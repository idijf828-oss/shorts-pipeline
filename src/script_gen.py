"""2-qadam: Gemini API orqali 100% YANGI geografiya-faktlar skripti.

Mantiq: trend tahlili + tarix (takrorlanmasin) -> 7 sahna JSON.
Retention: curiosity-gap hook, "oxirigacha ko'r" istagi, like CTA.
Metadata: professional title, description, tags, hashtags ham shu yerda.
"""
import datetime
import json
import re
import time

from src.net import session

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# 2026-10 holati: gemini-2.5-*/gemini-2.0-flash O'CHIRILGAN (404 qaytaradi).
# Faqat hozirgi TIRIK modellar (barchasi bepul tier'da mavjud):
MODELS = [
    "gemini-3.5-flash-lite",   # tez, arzon (asosiy tanlov)
    "gemini-3.1-flash-lite",   # arzon zaxira
    "gemini-3.8-flash",        # kuchliroq zaxira
    "gemini-3.6-flash",        # oxirgi zaxira
]

SYSTEM = """You are a professional documentary scriptwriter and fact researcher
for a US YouTube Shorts channel about geography, countries and world facts
(audience ages 13-40). Use ONLY well-known, verifiable facts (atlas /
encyclopedia level) — never invent statistics, borders or records. Tone:
authoritative, curious and cinematic, like a high-quality nature documentary
narration, but in natural conversational American English."""


def _call(key, model, prompt, cfg, timeout=90):
    s = session()
    for attempt in range(3):
        try:
            r = s.post(
                API.format(model=model),
                params={"key": key},
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "response_mime_type": "application/json",
                        "temperature": cfg["gemini"].get("temperature", 0.9),
                    },
                },
                timeout=timeout,
            )
            if r.status_code == 429 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return txt
        except RuntimeError:
            raise
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"Gemini bilan bog'lanib bo'lmadi: {e}")
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("Gemini javob bermadi")


def _build_prompt(cfg, trends, history_kws, avoid_title=""):
    ch, v = cfg["channel"], cfg["video"]
    sm = trends.get("summary", {})
    top_titles = "\n".join(
        f"- {t['title']} ({t['views']:,} views)" for t in sm.get("top_titles", [])[:8]
    )
    hist = ", ".join(history_kws[-25:]) if history_kws else "(hech narsa — birinchi video)"
    avoid = f"\nAVOID this exact topic too (already generated today): {avoid_title}\n" if avoid_title else ""
    # Kun mavzusi: deterministik tanlanadi (har kuni boshqa mavzu, takrorlanmasin)
    topics = ch["topics"]
    yday = datetime.datetime.now(datetime.UTC).timetuple().tm_yday
    topic = topics[yday % len(topics)]
    return f"""Channel niche: {ch['niche']} — geography & country facts.
TODAY'S ASSIGNED TOPIC: "{topic}".
Audience: USA, English, ages 13-40.

WHAT IS TRENDING IN THIS NICHE (US, last {cfg['sources']['days_back']} days):
{top_titles}
Most-used words: {', '.join(sm.get('top_words', [])[:10])}
Common hashtags: {', '.join('#' + h for h in sm.get('hashtags', [])[:8])}
Popular formats seen: {', '.join(sm.get('formats_seen', [])) or 'none detected'}

ALREADY-USED TOPICS (do NOT repeat these):
{hist}
{avoid}
WRITE A NEW, FACT-CHECKED 7-SCENE SHORTS SCRIPT about "{topic}":
Scene 1 = HOOK: a bold question or statement with a strong CURIOSITY GAP.
  Tease that fact #1 is the most unbelievable ("stay to the end...").
Scenes 2-6 = countdown facts #5, #4, #3, #2, #1 about the topic.
  Each fact: surprising, specific and TRUE (round numbers sensibly).
  Fact #1 must pay off the hook's tease — the best fact, saved for last.
Scene 7 = OUTRO: ask viewers which fact surprised them most + a direct,
  friendly like & subscribe ask (viewers who reach the end are the likers).

Retention rules (VERY important — this is a watch-to-the-end channel):
- The hook must create an open loop in the first 2 seconds.
- Every fact ends with a punchy wow-phrase, never a flat ending.
- Escalate interest: #5 interesting -> #1 jaw-dropping.

Rules:
- narration: plain spoken English, 8-18 words per scene, professional
  documentary tone. Total ~110-135 words (40-50 seconds spoken).
- overlay: on-screen text, max 8 words, ALL CAPS where punchy.
  ONLY plain letters, numbers, # and ! — NO emojis (render font).
- badge: "DID YOU KNOW" for the hook, "#5".."#1" for facts, "YOUR TURN" for outro.
- pexels_query: 2-4 word English b-roll search (aerial/drone/nature/map style):
  e.g. "aerial coastline", "desert aerial", "world map zoom", "mountain drone".
  No people close-ups, no text, no logos.

Return ONLY this JSON, nothing else:
{{"title": "curiosity-driven video title under 70 chars with 1 emoji",
  "keywords": ["3-6 topic keywords"],
  "tags": ["12-15 lowercase YouTube search tags"],
  "hashtags": ["3 hashtags without # symbol, e.g. geography facts shorts"],
  "description": "professional video description 400-600 chars: a hook line, what the viewer will learn, a like/subscribe call-to-action. Plain text, NO hashtags inside.",
  "scenes": [
    {{"type": "hook", "badge": "DID YOU KNOW", "overlay": "...", "narration": "...", "pexels_query": "..."}},
    {{"type": "countdown", "number": 5, "badge": "#5", "overlay": "...", "narration": "...", "pexels_query": "..."}},
    ... scenes for 4,3,2,1 ...
    {{"type": "outro", "badge": "YOUR TURN", "overlay": "...", "narration": "...", "pexels_query": "..."}}
  ]}}"""


def _parse(raw):
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S)
    # JSON'dan oldin/keyin ortiqcha matn bo'lsa, { ... } blokini kesib olish
    a, b = txt.find("{"), txt.rfind("}")
    if a != -1 and b > a and (a > 0 or b < len(txt) - 1):
        txt = txt[a:b + 1]
    data = json.loads(txt)
    scenes = data.get("scenes", [])
    if len(scenes) != 7:
        raise ValueError(f"7 sahna kerak, {len(scenes)} ta keldi")
    for sc in scenes:
        # Gemini ba'zan raqamlarni satr ("5") qaytaradi -> songa aylantiramiz
        if sc.get("type") == "countdown":
            try:
                sc["number"] = int(sc["number"])
            except (TypeError, ValueError):
                pass
    nums = [sc.get("number") for sc in scenes if sc.get("type") == "countdown"]
    if sorted(nums) != [1, 2, 3, 4, 5]:
        raise ValueError("countdown raqamlari 5..1 bo'lishi kerak")
    for sc in scenes:
        if not sc.get("narration") or not sc.get("pexels_query"):
            raise ValueError("bo'sh narration/pexels_query")
    data["title"] = str(data.get("title", "Top 5 Geography Facts You Won't Believe"))[:100]
    data["keywords"] = [str(k) for k in data.get("keywords", [])][:8]
    # Professional metadata (upload uchun)
    data["description"] = str(data.get("description", "")).strip()[:4500]
    data["tags"] = [str(t).strip().lower() for t in data.get("tags", [])
                    if str(t).strip()][:20]
    data["hashtags"] = [re.sub(r"^#", "", str(h).strip()).lower()
                        for h in data.get("hashtags", [])
                        if str(h).strip()][:4]
    return data


def write_script(cfg, trends, history_kws, avoid_title=""):
    key = cfg["secrets"]["gemini_api_key"]
    models = [cfg["gemini"].get("model", MODELS[0])] + [m for m in MODELS if m != cfg["gemini"].get("model")]
    prompt = _build_prompt(cfg, trends, history_kws, avoid_title)
    last_err = None
    for model in models:
        for attempt in range(2):
            try:
                raw = _call(key, model, prompt, cfg)
                return _parse(raw)
            except Exception as e:
                last_err = e
                print(f"[script] {model} urinish {attempt + 1}: {e}")
                # model topilmadi/o'chirilgan -> qayta urinmasdan keyingisiga
                if "not found" in str(e).lower() or "not_found" in str(e).lower():
                    break
                time.sleep(2)
    raise RuntimeError(f"Skript yozib bo'lmadi: {last_err}")
