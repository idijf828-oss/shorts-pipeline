"""Birlashtirilgan LLM qatlami (v6).

Zanjir: ANTHROPIC_API_KEY borida Claude Opus 5.5 (matn + vision),
xatoda Claude Sonnet 5.5, so'ng Gemini modellari. Barcha LLM
chaqiruvlari (skript generatsiyasi, vision tekshiruv) faqat shu
modul orqali — script_gen/media to'g'ridan-to'g'ri API chaqirmaydi.
"""
import base64
import time

from src.net import session

_ANT_URL = "https://api.anthropic.com/v1/messages"
_ANT_VER = "2023-06-01"
_ANT_MODELS = [
    "claude-opus-5-5",     # eng kuchli (2026-09-22)
    "claude-sonnet-5-5",   # tezroq zaxira
]
_GEM_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent")
# 2026-10 holati: gemini-2.5-*/2.0-flash O'CHIRILGAN (404). Tirik modellar:
_GEM_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
]


def _ant_call(key, model, system, content, temperature, timeout):
    """Anthropic Messages API. (text, None) yoki (None, xato)."""
    try:
        r = session().post(
            _ANT_URL,
            headers={"x-api-key": key, "anthropic-version": _ANT_VER},
            json={"model": model, "max_tokens": 12000,
                  "system": system, "temperature": temperature,
                  "messages": [{"role": "user", "content": content}]},
            timeout=timeout)
    except Exception as e:
        return None, f"{model}: tarmoq ({e})"
    if r.status_code == 429:
        return None, f"{model}: 429 (rate limit)"
    if r.status_code != 200:
        return None, f"{model}: {r.status_code}: {r.text[:100]}"
    data = r.json()
    txt = "".join(b.get("text", "") for b in data.get("content", [])
                  if isinstance(b, dict) and b.get("type") == "text")
    if not txt.strip():
        return None, f"{model}: javob bo'sh (stop={data.get('stop_reason')})"
    return txt, None


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
    v10.2 (user qoidasi): ENG KUCHLI MODEL SHART — faqat Anthropic
    (Claude Opus 5.5 -> Sonnet 5.5). Kalit yo'q = RuntimeError (sir
    saqlanadi, zaif modelga yashirin tushish YO'Q). Gemini faqat
    cfg["llm"]["allow_gemini"]=true bayrog'i bilan (test rejim)."""
    b64s = []
    for p in (images or []):
        with open(p, "rb") as f:
            b64s.append(base64.b64encode(f.read()).decode())
    t = 0.8 if temperature is None else temperature
    errs = []

    akey = (cfg.get("secrets") or {}).get("anthropic_api_key") or ""
    allow_gemini = bool((cfg.get("llm") or {}).get("allow_gemini", False))
    if not (akey and akey != "FAKE") and not allow_gemini:
        raise RuntimeError(
            "ANTHROPIC_API_KEY yo'q — eng kuchli model (Claude Opus) "
            "shart. Zaif modelga tushish taqiqlangan (user qoidasi). "
            "Kalitni GitHub secret sifatida qo'shing.")
    if akey and akey != "FAKE":
        content = [{"type": "text", "text": user}]
        for b in b64s:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg", "data": b}})
        models = [cfg.get("anthropic", {}).get("model") or _ANT_MODELS[0]]
        models += [m for m in _ANT_MODELS if m not in models]
        for m in models:
            for att in range(2):
                txt, err = _ant_call(akey, m, system, content, t, timeout)
                if txt is not None:
                    return txt
                errs.append(err)
                print(f"[llm] {err}")
                if "429" in err and att == 0:
                    time.sleep(5 * (att + 1))
                    continue
                break                                # keyingi model

    gkey = (cfg.get("secrets") or {}).get("gemini_api_key") or ""
    if gkey and gkey != "FAKE" and allow_gemini:
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
                break                                # keyingi model

    raise RuntimeError("LLM javob bermadi: " + "; ".join(errs[-3:]))


def provider(cfg):
    """Foydalanilayotgan provayder nomi (log uchun)."""
    akey = (cfg.get("secrets") or {}).get("anthropic_api_key") or ""
    if akey and akey != "FAKE":
        return "Claude " + (cfg.get("anthropic", {}).get("model")
                            or _ANT_MODELS[0])
    if bool((cfg.get("llm") or {}).get("allow_gemini", False)):
        return "Gemini " + str((cfg.get("gemini") or {}).get("model")
                               or _GEM_MODELS[0])
    return "YO'Q (ANTHROPIC_API_KEY kerak)"
