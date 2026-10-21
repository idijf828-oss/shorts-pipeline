"""2-qadam: MASTER LLM — Info Hub uslubi (18-25s, xarita-asosli).

Har qanday geografiya/geosiyosat mavzusi uchun LLM shu prompt bilan
to'liq reja chiqaradi: ovoz matni + xarita kameralari (lat/lon/zoom) +
bayroq bilan ajratiladigan davlatlar (ISO2) + kalit so'zda paydo
bo'luvchi ikonkalar + SFX triggerlari + (faqat kerak bo'lsa) b-roll.

Total: 55-75 so'z (18-25 sekund), infinite loop, outro YO'Q.
"""
import datetime
import json
import re
import time

from src.net import session

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# 2026-10 holati: gemini-2.5-*/2.0-flash O'CHIRILGAN (404). Tirik modellar:
MODELS = [
    "gemini-3.5-flash-lite",   # tez, arzon (asosiy)
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
]

# ================= MASTER SYSTEM PROMPT =================
SYSTEM = """You are the head writer and director of a viral geography/geopolitics
YouTube Shorts studio (benchmark: channels like "Info Hub" — 9M+ view shorts
such as "Why isn't USA attacking Canada"). You design fast, visual, high-
retention 18-25 second videos built on ANIMATED SATELLITE MAPS, not stock
footage. Every second must carry new visual information. You think in
SHOTS (map camera moves), not paragraphs."""

# ================= MASTER USER PROMPT =================
PROMPT_TMPL = """Today's topic: "{topic}" (niche: {niche}).
Audience: USA, English, ages 13-40. Platform: YouTube Shorts (vertical).

{trend_block}
Recently used topics (STRICTLY avoid, also avoid reusing the same countries
as the primary subject): {hist}
{avoid}
DIRECT A 18-25 SECOND SHORT about "{topic}".

VOICEOVER RULES (hard limits):
- Total 55-75 words. Hook = first sentence (~8-10 words), a concrete,
  provocative image or question. FORBIDDEN: "Did you know", "Top 5",
  "Welcome", any intro, any "like and subscribe", any outro.
- Sentences max 12 words, punchy, zero filler. Present tense, active voice.
- The LAST sentence is deliberately unfinished and loops back to the hook
  (seamless infinite loop when the video replays).

SHOT DESIGN RULES (this is a MAP video):
- 4-7 segments. EACH segment = one map camera shot + 1-2 spoken sentences.
- Segment 1 (hook): the most dramatic location, zoom_level high (10-14).
- Every segment MUST have map_camera with real, verifiable coordinates
  (lat, lon) of the actual place being discussed, and a zoom_level:
  3-5 = continent/country, 6-8 = region, 9-11 = city, 12-14 = street/building.
- country_iso_codes: ISO2 codes of countries to HIGHLIGHT WITH THEIR FLAG
  fill in that shot (max 2 per segment, only the ones being discussed).
- overlay_icons: 0-2 per segment. Each appears exactly when its keyword is
  spoken. Emoji must be a SINGLE emoji (OpenMoji sticker). pos = [x, y]
  fractions of the 1080x1920 frame (keep inside [0.2..0.8] x [0.15..0.75]
  so it never covers the center captions). Use arrows (arrow_right etc.)
  to point at places, jets/weapons/money faces for geopolitics.
- sfx_trigger: 0-2 per segment from: pop, whoosh, ding, boom, alarm.
  (pop = icon/flag appears, whoosh = camera change, boom/alarm = drama).
- fallback_broll_query: ONLY if this segment truly needs a HUMAN reaction
  close-up (face, crowd, protest). Otherwise empty list. If used: 2-3 word
  ultra-specific query ("crowd protesting street", "shocked man face").

TITLE (pick the strongest): concrete image + curiosity gap, under 70 chars,
max 1 emoji. Examples of the style: "The Bar That Sits in Two Countries",
"Why USA Doesn't Invade Canada", "The Border Drawn by a Drunk King".

DESCRIPTION template: line 1 = hook sentence; 2 short fact sentences;
"Which {topic} should I cover next? Comment below 👇"; "New geography
short every day." Plain text, no hashtags inside.

Return ONLY valid JSON, nothing else:
{{
  "title": "...",
  "hook": "<first sentence, same as segment 1 voice>",
  "script": "<full voiceover text, one string>",
  "keywords": ["3-6"],
  "tags": ["12-15 lowercase"],
  "hashtags": ["shorts", "geography", "<topic>"],
  "description": "...",
  "pinned_comment": "Which {topic} should I cover next? 👇",
  "segments": [
    {{"id": 1,
      "voice": "...",
      "map_camera": {{"lat": 51.44, "lon": 4.93, "zoom_level": 13,
                       "motion": "zoom_in", "label": "Baarle-Hertog"}},
      "country_iso_codes": ["NL", "BE"],
      "overlay_icons": [{{"at_word": "bar", "emoji": "🍺",
                           "pos": [0.5, 0.30]}}],
      "sfx_trigger": ["whoosh"],
      "fallback_broll_query": []
    }},
    ... 4-7 segments total ...
    {{"id": N, "voice": "<unfinished loop-back line>", "map_camera": {{...}},
      "country_iso_codes": [], "overlay_icons": [], "sfx_trigger": [],
      "fallback_broll_query": []}}
  ]
}}"""


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
                        "temperature": cfg["gemini"].get("temperature", 0.8),
                    },
                },
                timeout=timeout,
            )
            if r.status_code == 429 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
            data = r.json()
            cands = data.get("candidates") or []
            if not cands or not (cands[0].get("content") or {}).get("parts"):
                reason = ((cands[0].get("finishReason") if cands else None)
                          or data.get("promptFeedback", {}).get("blockReason", "?"))
                raise RuntimeError(f"Gemini javob bo'sh (finishReason={reason})")
            return "".join(p.get("text", "") for p in cands[0]["content"]["parts"])
        except RuntimeError:
            raise
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"Gemini bilan bog'lanib bo'lmadi: {e}")
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("Gemini javob bermadi")


def _build_prompt(cfg, trends, history_kws, avoid_title=""):
    ch = cfg["channel"]
    sm = trends.get("summary", {})
    tops = sm.get("top_titles", [])[:6]
    trend_block = ""
    if tops:
        trend_block = ("Trending in this niche (US, last "
                       f"{cfg['sources']['days_back']} days):\n"
                       + "\n".join(f"- {t['title']} ({t['views']:,} views)"
                                   for t in tops))
    hist = ", ".join(history_kws[-20:]) if history_kws else "(none — first video)"
    avoid = (f"AVOID this exact topic (already generated today): {avoid_title}\n"
             if avoid_title else "")
    topics = ch["topics"]
    yday = datetime.datetime.now(datetime.UTC).timetuple().tm_yday
    topic = topics[yday % len(topics)]
    return PROMPT_TMPL.format(topic=topic, niche=ch["niche"],
                              trend_block=trend_block, hist=hist, avoid=avoid), topic


def _as_list(v):
    if isinstance(v, str):
        return [v]
    return list(v or [])


def _parse(raw):
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S)
    a, b = txt.find("{"), txt.rfind("}")
    if a != -1 and b > a and (a > 0 or b < len(txt) - 1):
        txt = txt[a:b + 1]
    data = json.loads(txt)

    segs = data.get("segments") or data.get("scenes") or []
    if not (4 <= len(segs) <= 7):
        raise ValueError(f"4-7 segment kerak, {len(segs)} ta keldi")
    for i, sc in enumerate(segs):
        if not sc.get("voice"):
            raise ValueError(f"{i + 1}-segmentda voice yo'q")
        cam = sc.get("map_camera") or {}
        try:
            cam["lat"] = float(cam.get("lat", 0) or 0)
            cam["lon"] = float(cam.get("lon", 0) or 0)
            cam["zoom_level"] = int(float(cam.get("zoom_level", 6) or 6))
            cam["zoom_level"] = max(2, min(16, cam["zoom_level"]))
        except (TypeError, ValueError):
            cam = {"lat": 0, "lon": 0, "zoom_level": 6}
        cam.setdefault("motion", "zoom_in")
        cam.setdefault("label", "")
        sc["map_camera"] = cam
        sc["country_iso_codes"] = [str(c).upper()[:2] for c in
                                   _as_list(sc.get("country_iso_codes"))][:2]
        icons = []
        for ic in _as_list(sc.get("overlay_icons"))[:2]:
            if not isinstance(ic, dict):
                continue
            emoji = str(ic.get("emoji", "")).strip()
            pos = ic.get("pos") or [0.5, 0.3]
            try:
                pos = [max(0.15, min(0.85, float(pos[0]))),
                       max(0.12, min(0.75, float(pos[1])))]
            except (TypeError, ValueError):
                pos = [0.5, 0.3]
            icons.append({"at_word": str(ic.get("at_word", "")).lower().strip(),
                          "emoji": emoji, "pos": pos})
        sc["overlay_icons"] = icons
        sc["sfx_trigger"] = [str(s) for s in _as_list(sc.get("sfx_trigger"))
                             if str(s) in ("pop", "whoosh", "ding",
                                           "boom", "alarm", "riser")][:2]
        sc["fallback_broll_query"] = [str(q) for q in
                                      _as_list(sc.get("fallback_broll_query"))][:3]
        sc.setdefault("id", i + 1)

    data["title"] = str(data.get("title", "Geography Short"))[:100]
    data["hook"] = str(data.get("hook", segs[0]["voice"]))[:200]
    data["script"] = str(data.get("script",
                                  " ".join(s["voice"] for s in segs)))[:1200]
    data["keywords"] = [str(k) for k in data.get("keywords", [])][:8]
    data["description"] = str(data.get("description", "")).strip()[:4500]
    data["tags"] = [str(t).strip().lower() for t in data.get("tags", [])
                    if str(t).strip()][:20]
    data["hashtags"] = [re.sub(r"^#", "", str(h).strip()).lower()
                        for h in _as_list(data.get("hashtags"))
                        if str(h).strip()][:4]
    data["pinned_comment"] = str(data.get("pinned_comment", "")).strip()[:200]
    words = len(data["script"].split())
    if not (40 <= words <= 95):
        raise ValueError(f"script {words} so'z — 55-75 oralig'ida bo'lishi kerak")
    return data


def write_script(cfg, trends, history_kws, avoid_title=""):
    key = cfg["secrets"]["gemini_api_key"]
    primary = cfg["gemini"].get("model", MODELS[0])
    models = [primary] + [m for m in MODELS if m != primary]
    prompt, topic = _build_prompt(cfg, trends, history_kws, avoid_title)
    print(f"   kun mavzusi: {topic}")
    last_err = None
    for model in models:
        for attempt in range(2):
            try:
                raw = _call(key, model, prompt, cfg)
                data = _parse(raw)
                data["_topic"] = topic
                return data
            except Exception as e:
                last_err = e
                print(f"[script] {model} urinish {attempt + 1}: {e}")
                if "not found" in str(e).lower() or "not_found" in str(e).lower():
                    break
                time.sleep(2)
    raise RuntimeError(f"Skript yozib bo'lmadi: {last_err}")
