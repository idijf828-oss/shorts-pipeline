"""2-qadam: MASTER LLM — MAP EXPLAINER (v10, qo'llanma: map-explainer-video).

Format: bitta savol ("Why isn't the US annexing Canada?") + 2-3 sabab +
CTA savol. 45-70 so'z, 15-35s. Vizuallar: satellite xarita asosiy
(bayroq-poligon, strelka, sticker, davlat nomi yorlig'i), 2 ta qisqa
stock insert. So'zma-so'z markaz subtitr, kalit so'z cyan.
"""
import datetime
import difflib
import json
import os
import random
import re
import unicodedata

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
- EVERY line MAX 10 words. Short, punchy, everyday American English
  that a 7-8 year old fully understands — no legal, academic or
  technical terms, no jargon. Explain like a friendly teacher.
  BANNED words (never use, never even imply): jurisdiction, contiguous,
  exclave, enclave, feudal, sovereignty, sovereign, demarcation,
  cession, irredentist, condominium, estoppel, pursuant, whereas.
  Use plain equivalents: "control", "next to", "land inside another
  country", "who rules it", "border line", "gave/sold land".
- Scene 1 (HOOK, 6-9 words): a complete, natural, grammatical question
  that names the place — starting with Why/How/What/Where/Who.
  Examples: "Why isn't the US simply annexing Canada?"
            "Why does this town sit in two countries?"
- Scenes 2-6 (REASONS, 7-10 words each): one reason per beat. Concrete
  facts, real numbers, real names. Natural flow or "First / Second".
  The strongest reason LAST. Everyday facts a kid knows.
- Final scene (CLOSE + CTA, 6-10 words): one-line answer summary, then
  a short question that invites the next video, ending with "?".
- Active voice. Every line adds NEW information. NEVER "did you know",
  intros, thank-yous, or hype. No exclamation marks.
- Neutral, factual tone on political topics — explain, never take sides.

VISUALS — SATELLITE MAP is the star (guide style):
- Most scenes are map scenes: "mode": "map" with focus/lat/lon and
  zoom_level (3=continent, 5=whole country, 7=region, 9=city).
  CAMERA STORY (required): every next map scene zooms CLOSER —
  zoom_level increases scene by scene (3 or 4 first — continent wide;
  middle scenes 5-7; last map scene 9-11 right on the exact place).
  The final map scene must sit on the exact place with REAL city-level
  lat/lon and carry a "pin" event pointing at it.
  Use AT LEAST 3 DIFFERENT map views across the video (different
  places, countries or zoom levels — never the same view twice in a
  row). Vary "motion": "zoom_in", "zoom_out", "pan_left", "pan_right".
  The camera moves slowly the whole time; topic change = hard cut.
- Scenes with "flag_fill" use zoom_level 4-7 so the country polygon
  stays inside the frame (max ~40% of screen).
- Give each map scene 1-3 "events" from:
  "flag_fill" target ISO2 — fills the country with its flag texture
  (use for the 1-2 main countries);
  "highlight" target ISO2 — cyan ally/ bloc fill;
  "arrow" dir up/down/left/right — big yellow arrow (pressure, movement);
  "icon" emoji — one sticker per event: handshake, siren, money bag, rocket, warning sign, checkered flag (use the actual emoji characters);
  "label" target — a small black name tag on the country (country name);
  "pin" target <place> lat/lon — red map pin + place name tag at the
  EXACT point (final reveal scene; use the real coordinates).
- EXACTLY 1-2 scenes are stock inserts: "mode": "stock" with a SHORT
  punch line of 3-6 words (the insert lasts <= 2 seconds) and
  visual_query = 3 hierarchical phrases (2-3 words each) about filmable
  real-world b-roll (e.g. ["protest crowd street", "angry crowd signs",
  "demonstration city"]). Subtitles continue over inserts.
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

# v10.1e (run 26): LLM ba'zan diakritik qoldiradi (ü, ö, ç, ñ...) — Baarle
# temasi 3 urinishda ham 'ü' da yiqildi. Endi avtomatik transliteratsiya.
_TRANSLIT = {
    "à": "a", "á": "a", "â": "a", "ã": "a", "ä": "a", "å": "a", "ā": "a",
    "ă": "a", "ą": "a",
    "À": "A", "Á": "A", "Â": "A", "Ã": "A", "Ä": "A", "Å": "A", "Ā": "A",
    "Ă": "A", "Ą": "A",
    "è": "e", "é": "e", "ê": "e", "ë": "e", "ē": "e", "ę": "e", "ě": "e",
    "ė": "e",
    "È": "E", "É": "E", "Ê": "E", "Ë": "E", "Ē": "E", "Ę": "E", "Ě": "E",
    "Ė": "E",
    "ì": "i", "í": "i", "î": "i", "ï": "i", "ī": "i", "ı": "i",
    "Ì": "I", "Í": "I", "Î": "I", "Ï": "I", "Ī": "I", "İ": "I",
    "ò": "o", "ó": "o", "ô": "o", "õ": "o", "ö": "o", "ø": "o", "ō": "o",
    "ő": "o",
    "Ò": "O", "Ó": "O", "Ô": "O", "Õ": "O", "Ö": "O", "Ø": "O", "Ō": "O",
    "Ő": "O",
    "ù": "u", "ú": "u", "û": "u", "ü": "u", "ū": "u", "ů": "u", "ű": "u",
    "Ù": "U", "Ú": "U", "Û": "U", "Ü": "U", "Ū": "U", "Ů": "U", "Ű": "U",
    "ý": "y", "ÿ": "y", "Ý": "Y", "Ÿ": "Y",
    "ñ": "n", "ń": "n", "ņ": "n", "ň": "n", "Ñ": "N", "Ń": "N", "Ň": "N",
    "ç": "c", "ć": "c", "č": "c", "Ç": "C", "Ć": "C", "Č": "C",
    "ş": "s", "ś": "s", "š": "s", "ș": "s", "Ş": "S", "Š": "S", "Ș": "S",
    "ğ": "g", "Ğ": "G",
    "ż": "z", "ź": "z", "ž": "z", "Ż": "Z", "Ź": "Z", "Ž": "Z",
    "đ": "d", "ď": "d", "Đ": "D", "Ď": "D",
    "ť": "t", "ț": "t", "Ť": "T", "Ț": "T",
    "ľ": "l", "ł": "l", "Ľ": "L", "Ł": "L",
    "ŕ": "r", "ř": "r", "Ŕ": "R", "Ř": "R",
    "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ß": "ss",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th",
}


def _asciiize(s):
    """Lotin diakritiklarini ASCII'ga almashtiradi.

    Kirill/CJK kabi haqiqiy xorijiy skriptlar o'z holida qoladi —
    ularni _lint_voice ushlaydi (ingliz skripti talabi buzilmaydi).
    """
    out = []
    for ch in s:
        if ord(ch) < 128 or ch in _OK_EXTRA:
            out.append(ch)
            continue
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
            continue
        base = "".join(c for c in unicodedata.normalize("NFKD", ch)
                       if not unicodedata.combining(c))
        out.append(base if base and base.isascii() else ch)
    return "".join(out)


PLACE_KEYS = ("place", "country", "focus", "target")


def _asciiize_tree(o, ctr=None):
    """Recursiv translit — LEKIN joy nomlari (place/country/focus/target)
    saqlanadi: 'Büsingen' label'da Ü bilan chiqadi (fontda bor).
    Voice/mid_text esa baribir OCR uchun ASCII."""
    if isinstance(o, dict):
        r = {}
        for k, v in o.items():
            if str(k) in PLACE_KEYS or any(str(k).endswith("_" + p)
                                           for p in PLACE_KEYS):
                r[_asciiize_tree(k, ctr)] = v
            else:
                r[_asciiize_tree(k, ctr)] = _asciiize_tree(v, ctr)
        return r
    if isinstance(o, list):
        return [_asciiize_tree(v, ctr) for v in o]
    if isinstance(o, str):
        a = _asciiize(o)
        if a != o:
            ctr[0] += 1
        return a
    return o


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


def _parse(raw, strict_insert=True):
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S)
    a, b = txt.find("{"), txt.rfind("}")
    if a != -1 and b > a and (a > 0 or b < len(txt) - 1):
        txt = txt[a:b + 1]
    # LLM'larning eng ko'p xatosi: oxirgi vergul (run 18: "line 27 col 9")
    txt = re.sub(r",\s*([\]}])", r"\1", txt)
    txt = re.sub(r"(?<=\d)\s+(?=\d)", "", txt)   # "5\n  million" emas
    data = json.loads(txt)
    _ctr = [0]
    data = _asciiize_tree(data, _ctr)
    if _ctr[0]:
        print(f"[script] transliteratsiya: {_ctr[0]} maydonda diakritika "
              "ASCII'ga o'tdi (ü->u kabi)")

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

    # v10 map-explainer: xarita ASOSIY, 1-2 ta qisqa stock insert
    n = len(segs)
    # v10.1f (run 27): 1-2 urinishda insert >8 so'z QAT'IY rad etiladi
    # (feedback LLM'ga aniq muammoni tuzatishga imkon beradi); faqat
    # oxirgi urinishda xaritaga degradatsiya — run o'limi yo'q.
    long_ins = [s for s in segs if s["mode"] == "stock"
                and len(s["voice"].split()) > 8]
    if long_ins and strict_insert:
        raise ValueError("insert gapi 3-6 so'z (<=8) bo'lishi kerak")
    for s in long_ins:
        print(f"[script] insert {len(s['voice'].split())} so'z — "
              "xarita rejimiga o'tkazildi")
        s["mode"] = "map"
    n_stock = sum(1 for s in segs if s["mode"] == "stock")
    if n_stock > 2:
        if strict_insert:
            raise ValueError(f"stock insert 1-2 ta bo'lishi kerak: "
                             f"{n_stock}/{n}")
        # v10.1f: oxirgi himoya — ortiqchalar xaritaga, birinchi 2 si qoladi
        for s in [x for x in segs if x["mode"] == "stock"][2:]:
            print("[script] ortiqcha stock insert — xaritaga o'tkazildi")
            s["mode"] = "map"
        n_stock = 2
    if n_stock == 0:
        print("[script] ogohlantirish: yaroqli stock insert yo'q — "
              "to'liq xarita video")
    # v10.1 (user): hook to'liq, grammatik savol bo'lishi shart
    if "?" not in segs[0]["voice"]:
        raise ValueError("1-sahna (hook) savol bo'lishi kerak ('?')")
    if not re.match(r"^(Why|How|What|Where|Who|When|Which|Is|Are|Do|Does|Did"
                    r"|Can|Could|Would|Will)\b", segs[0]["voice"].strip()):
        raise ValueError("hook Why/How/What/... bilan boshlanishi kerak")
    if "?" not in segs[-1]["voice"]:
        raise ValueError("oxirgi gap CTA savol bilan tugasin ('?')")
    # v10.1 (user): kamida 3 XIL xarita ko'rinishi
    views = {(round(s["map"]["lat"], 1), round(s["map"]["lon"], 1),
              s["map"]["zoom_level"])
             for s in segs if s["mode"] == "map"}
    if len(views) < 3:
        raise ValueError(f"kamida 3 xil xarita ko'rinishi kerak: {len(views)}")
    # v10.1: flag_fill sahnada davlat poligoni kadrga sig'sin
    for s in segs:
        if any(e["type"] == "flag_fill" for e in s["events"]):
            s["map"]["zoom_level"] = min(s["map"]["zoom_level"], 7)

    place = str(data.get("place") or "").strip()
    country = str(data.get("country") or "").strip()
    data["question"] = str(data.get("question")
                           or data.get("title") or "").strip()[:150]
    # v10.1e (analitika 2026-10-24): savol-titullarda AVD 21s/26s, oddiy
    # titulda 14s — title doim SAVOL. Mos kelmasa hook'dan yasaladi.
    ttl = str(data.get("title") or "").strip()
    if not (re.match(r"^(Why|How|What|Where|Who|When|Which|Is|Are|Do|Does"
                     r"|Did|Can|Could|Would|Will)\b", ttl) and ttl.endswith("?")):
        new_t = segs[0]["voice"].strip()
        if "?" in new_t:
            new_t = new_t.split("?")[0].strip()[:88] + "?"
        data["title"] = new_t
        print(f"[script] title savolga aylantirildi: {new_t[:70]}")
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
        return _parse(raw, strict_insert=False)
    finally:
        _WORD_LO, _WORD_HI = 45, 70



# --- v10.2 (user #3/#4): haqiqiy zoom + aniq joy + oddiy til ---------------

_GEO_RADIUS = {3: 2600, 4: 1600, 5: 900, 6: 450, 7: 200, 8: 90,
               9: 45, 10: 25, 11: 15, 12: 10}          # km, zoom bo'yicha
_PIN_TYPES = ("city", "town", "village", "hamlet", "suburb", "borough",
              "administrative")
BLACKLIST = ("jurisdiction", "contiguous", "exclave", "enclave",
             "feudal", "sovereignty", "sovereign", "demarcation",
             "cession", "irredentist", "condominium", "estoppel",
             "pursuant", "whereas")


def _geocode(place, cfg):
    """Nominatim geokodlash + disk kechi. -> (lat, lon, type) | None."""
    place = str(place or "").strip()
    if not place:
        return None
    work = (cfg.get("_paths") or {}).get("work") or "."
    cache_p = os.path.join(work, "geocode_cache.json")
    cache = {}
    try:
        with open(cache_p, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        pass
    if place in cache:
        return cache[place]
    import urllib.parse
    import urllib.request
    url = ("https://nominatim.openstreetmap.org/search?q="
           + urllib.parse.quote(place) + "&format=json&limit=1")
    req = urllib.request.Request(
        url, headers={"User-Agent": "shorts-pipeline/1.0 (explainer videos)"})
    res = None
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data:
            d0 = data[0]
            res = (float(d0["lat"]), float(d0["lon"]),
                   str(d0.get("type") or d0.get("class") or ""))
    except Exception as e:
        print(f"[geocode] {place}: {e}")
    cache[place] = res
    try:
        os.makedirs(work, exist_ok=True)
        with open(cache_p, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    return res


def _geo_check(data, cfg):
    """User #3 lint. -> xatolik ro'yxati (bo'sh = OK)."""
    errs = []
    place = str(data.get("place") or "").strip()
    g = _geocode(place, cfg) if place else None
    if g:
        plat, plon, ptype = g
        data["_place_geo"] = {"lat": plat, "lon": plon}
        import math

        def dist_km(la, lo):
            p1, p2 = math.radians(la), math.radians(plat)
            a = (math.sin((p2 - p1) / 2) ** 2
                 + math.cos(p1) * math.cos(p2)
                 * math.sin(math.radians(lo - plon) / 2) ** 2)
            return 2 * 6371.0 * math.asin(math.sqrt(a))

        maps = [sc for sc in data["scenes"] if sc.get("mode") == "map"]
        for j, sc in enumerate(maps):
            m = sc["map"]
            d = dist_km(m["lat"], m["lon"])
            r = _GEO_RADIUS.get(int(m["zoom_level"]), 200)
            if d > r:
                errs.append(
                    f"sahna {j}: kamera {place} dan {d:.0f}km uzoqda "
                    f"(z{m['zoom_level']} uchun <= {r}km kerak)")
        need_z = 9 if ptype in _PIN_TYPES else 6
        if not any(int(sc["map"]["zoom_level"]) >= need_z
                   and dist_km(sc["map"]["lat"], sc["map"]["lon"]) <= 60.0
                   for sc in maps):
            errs.append(
                f"aniq nuqta (reveal) sahna yo'q: {place} z>={need_z} "
                "va joydan <=60km kamera kerak")
    maps = [sc for sc in data["scenes"] if sc.get("mode") == "map"]
    if maps and int(maps[0]["map"]["zoom_level"]) > 5:
        errs.append("birinchi xarita sahna z<=5 kerak (joriy z"
                    + str(maps[0]["map"]["zoom_level"]) + ")")
    zs = [int(sc["map"]["zoom_level"]) for sc in maps]
    dip = [j for j, (a, b) in enumerate(zip(zs, zs[1:])) if b < a]
    if dip:
        errs.append("zoom har sahnada o'sishi kerak (tushish: "
                    + ",".join(str(j) for j in dip) + ")")
    keys = [(round(sc["map"]["lat"], 1), round(sc["map"]["lon"], 1),
             int(sc["map"]["zoom_level"])) for sc in maps]
    for j in range(2, len(keys)):
        if keys[j] == keys[j - 1] == keys[j - 2]:
            errs.append("bir xil kadr 3+ sahnada takrorlanadi")
            break
    return errs


def _simple_check(data):
    """User #4: 7-8 yosh tili — qiyin so'z yo'q, gap <=10 so'z."""
    errs = []
    for j, sc in enumerate(data.get("scenes") or []):
        for fld in ("voice", "mid_text"):
            txt = str(sc.get(fld) or "")
            low = " " + re.sub(r"[^a-z]+", " ", txt.lower()) + " "
            for b in BLACKLIST:
                if f" {b} " in low or f" {b}s " in low:
                    errs.append(f"sahna {j+1} '{fld}': qiyin so'z '{b}'")
            n = len(txt.split())
            if n > 10:
                errs.append(f"sahna {j+1} '{fld}': {n} so'z (>10)")
    t = str(data.get("title") or "").lower()
    for b in BLACKLIST:
        if b in t:
            errs.append(f"title: qiyin so'z '{b}'")
    return errs


def _auto_pin(data, cfg):
    """Aniq nuqta sahnasiga (eng baland zoom) pin: geokodlangan
    koordinata + place label. LLM pin bo'lsa koordinatasi to'g'rilanadi."""
    pg = data.get("_place_geo")
    place = str(data.get("place") or "").strip()
    maps = [sc for sc in data["scenes"] if sc.get("mode") == "map"]
    if not pg or not maps:
        return
    best = max(maps, key=lambda sc: int(sc["map"]["zoom_level"]))
    evs = best.setdefault("events", [])
    pins = [e for e in evs if str(e.get("type")) == "pin"]
    if pins:
        pins[0]["lat"] = pg["lat"]
        pins[0]["lon"] = pg["lon"]
        pins[0]["target"] = pins[0].get("target") or place
    else:
        words = str(best.get("voice") or "").split()
        at = words[0].lower().strip(".,!?") if words else ""
        evs.append({"type": "pin", "target": place,
                    "lat": pg["lat"], "lon": pg["lon"], "at_word": at})


def write_script(cfg, trends, history_kws, avoid_title=""):
    prompt, cands = _build_prompt(cfg, trends, history_kws, avoid_title)
    print(f"   tema: {cands} [{llm.provider(cfg)}]")
    last_err, last_raw = None, None
    p = prompt
    for attempt in range(3):
        try:
            raw = llm.chat(cfg, SYSTEM, p, json_mode=True, timeout=150)
        except Exception as e:
            raise RuntimeError(f"Skript yozib bo'lmadi: {e}")
        try:
            data = _parse(raw, strict_insert=(attempt < 2))
            # v10.2 (user #3/#4): geo va oddiylik lintlari — feedback
            # bilan qayta urinishga tushadi (aks holda run o'limi yo'q).
            gerrs = _geo_check(data, cfg)
            if gerrs:
                raise ValueError("; ".join(gerrs[:2]))
            serrs = _simple_check(data)
            if serrs:
                raise ValueError("; ".join(serrs[:2]))
            data["_topic"] = data.get("place") or data.get("country") \
                or cands
            _auto_pin(data, cfg)
            return data
        except Exception as e:
            last_err, last_raw = e, raw
            print(f"[script] urinish {attempt + 1}: {str(e)[:140]}")
            # v10.1f: keyingi urinishga ANIQ xato feedback (run 26/27:
            # bir xil prompt bilan LLM xatosini tuzatmaydi)
            p = (prompt + "\n\nIMPORTANT: your previous JSON was rejected: "
                 f"{e}. Rewrite the full JSON fixing exactly this issue "
                 "and keep every other requirement above.")
    # zaxira: oxirgi javobni yumshoq oynada qabul qilamiz
    if last_raw:
        try:
            data = _parse_relaxed(last_raw)
            data["_topic"] = data.get("place") or data.get("country") \
                or cands
            gerrs = _geo_check(data, cfg)
            serrs = _simple_check(data)
            if gerrs or serrs:
                print("[script] OGOHLANTIRISH (relaxed): "
                      + "; ".join((gerrs + serrs)[:3]))
            _auto_pin(data, cfg)
            print("[script] zaxira oyna (150-190 so'z) bilan qabul qilindi")
            return data
        except Exception:
            pass
    raise RuntimeError(f"Skript yozib bo'lmadi: {last_err}")
