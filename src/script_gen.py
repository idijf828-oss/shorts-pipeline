"""2-qadam: MASTER LLM — MAP EXPLAINER (v10, qo'llanma: map-explainer-video).

Format: bitta savol ("Why isn't the US annexing Canada?") + 2-3 sabab +
CTA savol. 45-70 so'z, 15-35s. Vizuallar: satellite xarita asosiy
(bayroq-poligon, strelka, sticker, davlat nomi yorlig'i), 2 ta qisqa
stock insert. So'zma-so'z markaz subtitr, kalit so'z cyan.
"""
import datetime
import difflib
import json
import random
import re

from src import llm

# Hikoya temalari (kun+slot bo'yicha aylanadi; trend so'rovlari
# config'dagi topics ro'yxatidan alohida)
THEMES = [
    # v10 aralash mavzular (user: savol + chegara joyi + hayratlanarli fakt)
    "a geopolitics why-question (why isn't / why doesn't a country do X)",
    "a strange border place explained (why is this town in two countries?)",
    "a surprising geography fact (why does a border/river/island look like this?)",
    "a tiny country or enclave and why it still exists",
    "an island, sea or river two countries disagree about",
    "why a border wall, fence or crossing is exactly there",
    "how geography made a country rich, safe or isolated",
    "a weird-looking border on the map and the story behind it",
    "why two countries share one thing (island, mountain, city, port)",
    "a place that changed countries and why",
    "why a huge country has almost no coastline or no neighbors",
    "a map oddity: panhandles, holes and dead-end borders",
]

# ================= MASTER SYSTEM PROMPT =================
SYSTEM = """You are the writer-director of a viral geography and
geopolitics YouTube Shorts channel. Every short answers ONE surprising
real-world question on a satellite map — "Why isn't the US annexing
Canada?", "Why is this village in two countries?". One question, two or
three concrete reasons, one closing line that invites the next question.
Fast, clear, factual, neutral on political topics. Perfect American
English — zero typos, zero filler."""



# ================= MASTER USER PROMPT =================
PROMPT_TMPL = """Answer ONE surprising question that fits this theme: {theme}.
The question must be real, answerable with 2-3 concrete geographical or
historical reasons, and verifiable. Niche: {niche}. Audience: USA,
English, ages 13-40. Platform: YouTube Shorts (vertical 1080x1920).

{trend_block}
Recently covered questions/topics (STRICTLY avoid anything similar): {hist}
{avoid}
Write a 15-30 SECOND map-explainer short: 45-70 words total,
6-8 scenes.

NARRATION — FAST EXPLAINER VOICE (150-170 words/min, no pauses wasted):
- Scene 1 (HOOK, 5-8 words): the question itself, ending with "?".
  Example: "Why isn't the US simply annexing Canada?"
- Scenes 2-6 (REASONS, 7-12 words each): one reason per beat. Concrete
  facts, real numbers, real names. Natural flow or "First / Second".
  The strongest reason LAST.
- Final scene (CLOSE + CTA, 6-10 words): one-line answer summary, then
  a short question that invites the next video, ending with "?".
- Active voice. Every line adds NEW information. NEVER "did you know",
  intros, thank-yous, or hype. No exclamation marks.
- Neutral, factual tone on political topics — explain, never take sides.

VISUALS — SATELLITE MAP is the star (guide style):
- Most scenes are map scenes: "mode": "map" with focus/lat/lon and
  zoom_level (3=continent, 5=whole country, 7=region, 9=city).
  The camera slowly zooms; the topic change is a hard cut.
- Give each map scene 1-3 "events" from:
  "flag_fill" target ISO2 — fills the country with its flag texture
  (use for the 1-2 main countries);
  "highlight" target ISO2 — cyan ally/ bloc fill;
  "arrow" dir up/down/left/right — big yellow arrow (pressure, movement);
  "icon" emoji — one sticker per event: handshake, siren, money bag, rocket, warning sign, checkered flag (use the actual emoji characters);
  "label" target — a small black name tag on the country (country name).
- EXACTLY 2 scenes are stock inserts: "mode": "stock" with
  visual_query = 3 hierarchical phrases (2-3 words each) about filmable
  real-world b-roll (e.g. ["protest crowd street", "angry crowd signs",
  "demonstration city"]). Inserts are 1-2 seconds, subtitles continue.
- "highlights": at most 1 keyword per scene, color "#22D3EE" — the
  word shown BIG and cyan in the subtitles. Pick the punch words.

OUTPUT — ONE JSON object, no markdown, no commentary:
{{
  "question": "<the full question>",
  "place": "<main place or ''>",
  "country": "<main country or 'US-CA' style pair>",
  "title": "<<=70 chars, the question, 'Why ...?' pattern>",
  "description": "<2-3 sentences>",
  "pinned_comment": "<CTA question driving comments>",
  "keywords": ["<place/question keywords>", "..."],
  "hashtags": ["<3-4 tags like geopolitics, maps, shorts>"],
  "scenes": [
    {{
      "id": 1,
      "voice": "<hook question, 5-8 words, ends with ?>",
      "mode": "map",
      "map": {{"focus": "<place>", "lat": <real lat>, "lon": <real lon>,
               "zoom_level": <3-9>, "motion": "zoom_in"}},
      "country_iso_codes": ["<ISO2>", "<ISO2>"],
      "events": [{{"type": "flag_fill", "target": "US", "at_word": "..."}},
                 {{"type": "label", "target": "United States", "at_word": "..."}}],
      "highlights": [{{"word": "<keyword>", "color": "#22D3EE"}}],
      "sfx_trigger": [],
      "fact_source": "<credible source>",
      "visual_query": [],
      "must_contain": [],
      "reject": []
    }},
    {{ ... scenes 2-6: reasons; 2 of them "mode": "stock" inserts ... }},
    {{ ... final scene: close + CTA question ... }}
  ]
}}
"""


_WORD_LO, _WORD_HI = 45, 70


def _pick_theme():
    """Kun+slot bo'yicha determin tema (3 run/kun har xil)."""
    now = datetime.datetime.now(datetime.UTC)
    slot = (now.hour + 1) // 8                 # 3 run/kun: 0/1/2
    return THEMES[(now.timetuple().tm_yday * 8 + slot) % len(THEMES)]


def _build_prompt(cfg, trends, history_kws, avoid_title=""):
    ch = cfg["channel"]
    sm = (trends or {}).get("summary", {})
    tops = sm.get("top_titles", [])[:6]
    trend_block = ""
    if tops:
        trend_block = (f"Trending in this niche (US, last "
                       f"{cfg['sources']['days_back']} days):\n"
                       + "\n".join(f"- {t['title']} ({t['views']:,} views)"
                                   for t in tops))
    theme = _pick_theme()
    hist = ", ".join(history_kws[-20:]) if history_kws else "(none yet)"
    avoid = (f"DO NOT use the place from this already-generated title "
             f"today: {avoid_title}\n" if avoid_title else "")
    prompt = PROMPT_TMPL.format(theme=theme, niche=ch["niche"],
                                trend_block=trend_block, hist=hist,
                                avoid=avoid)
    return prompt, theme


def _as_list(v):
    if isinstance(v, str):
        return [v]
    return list(v or [])


_EV_TYPES = ("pin", "line", "arrow", "highlight", "flag_fill", "zoom",
              "icon", "label")

# ASCII + imzo belgilaridan boshqa belgi bo'lmasin (ideal yozuvlar)
_OK_EXTRA = set("\u2019\u2018\u201c\u201d\u2013\u2014\u2026%")


def _lint_voice(v, i):
    """Ideal matn mezoni: har qoidabuzarlik urinishni yiqitadi."""
    v = v.strip()
    if not v:
        return f"{i + 1}-sahna: voice bo'sh"
    if re.search(r"\s{2,}", v):
        return f"{i + 1}-sahna: ikki probel"
    if re.search(r"\s[,.;:!?]", v):
        return f"{i + 1}-sahna: tinish belgisidan oldin probel"
    if not v[0].isupper():
        return f"{i + 1}-sahna: kichik harf bilan boshlanadi"
    if v[-1] not in ".?!":
        return f"{i + 1}-sahna: tinish belgisisiz tugaydi"
    for ch in v:
        if ord(ch) > 127 and ch not in _OK_EXTRA:
            return f"{i + 1}-sahna: taqiqlangan belgi {ch!r}"
    return None


def _parse(raw):
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S)
    a, b = txt.find("{"), txt.rfind("}")
    if a != -1 and b > a and (a > 0 or b < len(txt) - 1):
        txt = txt[a:b + 1]
    # LLM'larning eng ko'p xatosi: oxirgi vergul (run 18: "line 27 col 9")
    txt = re.sub(r",\s*([\]}])", r"\1", txt)
    txt = re.sub(r"(?<=\d)\s+(?=\d)", "", txt)   # "5\n  million" emas
    data = json.loads(txt)

    segs = data.get("scenes") or data.get("segments") or []
    if not (5 <= len(segs) <= 9):
        raise ValueError(f"5-9 sahna kerak, {len(segs)} ta keldi")
    for i, sc in enumerate(segs):
        err = _lint_voice(str(sc.get("voice", "")), i)
        if err:
            raise ValueError(err)
        # map (yangi) yoki map_camera (eski) — ikkalasi ham
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
        mode = str(sc.get("mode", "stock")).lower()
        # v6: stock asosiy — faqat visual_query bor bo'lsa saqlanadi,
        # aks holda xarita zaxirasiga tushadi
        sc["mode"] = "stock" if (mode == "stock" and sc.get("visual_query")) \
            else "map"
        sc["country_iso_codes"] = [str(c).upper()[:2] for c in
                                   _as_list(sc.get("country_iso_codes"))][:2]
        hls = []
        for h in _as_list(sc.get("highlights"))[:3]:
            if isinstance(h, dict) and h.get("word"):
                col = str(h.get("color", "#FFD400"))
                if not re.match(r"^#[0-9a-fA-F]{6}$", col):
                    col = "#FFD400"
                hls.append({"word": str(h["word"]), "color": col})
        sc["highlights"] = hls
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
        # v9: pin bor sahnada over-zoom yo'q — davlat chegarasi ko'rinadi
        if any(ev["type"] == "pin" for ev in evs):
            m["zoom_level"] = min(m["zoom_level"], 9)
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
        sc["reject"] = [str(x).lower() for x in
                        _as_list(sc.get("reject"))][:5]
        sc["on_screen"] = str(sc.get("on_screen", "")).strip()
        mid = str(sc.get("mid_text") or "").strip()
        mw = mid.split()
        if not (1 <= len(mw) <= 3) or len(mid) > 24:
            mid = ""
        sc["mid_text"] = mid.upper()
        sc.setdefault("id", i + 1)

    # v9: texnik so'zlar (run 23'da "INFINITE LOOP" chiqdi) ASLO ko'rinmasin
    _BAN = {"INFINITE", "LOOP", "REPLAY", "REWIND", "AGAIN", "REWATCH",
            "NEXT", "VIDEO", "SUBSCRIBE", "SHORTS", "PART2", "PART"}
    # v8: on_screen = hikoya beat sarlavhasi (2-4 SO'Z, FACT YO'Q)
    for sc in segs:
        head = re.sub(r"^FACT\s*\d+\s*[-–—:]?\s*", "",
                      sc["on_screen"], flags=re.I)
        words = [w for w in head.split() if w.strip(".,!?-_").upper() not in _BAN]
        if not head.split():
            words = []                           # v10: kiritilmagan -> YO'Q
        elif not words:                          # to'liq blacklisted -> voice'dan
            words = sc["voice"].split()[:2]
        if len(words) > 5:                       # eng muhim so'zlar qoladi
            words = words[-4:]
        sc["on_screen"] = " ".join(words)[:40].upper()
        mw = [w for w in sc["mid_text"].split()
              if w.strip(".,!?-_").upper() not in _BAN]
        sc["mid_text"] = " ".join(mw)[:24].upper()

    # v10 map-explainer: xarita ASOSIY, 1-3 ta qisqa stock insert
    n = len(segs)
    n_stock = sum(1 for s in segs if s["mode"] == "stock")
    if not (1 <= n_stock <= 3):
        raise ValueError(f"stock insert 1-3 ta bo'lishi kerak: {n_stock}/{n}")
    # v10: hook SAVOL, yakuniy gap CTA savol bilan tugashi shart
    if "?" not in segs[0]["voice"]:
        raise ValueError("1-sahna (hook) savol bo'lishi kerak ('?')")
    if "?" not in segs[-1]["voice"]:
        raise ValueError("oxirgi gap CTA savol bilan tugasin ('?')")

    place = str(data.get("place") or "").strip()
    country = str(data.get("country") or "").strip()
    data["question"] = str(data.get("question")
                           or data.get("title") or "").strip()[:150]
    data["title"] = str(data.get("title", "A strange place"))[:100]
    if place and place.lower() not in data["title"].lower() \
            and len(data["title"]) < 58:
        data["title"] = f"{data['title']} ({place})"[:100]
    data["hook"] = str(data.get("hook", segs[0]["voice"]))[:200]
    data["script"] = str(data.get("script",
                                  " ".join(s["voice"] for s in segs)))[:2000]
    kws = [str(k) for k in data.get("keywords", [])][:8]
    for tag in (place, country):
        if tag and tag.lower() not in [k.lower() for k in kws]:
            kws = [tag] + kws
    data["keywords"] = kws[:8]
    data["place"] = place
    data["country"] = country
    data["description"] = str(data.get("description", "")).strip()[:4500]
    data["tags"] = [str(t).strip().lower() for t in data.get("tags", [])
                    if str(t).strip()][:20]
    # v9: hashtag ichida probel ASLO qolmasin ("#strange borders" -> "#strangeborders")
    data["hashtags"] = [re.sub(r"[^A-Za-z0-9_]", "", str(h)).lower()
                        for h in _as_list(data.get("hashtags"))
                        if re.sub(r"[^A-Za-z0-9_]", "", str(h))][:4]
    data["pinned_comment"] = str(data.get("pinned_comment", "")).strip()[:200]
    # v9: oxirgi (LOOP) gap hook'ni so'zma-so'z takrorlamasin
    def _norm(t):
        return re.sub(r"[^a-z0-9 ]", "", str(t).lower()).strip()
    hv, lv = _norm(segs[0]["voice"]), _norm(segs[-1]["voice"])
    if hv and lv and (hv == lv or hv in lv or lv in hv
                      or difflib.SequenceMatcher(None, hv, lv).ratio() > 0.70):
        raise ValueError("loop gap hook bilan deyarli bir xil — qayta yoz")

    words = len(data["script"].split())
    lo, hi = globals().get("_WORD_LO", 158), globals().get("_WORD_HI", 182)
    if not (lo <= words <= hi):
        raise ValueError(f"script {words} so'z — {lo}-{hi} oralig'ida bo'lishi kerak")
    return data


def _parse_relaxed(raw):
    """Oxirgi zaxira: so'z oynasi 40-78 (qisqa video uchun)."""
    global _WORD_LO, _WORD_HI
    _WORD_LO, _WORD_HI = 40, 78
    try:
        return _parse(raw)
    finally:
        _WORD_LO, _WORD_HI = 45, 70


def write_script(cfg, trends, history_kws, avoid_title=""):
    prompt, cands = _build_prompt(cfg, trends, history_kws, avoid_title)
    print(f"   tema: {cands} [{llm.provider(cfg)}]")
    last_err, last_raw = None, None
    for attempt in range(3):
        try:
            raw = llm.chat(cfg, SYSTEM, prompt, json_mode=True, timeout=150)
        except Exception as e:
            raise RuntimeError(f"Skript yozib bo'lmadi: {e}")
        try:
            data = _parse(raw)
            data["_topic"] = data.get("place") or data.get("country") \
                or cands
            return data
        except Exception as e:
            last_err, last_raw = e, raw
            print(f"[script] urinish {attempt + 1}: {str(e)[:140]}")
    # zaxira: oxirgi javobni yumshoq oynada qabul qilamiz
    if last_raw:
        try:
            data = _parse_relaxed(last_raw)
            data["_topic"] = data.get("place") or data.get("country") \
                or cands
            print("[script] zaxira oyna (150-190 so'z) bilan qabul qilindi")
            return data
        except Exception:
            pass
    raise RuntimeError(f"Skript yozib bo'lmadi: {last_err}")
