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
import json
import random
import re

from src import llm

# Footage topiladigan, tomoshabinga tanish davlatlar (~170)
COUNTRIES = [
    "Japan", "Iceland", "Australia", "Canada", "Brazil", "Egypt",
    "France", "Italy", "Spain", "Germany", "Norway", "Sweden",
    "Finland", "Denmark", "Netherlands", "Belgium", "Switzerland",
    "Austria", "Portugal", "Greece", "Turkey", "Russia", "China",
    "India", "South Korea", "Thailand", "Vietnam", "Indonesia",
    "Malaysia", "Singapore", "Philippines", "New Zealand", "Mexico",
    "Argentina", "Chile", "Peru", "Colombia", "Bolivia", "Ecuador",
    "Uruguay", "Paraguay", "Venezuela", "Panama", "Costa Rica",
    "Cuba", "Jamaica", "Morocco", "Tunisia", "Algeria", "Libya",
    "Ethiopia", "Kenya", "Tanzania", "Uganda", "Rwanda", "Nigeria",
    "Ghana", "Senegal", "Mali", "Niger", "Chad", "Sudan", "Somalia",
    "South Africa", "Namibia", "Botswana", "Zimbabwe", "Zambia",
    "Madagascar", "Mozambique", "Angola", "Congo", "Cameroon",
    "Saudi Arabia", "United Arab Emirates", "Qatar", "Israel",
    "Jordan", "Lebanon", "Iraq", "Iran", "Afghanistan", "Pakistan",
    "Bangladesh", "Sri Lanka", "Nepal", "Bhutan", "Myanmar",
    "Cambodia", "Laos", "Mongolia", "Kazakhstan", "Uzbekistan",
    "Kyrgyzstan", "Tajikistan", "Turkmenistan", "Azerbaijan",
    "Georgia", "Armenia", "Ukraine", "Poland", "Czech Republic",
    "Slovakia", "Hungary", "Romania", "Bulgaria", "Serbia", "Croatia",
    "Slovenia", "Bosnia and Herzegovina", "Albania", "North Macedonia",
    "Montenegro", "Estonia", "Latvia", "Lithuania", "Belarus",
    "Moldova", "Ireland", "United Kingdom", "Scotland", "Malta",
    "Cyprus", "Luxembourg", "Monaco", "Andorra", "San Marino",
    "Liechtenstein", "Greenland", "Fiji", "Papua New Guinea",
    "Samoa", "Tonga", "Vanuatu", "Solomon Islands", "Maldives",
    "Bhutan", "Taiwan", "Hong Kong", "Oman", "Yemen", "Kuwait",
    "Bahrain", "Syria", "Eswatini", "Lesotho", "Malawi", "Burundi",
    "Gabon", "Benin", "Togo", "Burkina Faso", "Guinea", "Liberia",
    "Sierra Leone", "Mauritania", "Botswana", "Timor-Leste", "Brunei",
    "Suriname", "Guyana", "Belize", "Guatemala", "Honduras",
    "Nicaragua", "El Salvador", "Haiti", "Dominican Republic",
    "Bahamas", "Trinidad and Tobago", "Barbados", "Puerto Rico",
]
COUNTRIES = list(dict.fromkeys(COUNTRIES))          # dublikatlarsiz

# ================= MASTER SYSTEM PROMPT =================
SYSTEM = """You are the head writer of a viral "Top 5 facts" YouTube
Shorts channel about countries. Format: fast countdown listicle —
hook, five numbered facts counting down from 5 to 1 (the most
shocking fact LAST), then a seamless loop question. Every fact is
real, verifiable and genuinely surprising. You write clean, punchy,
grammatically perfect American English — zero typos, zero filler,
zero cliches."""

# ================= MASTER USER PROMPT =================
PROMPT_TMPL = """Pick ONE country from these three candidates: {candidates}.
Niche: {niche}. Audience: USA, English, ages 13-40.
Platform: YouTube Shorts (vertical 1080x1920).

{trend_block}
Recently covered countries (STRICTLY DO NOT pick any of these): {hist}
{avoid}
Write a 45-55 SECOND SHORT: "5 facts about <your country>" countdown.

VOICEOVER (hard limits — COUNT the words in every line before answering):
- Total 158-182 words across exactly 7 scenes.
- Scene 1 (HOOK): 18-24 words. First sentence is a provocative question
  (~10 words) that teases the #1 fact. Something must move on screen
  within 0.5s of the start.
- Scenes 2-6 (FACT 5 -> FACT 1 countdown, most shocking fact LAST):
  each 25-31 words, exactly TWO sentences — the fact, then a short
  punch line that lands it.
- Scene 7 (LOOP): 14-18 words, ends in a question the HOOK answers
  (seamless infinite loop on replay). Never end mid-sentence.
- FORBIDDEN: "Did you know", "Welcome", saying "number five" or
  "Top 5" out loud, any intro, "like and subscribe", any outro/CTA.
- Present tense, active voice, specific place names, real numbers.
- Facts must be real and verifiable (geography, records, laws, history).
  If you cannot name a credible source, REPLACE the fact.

VISUALS — REAL FOOTAGE for every scene:
- Every scene: "mode": "stock" with visual_query = exactly 3
  hierarchical phrases (specific -> broader -> generic), each 2-3
  English words describing filmable real-world b-roll.
  Example: ["shinkansen bullet train passing", "japanese train station",
            "modern train aerial"].
- NEVER a lone generic object ("floor", "wall", "land", "water") —
  those queries return wrong footage. NEVER build queries from filler
  words. NEVER queries about text, signs or logos (OCR rejects them).
- "reject": wrong topics these queries could return.
- Every scene ALSO carries map data (focus/lat/lon/zoom) as a fallback
  if footage fails validation — use the exact place the fact is about.
- "on_screen": fact scenes use "FACT 5 - HEADLINE" format (2-4 ALL-CAPS
  words after the dash, the fact's core). Hook: a 2-4 word tease.
  Loop: a 2-4 word question.
- sfx_trigger: fact scenes get "ding"; hook gets "riser"; scene 6
  (FACT 1) may add "boom".
- highlights: 1-3 per scene, color from the palette
  (cyan #00E5FF, red #FF2D2D, yellow #FFD400).

OUTPUT — ONE JSON object, no markdown, no commentary:
{{
  "country": "<the country you picked>",
  "title": "<=70 chars, curiosity gap, mentions the country>",
  "description": "<2-3 sentences>",
  "pinned_comment": "<question that drives comments>",
  "keywords": ["<country>", "facts", "..."],
  "hashtags": ["<3-4 tags>"],
  "scenes": [
    {{
      "id": 1,
      "voice": "<hook, 18-24 words — count them>",
      "on_screen": "<2-4 WORD TEASE>",
      "mode": "stock",
      "map": {{"focus": "<place>", "lat": <real lat>, "lon": <real lon>,
               "zoom_level": <3=continent .. 12=city>, "motion": "zoom_in"}},
      "country_iso_codes": ["<ISO2>"],
      "highlights": [{{"word": "<exact word from voice>",
                        "color": "#FFD400"}}],
      "sfx_trigger": ["riser"],
      "fact_source": "<credible source for the tease>",
      "visual_query": ["<3 phrases>"],
      "must_contain": ["<2-5 GENERIC visual words that literally appear in stock clip tags: mountain, snow, deer, street, train, aerial — NEVER country names or abstract words (culture, economy, history)>"],
      "reject": ["<wrong topics>"]
    }},
    {{ ... scenes 2-6: FACT 5 down to FACT 1, "voice" 25-31 words,
         "on_screen": "FACT N - HEADLINE", "sfx_trigger": ["ding"] ... }},
    {{ ... scene 7: loop, ends in a question ... }}
  ]
}}"""

_WORD_LO, _WORD_HI = 152, 184


def _pick_candidates(history_kws, k=3):
    """Tarixda yopilmagan davlatlardan 3 ta (kun+slot bo'yicha determin)."""
    used = {str(w).strip().lower() for w in (history_kws or []) if w}
    avail = [c for c in COUNTRIES if c.lower() not in used]
    if len(avail) < k:
        avail = COUNTRIES[:]
    now = datetime.datetime.now(datetime.UTC)
    slot = (now.hour + 1) // 8                 # 3 run/kun: 0/1/2
    rnd = random.Random(now.timetuple().tm_yday * 8 + slot)
    return rnd.sample(avail, k)


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
    cands = _pick_candidates(history_kws)
    hist = ", ".join(history_kws[-20:]) if history_kws else "(none yet)"
    avoid = (f"DO NOT pick the country from this already-generated title "
             f"today: {avoid_title}\n" if avoid_title else "")
    prompt = PROMPT_TMPL.format(
        candidates=", ".join(cands), niche=ch["niche"],
        trend_block=trend_block, hist=hist, avoid=avoid)
    return prompt, " / ".join(cands)


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
        sc.setdefault("id", i + 1)

    # FACT N prefiksi: sahna 2..(n-1) => FACT (n-1-i); yo'q bo'lsa qo'sh
    n = len(segs)
    for i in range(1, max(1, n - 1)):
        num = n - 1 - i                          # 7 sahna: 5,4,3,2,1
        sc = segs[i]
        head = sc["on_screen"]
        if not re.match(rf"^FACT\s*{num}\b", head, re.I):
            head = re.sub(r"^FACT\s*\d+\s*[-–—:]?\s*", "", head, flags=re.I)
            head = f"FACT {num} \u2014 {head}".strip(" -\u2014")
        sc["on_screen"] = head[:40].upper()
    segs[0]["on_screen"] = segs[0]["on_screen"][:40].upper()
    segs[-1]["on_screen"] = segs[-1]["on_screen"][:40].upper()

    # kamida 4 sahna real footage rejimida bo'lishi kerak (v6 formati)
    n_stock = sum(1 for s in segs if s["mode"] == "stock")
    if n_stock < min(4, n - 1):
        raise ValueError(f"stock sahna kam: {n_stock}/{n}")

    country = str(data.get("country") or "").strip()
    data["title"] = str(data.get("title", "Country facts"))[:100]
    if country and country.lower() not in data["title"].lower():
        data["title"] = f"{data['title'][:60]} ({country})".strip()
    data["hook"] = str(data.get("hook", segs[0]["voice"]))[:200]
    data["script"] = str(data.get("script",
                                  " ".join(s["voice"] for s in segs)))[:2000]
    kws = [str(k) for k in data.get("keywords", [])][:8]
    if country and country.lower() not in [k.lower() for k in kws]:
        kws = [country] + kws
    data["keywords"] = kws
    data["country"] = country
    data["description"] = str(data.get("description", "")).strip()[:4500]
    data["tags"] = [str(t).strip().lower() for t in data.get("tags", [])
                    if str(t).strip()][:20]
    data["hashtags"] = [re.sub(r"^#", "", str(h).strip()).lower()
                        for h in _as_list(data.get("hashtags"))
                        if str(h).strip()][:4]
    data["pinned_comment"] = str(data.get("pinned_comment", "")).strip()[:200]
    words = len(data["script"].split())
    lo, hi = globals().get("_WORD_LO", 158), globals().get("_WORD_HI", 182)
    if not (lo <= words <= hi):
        raise ValueError(f"script {words} so'z — {lo}-{hi} oralig'ida bo'lishi kerak")
    return data


def _parse_relaxed(raw):
    """Oxirgi zaxira: so'z oynasi 146-198 (tempo <=1.10x 45-55s ga siqadi)."""
    global _WORD_LO, _WORD_HI
    _WORD_LO, _WORD_HI = 146, 198
    try:
        return _parse(raw)
    finally:
        _WORD_LO, _WORD_HI = 152, 184


def write_script(cfg, trends, history_kws, avoid_title=""):
    prompt, cands = _build_prompt(cfg, trends, history_kws, avoid_title)
    print(f"   nomzod davlatlar: {cands} [{llm.provider(cfg)}]")
    last_err, last_raw = None, None
    for attempt in range(3):
        try:
            raw = llm.chat(cfg, SYSTEM, prompt, json_mode=True, timeout=150)
        except Exception as e:
            raise RuntimeError(f"Skript yozib bo'lmadi: {e}")
        try:
            data = _parse(raw)
            data["_topic"] = data.get("country") or cands.split(" / ")[0]
            return data
        except Exception as e:
            last_err, last_raw = e, raw
            print(f"[script] urinish {attempt + 1}: {str(e)[:140]}")
    # zaxira: oxirgi javobni yumshoq oynada qabul qilamiz
    if last_raw:
        try:
            data = _parse_relaxed(last_raw)
            data["_topic"] = data.get("country") or cands.split(" / ")[0]
            print("[script] zaxira oyna (150-190 so'z) bilan qabul qilindi")
            return data
        except Exception:
            pass
    raise RuntimeError(f"Skript yozib bo'lmadi: {last_err}")
