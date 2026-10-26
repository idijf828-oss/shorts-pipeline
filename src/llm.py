"""Yordamchi LLM qatlami (v12.1) — faqat Gemini vision (stock QA).

Tashqi "eng kuchli model" kaliti BUTUNLAY O'CHIRILDI (user
2026-10-26). Skript generatsiyasi bu modulga
umuman tegmaydi — u seed bankasidan keladi (src/script_gen.py,
write_script). Bu modul faqat media._vision_check (stock kadr QA)
uchun zaxira: cfg["llm"]["allow_gemini"]=true bo'lgandagina ishlaydi,
standartda O'CHIRIK — barcha QA programmatik (OCR + piksel).
"""
import base64
import time

from src.net import session

_GEM_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent")
# 2026-10 holati: gemini-2.5-*/2.0-flash O'CHIRILGAN (404). Tirik modellar:
_GEM_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
]


def _gem_call(key, model, system, user, b64s, temperature, json_mode, timeout):
    """Gemini generateContent. (text, None) yoki (None, xato)."""
    parts = [{"text": user}]
    for b in b64s:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b}})
    gc = {"temperature": temperature}
    if json_mode:
        gc["response_mime_type"] = "application/json"
    try:
        r = session().post(
            _GEM_URL.format(model=model), params={"key": key},
            json={"system_instruction": {"parts": [{"text": system}]},
                  "contents": [{"role": "user", "parts": parts}],
                  "generationConfig": gc},
            timeout=timeout)
    except Exception as e:
        return None, f"{model}: tarmoq ({e})"
    if r.status_code == 429:
        return None, f"{model}: 429 (rate limit)"
    if r.status_code != 200:
        return None, f"{model}: {r.status_code}: {r.text[:100]}"
    data = r.json()
    cands = data.get("candidates") or []
    if not cands or not (cands[0].get("content") or {}).get("parts"):
        reason = ((cands[0].get("finishReason") if cands else None)
                  or data.get("promptFeedback", {}).get("blockReason", "?"))
        return None, f"{model}: javob bo'sh (finishReason={reason})"
    txt = "".join(p.get("text", "") for p in cands[0]["content"]["parts"])
    if not txt.strip():
        return None, f"{model}: bo'sh matn"
    return txt, None


def chat(cfg, system, user, images=None, json_mode=False,
         temperature=None, timeout=90):
    """Bitta matn javobi. images = jpg fayl yo'llari (vision).

    Faqat Gemini (vision QA uchun zaxira). Standartda O'CHIRIK:
    cfg["llm"]["allow_gemini"]=true bo'lmasa RuntimeError. Skript
    yozishda ishlatilmaydi — skriptlar seed bankadan (v12)."""
    if not bool((cfg.get("llm") or {}).get("allow_gemini", False)):
        raise RuntimeError(
            "LLM yo'li o'chirilgan (v12.1): skriptlar seed bankadan "
            "(script_bank/), QA programmatik. llm.allow_gemini=true "
            "faqat vision-zaxira uchun (user qoidasi: zaif modelga "
            "yashirin tushish taqiqlangan).")
    gkey = (cfg.get("secrets") or {}).get("gemini_api_key") or ""
    if not (gkey and gkey != "FAKE"):
        raise RuntimeError("GEMINI_API_KEY yo'q")
    b64s = []
    for p in (images or []):
        with open(p, "rb") as f:
            b64s.append(base64.b64encode(f.read()).decode())
    t = 0.8 if temperature is None else temperature
    errs = []
    primary = cfg.get("gemini", {}).get("model")
    models = ([primary] if primary in _GEM_MODELS else [])
    models += [m for m in _GEM_MODELS if m != primary]
    for m in models:
        for att in range(2):
            txt, err = _gem_call(gkey, m, system, user, b64s, t,
                                 json_mode, timeout)
            if txt is not None:
                return txt
            errs.append(err)
            print(f"[llm] {err}")
            if "429" in err and att == 0:
                time.sleep(5 * (att + 1))
                continue
            break                                    # keyingi model
    raise RuntimeError("LLM javob bermadi: " + "; ".join(errs[-3:]))


def provider(cfg):
    """Foydalanilayotgan provayder nomi (log uchun)."""
    if bool((cfg.get("llm") or {}).get("allow_gemini", False)):
        gkey = (cfg.get("secrets") or {}).get("gemini_api_key") or ""
        if gkey and gkey != "FAKE":
            return "Gemini " + str((cfg.get("gemini") or {}).get("model")
                                   or _GEM_MODELS[0])
    return "YO'Q (skriptlar seed bankadan — LLM kerak emas)"
