"""2-qadam: MASTER LLM — "5 FACTS ABOUT {country}" listicle (v6).

Format: hook + FACT 5..1 (countdown, eng hayratlanarlisi oxirida) +
loop = 7 sahna, 158-182 so'z (~45-55s @ +15% rate). HAMMA sahna
real footage (stock) rejimida, xarita ma'lumoti zaxira sifatida.

LLM: Claude Opus 5.5 (ANTHROPIC_API_KEY borida) -> Gemini zanjiri
(src/llm.py). Mavzu: kun bo'yicha 3 ta yangi davlat nomzodi
tarixdan (history) farq qiladigan qilib tanlanadi, LLM eng
qiziqrog'ini tanlaydi.
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
    "a building that sits on an international border",
    "a town split between two countries",
    "an island shared by two (or more) countries",
    "a road, bridge or tunnel that changes country midway",
    "an enclave completely inside another country",
    "a place where you can stand in two countries at once",
    "a border that runs through a house or a hotel",
    "a place where the timezone or calendar changes as you walk",
    "the world's strangest border crossing",
    "a border drawn by a river, lake or sea that moved",
    "a place that two countries both claim",
    "a border town with two of everything (mayor, clock, police)",
    "a place only reachable through another country",
    "a border that runs through a sports field or a restaurant",
]

# ================= MASTER SYSTEM PROMPT =================
SYSTEM = """You are the writer-director of a viral immersive geography
YouTube Shorts channel. Every short is ONE TRUE STORY about ONE real
place — "The bar where you sit in two countries", "The library with a
border through it". Style: slow, cinematic, SECOND-PERSON storytelling
that puts the viewer inside the place: "Step inside this small tavern
and sit down in two countries." Short calm lines, physical details,
no hype. End on a playful loop line. Facts are real and verifiable.
Perfect American English — zero typos, zero filler."""



# ================= MASTER USER PROMPT =================
PROMPT_TMPL = """Pick ONE specific real place that fits this theme: {theme}.
It must be a real, verifiable place with a surprising story (border
oddity, split town, enclave, two-countries-at-once spot).
Niche: {niche}. Audience: USA, English, ages 13-40.
Platform: YouTube Shorts (vertical 1080x1920).

{trend_block}
Recently covered places/topics (STRICTLY avoid anything similar): {hist}
{avoid}
Write a 35-40 SECOND immersive short about that ONE place.

NARRATION — IMMERSIVE STORYTELLING (the benchmark style):
"Step inside this small tavern and sit down in two countries."
"Order a drink on the left side and you are in Spain."
Rules derived from that style:
- Second person, present tense, imperative. The viewer is physically
  THERE. Use body actions: step inside, look down, order, walk, cross.
- Concrete physical details over abstractions: "a black line painted
  on the wooden floor", "your jacket on the chair" — never "interesting
  legislation".
- Total 88-102 words across exactly 7 scenes. COUNT every line.
- Scene 1 (HOOK): 11-13 words. Put the viewer inside the place and
  tease its strangest detail.
- Scenes 2-6 (STORY BEATS): 14-16 words each, TWO very short
  sentences. One continuous story that moves the viewer physically
  through the place, beat by beat, escalating — the strangest detail
  LAST (scene 6). Real place names, real numbers.
- Scene 7 (LOOP): 9-12 words. A playful warning or "just don't..."
  line that the HOOK answers on replay. It must be a DIFFERENT sentence
  than the hook — never repeat or lightly rephrase it.
- NEVER say "did you know", any intro, any CTA, no exclamation marks,
  no rhetorical hype. The title pattern: "The X Where You Y".

VISUALS — REAL FOOTAGE for every scene:
- Every scene: "mode": "stock" with visual_query = exactly 3
  hierarchical phrases (specific -> broader -> generic), each 2-3
  English words describing filmable real-world b-roll (e.g.
  ["cozy tavern wooden interior", "bartender pouring beer",
   "european bar counter"]).
- NEVER a lone generic object ("floor", "wall", "land"). NEVER queries
  about text, signs or logos (OCR rejects them).
- The b-roll must match the place TYPE: an inland village story gets
  streets, houses, markets, forests — NEVER open ocean, beaches or a
  spinning globe. NEVER suggest green-screen / chroma-key studio shots.
- "reject": wrong topics these queries could return.
- Every scene ALSO carries map data (focus/lat/lon/zoom) as fallback.
- "on_screen": a 2-4 ALL-CAPS word headline naming the story beat
  (e.g. "TAPE ON THE FLOOR", "STEPS TO FRANCE", "MIND THE LINE").
  NEVER meta/technical words: "LOOP", "INFINITE", "REPLAY", "REWIND",
  "NEXT VIDEO", "SUBSCRIBE" — these are FORBIDDEN on screen.
- "mid_text": give EXACTLY 2-3 scenes a 1-3 word ALL-CAPS reveal word
  that punches mid-screen (e.g. "IN FRANCE", "TWO MAYORS", "STILL
  LEGAL"). Choose the biggest reveal moments, including one in scene 6.

OUTPUT — ONE JSON object, no markdown, no commentary:
{{
  "place": "<the specific place, e.g. Haskell Free Library, Derby Line>",
  "country": "<main country or 'BE-NL' style pair>",
  "title": "<=70 chars, 'The X Where You Y' curiosity gap>",
  "description": "<2-3 sentences>",
  "pinned_comment": "<question that drives comments>",
  "keywords": ["<place>", "<theme keywords>", "..."],
  "hashtags": ["<3-4 tags>"],
  "scenes": [
    {{
      "id": 1,
      "voice": "<hook, 11-13 words — count them>",
      "on_screen": "<2-4 WORD HEADLINE>",
      "mode": "stock",
      "map": {{"focus": "<place>", "lat": <real lat>, "lon": <real lon>,
               "zoom_level": <3=continent .. 12=building>, "motion": "zoom_in"}},
      "country_iso_codes": ["<ISO2>", "<ISO2>"],
      "sfx_trigger": [],
      "fact_source": "<credible source for the beat>",
      "visual_query": ["<3 phrases>"],
      "must_contain": ["<2-5 GENERIC visual words that literally appear in stock clip tags: tavern, library, street, border, aerial — NEVER country names or abstract words (culture, economy, history)>"],
      "reject": ["<wrong topics>"]
    }},
    {{ ... scenes 2-6: story beats, "voice" 14-16 words, 2-3 of them
         with "mid_text": "<REVEAL WORD>" ... }},
    {{ ... scene 7: loop, playful warning ... }}
  ]
}}"""



_WORD_LO, _WORD_HI = 88, 102


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


_EV_TYPES = ("pin", "line", "arrow", "highlight", "flag_fill", "zoom", "icon")

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
    if not (6 <= len(segs) <= 8):
        raise ValueError(f"6-8 sahna kerak, {len(segs)} ta keldi")
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
        if not words:                            # to'liq blacklisted -> voice'dan
            words = sc["voice"].split()[:2]
        if len(words) > 5:                       # eng muhim so'zlar qoladi
            words = words[-4:]
        sc["on_screen"] = " ".join(words)[:40].upper()
        mw = [w for w in sc["mid_text"].split()
              if w.strip(".,!?-_").upper() not in _BAN]
        sc["mid_text"] = " ".join(mw)[:24].upper()

    # kamida 4 sahna real footage rejimida bo'lishi kerak
    n = len(segs)
    n_stock = sum(1 for s in segs if s["mode"] == "stock")
    if n_stock < min(4, n - 1):
        raise ValueError(f"stock sahna kam: {n_stock}/{n}")

    place = str(data.get("place") or "").strip()
    country = str(data.get("country") or "").strip()
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
    """Oxirgi zaxira: so'z oynasi 84-106 (tempo 35-40s ga siqadi)."""
    global _WORD_LO, _WORD_HI
    _WORD_LO, _WORD_HI = 84, 106
    try:
        return _parse(raw)
    finally:
        _WORD_LO, _WORD_HI = 88, 102


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
