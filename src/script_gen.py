"""2-qadam: Gemini API orqali 100% YANGI asl skript yozish.

Mantiq: trend tahlili + tarix (takrorlanmasin) -> 7 sahna JSON.
Takroriy urinishlar + JSON tekshiruvi.
"""
import json
import re
import time

from src.net import session

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite"]

SYSTEM = """You are a sharp comedic scriptwriter for a US YouTube Shorts channel
(relatable everyday humor for ages 16-40). Write fresh, original jokes only:
never copy other creators' jokes, memes, or viral punchlines. Tone: natural,
conversational American English, like telling a friend a funny story."""


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
    return f"""Channel niche: {ch['niche']}.
Topics: {', '.join(ch['topics'])}. Audience: USA, English, ages 16-40.

WHAT IS TRENDING IN THIS NICHE (US, last {cfg['sources']['days_back']} days):
{top_titles}
Most-used words: {', '.join(sm.get('top_words', [])[:10])}
Common hashtags: {', '.join('#' + h for h in sm.get('hashtags', [])[:8])}
Popular formats seen: {', '.join(sm.get('formats_seen', [])) or 'none detected'}
Average title length: {sm.get('avg_title_len', 0)} chars; top-10 avg views: {sm.get('avg_views_top10', 0):,}

ALREADY-USED TOPICS (do NOT repeat these):
{hist}
{avoid}
WRITE A NEW, ORIGINAL 7-SCENE SHORTS SCRIPT:
Scene 1 = HOOK (first 2 seconds, a punchy question/statement that grabs attention).
Scenes 2-6 = countdown #5, #4, #3, #2, #1 (one funny everyday situation each: work, school, tech fails, family or social life).
Scene 7 = OUTRO (1-2 sentences asking viewers to comment their own situation).

Rules:
- Total narration ~110-135 words (spoken duration 40-50 seconds).
- Every situation must be your own invented joke, not a copied/known meme or another creator's bit.
- narration: plain spoken English, 8-18 words per scene.
- overlay: on-screen text for that scene, max 8 words, ALL CAPS where funny.
- badge: "WAIT FOR IT" for the hook, "#5".."#1" for countdown scenes, "COMMENT!" for outro.
- pexels_query: simple 2-4 word English search describing generic footage for the scene (objects, places, actions — no people's faces as the joke).

Return ONLY this JSON, nothing else:
{{"title": "video title under 70 chars with an emoji",
  "keywords": ["3-6 topic keywords"],
  "scenes": [
    {{"type": "hook", "badge": "WAIT FOR IT", "overlay": "...", "narration": "...", "pexels_query": "..."}},
    {{"type": "countdown", "number": 5, "badge": "#5", "overlay": "...", "narration": "...", "pexels_query": "..."}},
    ... scenes for 4,3,2,1 ...
    {{"type": "outro", "badge": "COMMENT!", "overlay": "...", "narration": "...", "pexels_query": "..."}}
  ]}}"""


def _parse(raw):
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S)
    data = json.loads(txt)
    scenes = data.get("scenes", [])
    if len(scenes) != 7:
        raise ValueError(f"7 sahna kerak, {len(scenes)} ta keldi")
    nums = [sc.get("number") for sc in scenes if sc.get("type") == "countdown"]
    if sorted(nums) != [1, 2, 3, 4, 5]:
        raise ValueError("countdown raqamlari 5..1 bo'lishi kerak")
    for sc in scenes:
        if not sc.get("narration") or not sc.get("pexels_query"):
            raise ValueError("bo'sh narration/pexels_query")
    data["title"] = str(data.get("title", "Top 5 Funny Everyday Situations"))[:100]
    data["keywords"] = [str(k) for k in data.get("keywords", [])][:8]
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
                time.sleep(2)
    raise RuntimeError(f"Skript yozib bo'lmadi: {last_err}")
