"""2-qadam: MASTER LLM — "map-explainer" uslubi (doc B1 sxemasi).

Har qanday geografiya/geosiyosat mavzusi uchun to'liq reja:
ovoz matni + on_screen + rejim (map/stock) + xarita kameralari +
bayroq-fill davlatlar + rangli highlight so'zlar + events (pin/line/
arrow/highlight/flag_fill/zoom) + SFX + (stock uchun) qat'iy
visual_query/must_contain/reject.

Total: 118-130 so'z (35-40s @ +15% rate), hook = savol, infinite loop, outro YO'Q.
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
YouTube Shorts studio. Benchmark: the "map-explainer" format (e.g. "Why isn't
the USA annexing Canada?" — 19s, millions of views). The entire video plays on
an ANIMATED WORLD MAP with country-flag fills, glowing highlights, pins and
arrows that pop in sync with the narration. You think in SHOTS and EVENTS,
never paragraphs. Palette: dark navy map, white text, cyan/red/yellow
accents."""

# ================= MASTER USER PROMPT =================
PROMPT_TMPL = """Today's topic: "{topic}" (niche: {niche}).
Audience: USA, English, ages 13-40. Platform: YouTube Shorts (vertical 1080x1920).

{trend_block}
Recently used topics (STRICTLY avoid, also avoid reusing the same countries
as the primary subject): {hist}
{avoid}
DIRECT A 35-40 SECOND SHORT about "{topic}".

VOICEOVER RULES (hard limits):
- Total 118-130 words (voice at +15% speed must fill 35-40 s).
  Each scene's "voice" is 14-18 words — COUNT the words in every line
  before answering; short lines are rejected. 7-8 scenes.
  First sentence = a provocative QUESTION in ~10 words;
  motion must happen on screen within 0.5s of the start.
- FORBIDDEN: "Did you know", "Top 5", "Welcome", any intro, any "like and
  subscribe", any outro/CTA.
- Sentences 14-18 words each, punchy, zero filler. Present tense, active voice.
- The LAST sentence is a complete thought ending in a question that the HOOK
  answers (seamless infinite loop on replay). Never end mid-sentence.
- Facts must be real and verifiable (borders, treaties, geography).

SCENE RULES:
- 5-8 scenes. AT LEAST 70% of scenes use "mode": "map".
- "mode": "stock" (max 30%) ONLY when a human reaction adds punch (crowds,
  border crossing, traffic). NO real politicians or public figures — generic
  people only.
- EVERY scene (including stock) still carries map data as fallback.

STRICT OUTPUT — one JSON object, no markdown, no commentary:
{{
  "title": "<<=70 chars, curiosity gap>",
  "description": "<2-3 sentences>",
  "pinned_comment": "<question that drives comments>",
  "scenes": [
    {{
      "id": 1,
      "voice": "<spoken line, 14-18 words — count them>",
      "on_screen": "<ALL-CAPS 2-4 word headline>",
      "mode": "map",
      "map": {{"focus": "<place name>", "lat": <real lat>, "lon": <real lon>,
               "zoom_level": <3=continent .. 12=city street>,
               "motion": "zoom_in" | "zoom_out"}},
      "country_iso_codes": ["<ISO2 of countries to FILL WITH THEIR FLAG>", "..."],
      "highlights": [
        {{"word": "<exact word from voice>", "color": "#00E5FF|#FF2D2D|#FFD400"}}
      ],
      "events": [
        {{"at_word": "<exact word from voice>", "type": "pin",
          "target": "<ISO2 or place>", "lat": <opt>, "lon": <opt>}},
        {{"at_word": "...", "type": "line", "target": "BE-NL"}},
        {{"at_word": "...", "type": "arrow", "dir": "left|right|up|down"}},
        {{"at_word": "...", "type": "highlight", "target": "<ISO2>"}},
        {{"at_word": "...", "type": "flag_fill", "target": "<ISO2>"}},
        {{"at_word": "...", "type": "zoom"}}
      ],
      "sfx_trigger": ["<pop|whoosh|ding|boom|alarm|riser>"],
      "fact_source": "<short source name for the scene's claim, e.g. Britannica / CIA World Factbook / UN>",
      "fallback": "map_zoom:<place>",
      "duration_s": 4,
      "visual_query": ["<ONLY for stock mode: 3 phrases>"],
      "must_contain": ["<only stock>"], "reject": ["<only stock>"]
    }}
  ]
}}

FACTS RULES:
- Every scene carries "fact_source" — a real, citable source for its claim.
  If you cannot name a credible source for a fact, REPLACE the fact with a
  verifiable one (vague claims get "fake" comments and kill retention).
- Use specific place names ("Hotel Arbez, La Cure", "Baarle-Hertog"),
  never "a bar somewhere".
- No claims about living politicians; no likeness of real people.

EVENTS RULES:
- 2-4 events per scene, each tied to an exact spoken word (at_word) — the
  visual appears the instant that word is said.
- highlights: 1-3 per scene; color = the country's flag dominant color or
  palette accent (cyan #00E5FF allies/groups, red #FF2D2D the "opponent",
  yellow #FFD400 attention).
- "line" target = two ISO2 joined by "-" (the shared border to draw).
- Coordinates must be real and verifiable.

STOCK SCENE QUERY RULES (visual_query — critical, past failures came from
ignoring these):
- Exactly 3 hierarchical phrases: specific -> broader -> generic.
- Each phrase is 2-3 ENGLISH words describing WHAT TO SHOW ON SCREEN:
  place/type + scene + optional action. Example scene "Order a beer in one
  country and pay in another" -> ["pub interior drinks",
  "bartender pouring beer", "european bar counter"].
- NEVER a lone generic object ("floor", "stool", "land", "wall") — such
  queries return wrong footage (a basketball court for "wooden floor").
- NEVER build queries from filler words ("or they land in...").
- "reject": wrong topics that could appear for these queries.
"""

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
                raise RuntimeError(f"Gemini {r.status_code}: {r.text[:120]}")
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


_EV_TYPES = ("pin", "line", "arrow", "highlight", "flag_fill", "zoom", "icon")


def _parse(raw):
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S)
    a, b = txt.find("{"), txt.rfind("}")
    if a != -1 and b > a and (a > 0 or b < len(txt) - 1):
        txt = txt[a:b + 1]
    data = json.loads(txt)

    segs = data.get("scenes") or data.get("segments") or []
    if not (5 <= len(segs) <= 8):
        raise ValueError(f"5-8 sahna kerak, {len(segs)} ta keldi")
    n_stock = 0
    for i, sc in enumerate(segs):
        if not sc.get("voice"):
            raise ValueError(f"{i + 1}-sahnada voice yo'q")
        # map (yangi sxema) yoki map_camera (eski) — ikkalasini qo'llab-quvvatla
        m = sc.get("map") or sc.get("map_camera") or {}
        try:
            m["lat"] = float(m.get("lat", 0) or 0)
            m["lon"] = float(m.get("lon", 0) or 0)
            m["zoom_level"] = max(3, min(12, int(float(m.get("zoom_level", 5) or 5))))
        except (TypeError, ValueError):
            m = {"lat": 0, "lon": 0, "zoom_level": 5}
        m.setdefault("motion", "zoom_in")
        m.setdefault("focus", "")
        sc["map"] = m
        sc.pop("map_camera", None)
        mode = str(sc.get("mode", "map")).lower()
        if mode == "stock" and sc.get("visual_query"):
            n_stock += 1
        else:
            mode = "map"
        sc["mode"] = mode
        sc["country_iso_codes"] = [str(c).upper()[:2] for c in
                                   _as_list(sc.get("country_iso_codes"))][:2]
        # highlights
        hls = []
        for h in _as_list(sc.get("highlights"))[:3]:
            if isinstance(h, dict) and h.get("word"):
                col = str(h.get("color", "#FFD400"))
                if not re.match(r"^#[0-9a-fA-F]{6}$", col):
                    col = "#FFD400"
                hls.append({"word": str(h["word"]), "color": col})
        sc["highlights"] = hls
        # events
        evs = []
        for e in _as_list(sc.get("events"))[:4]:
            if not isinstance(e, dict):
                continue
            k = str(e.get("type", "")).lower()
            if k not in _EV_TYPES:
                continue
            ev = {"type": k, "at_word": str(e.get("at_word", "")).lower()}
            if e.get("target") is not None:
                ev["target"] = str(e["target"])
            for f in ("dir", "lat", "lon", "pos", "emoji"):
                if e.get(f) is not None:
                    ev[f] = e[f]
            evs.append(ev)
        sc["events"] = evs
        # overlay_icons (orqa moslik)
        icons = []
        for ic in _as_list(sc.get("overlay_icons"))[:2]:
            if isinstance(ic, dict) and ic.get("emoji"):
                icons.append({"at_word": str(ic.get("at_word", "")).lower(),
                              "emoji": str(ic["emoji"]),
                              "pos": ic.get("pos") or [0.5, 0.3]})
        sc["overlay_icons"] = icons
        sc["sfx_trigger"] = [str(s) for s in _as_list(sc.get("sfx_trigger"))
                             if str(s) in ("pop", "whoosh", "ding", "boom",
                                           "alarm", "riser", "tick")][:2]
        vq = [str(q).strip() for q in _as_list(sc.get("visual_query"))
              if str(q).strip() and 1 < len(str(q).split()) <= 4][:3]
        sc["visual_query"] = vq
        sc["must_contain"] = [str(x).lower() for x in
                              _as_list(sc.get("must_contain"))][:5]
        sc["reject"] = [str(x).lower() for x in _as_list(sc.get("reject"))][:5]
        sc["on_screen"] = str(sc.get("on_screen", ""))[:40].upper()
        sc.setdefault("id", i + 1)
    # >=70% map (doc): stock ko'p bo'lsa ortiqchalarini map'ga aylantiramiz
    max_stock = max(1, int(len(segs) * 0.3))
    if n_stock > max_stock:
        for sc in segs:
            if n_stock <= max_stock:
                break
            if sc["mode"] == "stock":
                sc["mode"] = "map"
                n_stock -= 1

    data["title"] = str(data.get("title", "Geography Short"))[:100]
    data["hook"] = str(data.get("hook", segs[0]["voice"]))[:200]
    data["script"] = str(data.get("script",
                                  " ".join(s["voice"] for s in segs)))[:1500]
    data["keywords"] = [str(k) for k in data.get("keywords", [])][:8]
    data["description"] = str(data.get("description", "")).strip()[:4500]
    data["tags"] = [str(t).strip().lower() for t in data.get("tags", [])
                    if str(t).strip()][:20]
    data["hashtags"] = [re.sub(r"^#", "", str(h).strip()).lower()
                        for h in _as_list(data.get("hashtags"))
                        if str(h).strip()][:4]
    data["pinned_comment"] = str(data.get("pinned_comment", "")).strip()[:200]
    words = len(data["script"].split())
    lo, hi = globals().get("_WORD_LO", 112), globals().get("_WORD_HI", 138)
    if not (lo <= words <= hi):
        raise ValueError(f"script {words} so'z — 118-130 oralig'ida bo'lishi kerak")
    return data


def _parse_relaxed(raw):
    """Oxirgi zaxira: so'z oynasi 105-140 (pads/tempo 35-40s ni tuzatadi)."""
    global _WORD_LO, _WORD_HI
    _WORD_LO, _WORD_HI = 105, 140
    try:
        return _parse(raw)
    finally:
        _WORD_LO, _WORD_HI = 112, 138


def write_script(cfg, trends, history_kws, avoid_title=""):
    key = cfg["secrets"]["gemini_api_key"]
    primary = cfg["gemini"].get("model", MODELS[0])
    models = [primary] + [m for m in MODELS if m != primary]
    prompt, topic = _build_prompt(cfg, trends, history_kws, avoid_title)
    print(f"   kun mavzusi: {topic}")
    last_err, last_raw = None, None
    for model in models:
        for attempt in range(2):
            try:
                raw = _call(key, model, prompt, cfg)
                data = _parse(raw)
                data["_topic"] = topic
                return data
            except Exception as e:
                last_err, last_raw = e, raw
                print(f"[script] {model} urinish {attempt + 1}: {str(e)[:120]}")
                if ("not found" in str(e).lower()
                        or "not_found" in str(e).lower()
                        or "429" in str(e)):
                    break                      # modelni o'tkazib yuborish
                time.sleep(2)
    # zaxira: oxirgi javobni yumshoq oynada qabul qilamiz (crash o'rniga)
    if last_raw:
        try:
            data = _parse_relaxed(last_raw)
            data["_topic"] = topic
            print("[script] zaxira oyna (105-140 so'z) bilan qabul qilindi")
            return data
        except Exception:
            pass
    raise RuntimeError(f"Skript yozib bo'lmadi: {last_err}")
