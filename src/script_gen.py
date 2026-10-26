"""2-qadam: SKRIPT — SEED BANKASI (v12.1, LLM yo'li butunlay o'chirilgan).

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

_WORD_LO, _WORD_HI = 45, 70


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


def _parse(raw, strict_insert=True, ending="cta"):
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
    # v13.2 (user 3-tuzatish, 2026-10-26): ending endi navbatma-navbat
    # (50/50) keladi — seed IKKALA rejimni qo'llashi shart. loop_line
    # bo'lsa S7 o'sha gapga almashtiriladi ('...And that is why.'
    # ko'prigi bilan hook'ga uzluksiz ulanadi).
    if ending == "loop" and str(data.get("loop_line") or "").strip():
        ll = re.sub(r"\s+", " ", str(data["loop_line"])).strip()
        if not re.search(r"\bwhy\s*[.!]?\s*$", ll.lower()):
            ll = ll.rstrip(" .!?") + ". And that is why."
        segs[-1]["voice"] = ll
        err = _lint_voice(ll, len(segs) - 1)
        if err:
            raise ValueError(err)
        # pin/label so'zi yangi gapda yo'q bo'lsa birinchi so'zga o'tadi
        words_ll = {w.lower().strip(".,!?") for w in ll.split()}
        for e in segs[-1].get("events", []):
            aw = str(e.get("at_word") or "").lower().strip(".,!?")
            if aw and aw not in words_ll:
                e["at_word"] = ll.split()[0].lower().strip(".,!?")
    if ending == "loop":
        last_v = str(segs[-1]["voice"]).strip()
        if "?" in last_v:
            raise ValueError("loop: oxirgi gap savol EMAS — "
                             "'...And that is why.' ko'prigi kerak")
        if not re.search(r"\bwhy\s*[.!]?\s*$", last_v.lower()):
            raise ValueError("loop: oxirgi gap '...and that is why.' bilan "
                             "tugasin — hook'ga uzluksiz ulanadi")
    elif "?" not in segs[-1]["voice"]:
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
    # v11 (V2-1): ZONA A statik sarlavhasi — headline (yoki place)
    hl = str(data.get("headline") or "").strip()
    if not hl:
        hl = place or " ".join(segs[0]["voice"].split()[:4])
    hl = "".join(c for c in unicodedata.normalize("NFKD", hl)
                 if not unicodedata.combining(c))
    hl = re.sub(r"[^A-Za-z0-9 .'\-]", "", hl).strip().upper()[:30]
    data["headline"] = hl
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
        # v13.2 (user 4-tuzatish): render_meta/qc uchun geokod saqlanadi
        data["_geocode"] = [round(plat, 6), round(plon, 6)]
        # v13.2 (user 4-tuzatish): geokod nuqta seed davlatlari
        # poligonida bo'lishi kerak (Hashima->Gifu, Darvaza->UZ,
        # Lalibela->NYC kabi xatolar ushlanadi; orol/okean nuqtalari
        # poligon yetmasligi sababli o'tkazib yuboriladi)
        try:
            from . import geo as _geo
            _isos = set()
            if str(data.get("country") or "").strip():
                _isos.add(str(data["country"]).upper()[:2])
            for sc in data.get("scenes", []):
                for c in (sc.get("country_iso_codes") or []):
                    _isos.add(str(c).upper()[:2])
            _res = [_geo.point_in_country(c, plon, plat)
                    for c in sorted(_isos)]
            if _isos and not any(r is True for r in _res):
                if _geo.point_on_land(plon, plat):
                    errs.append(
                        f"geokod nuqta ({plat:.3f}, {plon:.3f}) seed "
                        f"davlatlari {sorted(_isos)} poligonida emas — "
                        "noto'g'ri geokod bo'lishi mumkin")
        except Exception as _e:
            print(f"[geo] poligon tekshiruvi o'tkazildi: {_e}")
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


# v13 (user 3-B, 2026-10-26): HOOK KUCHI — taajjub/paradoks/taqiq/raqam.
# Kuchsiz shakl ("Why did they build X?") rad etiladi.
_HOOK_PATTERNS = [
    ("taqiq/inkor", r"\b(can'?t|cannot|nobody|no one|never|illegal|banned|"
     r"forbidden|stopped|vanish(es|ed|ing)?|disappear(s|ed|ing)?|nowhere)\b"),
    ("'yoq' paradoksi", r"\b(no|zero|without)\s+[a-z]+\b"),
    ("qiyosiy/superlativ", r"\b(taller|shorter|bigger|smaller|faster|slower|"
     r"older|newer|lower|higher|deeper|longer|stronger)\s+than\b|"
     r"\b(oldest|newest|biggest|smallest|tallest|lowest|highest|deepest|"
     r"longest|fastest)\b"),
    ("hayratlanarli raqam", r"\b(two|three|four|five|six|seven|eight|nine|"
     r"ten|twenty|fifty|hundred|thousand|\d[\d,]*)\s+(billion\s+|million\s+)?"
     r"(years?|feet|ft|miles?|km|kilometers?|meters?|metres?|seconds?|minutes?|hours?|"
     r"days?|weeks?|months?|cents?|acres?|times|dollars?)\b"),
    ("this+paradoks-fe'l", r"\bthis\b[^?]*\b(boil|burn|move|sink|float|"
     r"freeze|grow|shrink|cross|fall|vanish|disappear|die|switch|change|"
     r"flip|trapped|locked|surrounded)\w*\b"
     r"|\b(boil|burn|move|sink|float|"
     r"freeze|grow|shrink|cross|fall|vanish|disappear|die|switch|change|"
     r"flip|trapped|locked|surrounded)\w*\b[^?]*\bthis\b"),
    ("faqat/yagona", r"\bonly\b"),
    ("qit'a-g'alatiligi", r"\b(fall|falls|falling|lands?|travels?|"
     r"reaches?|blows?)\s+(on|over|in|across)\s+(europe|america|asia|"
     r"africa|australia|another)\b"),
    ("joy-paradoksi", r"\b(upside.?down|backwards?|inside.?out|"
     r"underground|underwater|below sea level|beneath)\b"),
]


def _hook_check(data):
    """v13: hook kamida bitta KUCHLI shablonga mos bo'lishi kerak."""
    scs = data.get("scenes") or []
    hook = str((scs[0].get("voice") if scs else "") or "").lower()
    for name, pat in _HOOK_PATTERNS:
        if re.search(pat, hook):
            return None
    return ("hook kuchsiz — taajjub yo'q (paradoks/taqiq/raqam/qiyos "
            "kerak). Kuchli namunalar: 'Why can\'t anyone visit...?', "
            "'Why is this mountain taller than Everest?', 'Why has this "
            "fire burned for 50 years?', 'Why is it illegal to die "
            "here?', 'Why does African sand fall on Europe?'")


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
    herr = _hook_check(data)
    if herr:
        errs.append(herr)
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
        # Kuchli model koordinatasi geocode nuqtasiga yaqin (<3km) bo'lsa
        # uni ishonamiz (markaz nuqta aniqroq bo'lishi mumkin); uzoq
        # bo'lsa (xato koordinata) geocode qiymati bosib yoziladi.
        import math
        try:
            p0 = (float(pins[0].get("lat")), float(pins[0].get("lon")))
            d = (2 * 6371.0 * math.asin(math.sqrt(
                math.sin(math.radians(pg["lat"] - p0[0]) / 2) ** 2
                + math.cos(math.radians(p0[0]))
                * math.cos(math.radians(pg["lat"]))
                * math.sin(math.radians(pg["lon"] - p0[1]) / 2) ** 2)))
        except Exception:
            d = 1e9
        if d > 3.0:
            pins[0]["lat"] = pg["lat"]
            pins[0]["lon"] = pg["lon"]
        else:
            print(f"[script] pin seed koordinatasi saqlandi "
                  f"(geocode'dan {d:.2f}km)")
        pins[0]["target"] = pins[0].get("target") or place
    else:
        words = str(best.get("voice") or "").split()
        at = words[0].lower().strip(".,!?") if words else ""
        evs.append({"type": "pin", "target": place,
                    "lat": pg["lat"], "lon": pg["lon"], "at_word": at})


def _next_ending(hist):
    """v13.2 (user 3-tuzatish): loop/cta navbatma-navbat (50/50 A/B).

    history'dagi OXIRGI ending'ga qarab teskarisini qaytaradi;
    yozuv yo'q bo'lsa "loop" (A/B boshlanishi). Xato bo'sa None."""
    try:
        for e in reversed(hist or []):
            if e.get("ending_mode"):
                return ("cta" if str(e["ending_mode"]) == "loop"
                        else "loop")
        return "loop"
    except Exception:
        return None


def _use_pending_script(cfg):
    """v10.2: script_pending.json — kuchli model (Arena agent) SEED'i.
    v12 (user 2026-10-26: 'doimiy ishlaydigan qil'): SEED BANKASI —
    script_bank/ papkasidagi seedlar (alfabit tartibida) birma-bir
    iste'mol qilinadi; script_pending.json USTUVOR.

    Har bir nomzod xuddi oddiy yo'l kabi qat'iy tekshiriladi:
    _parse + _geo_check + _simple_check + too_similar (tarix bilan).
    Rad etilgan nomzod script_used/ ga (rad_ prefiksi bilan) ko'chadi
    va KEYINGI seed siniladi — bitta yomon seed butun runni o'ldirmaydi.

    Hamma narsa tugasa: run JIMGINA to'xtaydi (exit 0) — TG xato
    spami yo'q. LLM yo'li BUTUNLAY O'CHIRILGAN (user 2026-10-26): eng
    kuchli model = Arena agent, skriptlarni shu mexanizm orqali o'zi
    yozadi."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    used_dir = os.path.join(root, "script_used")
    os.makedirs(used_dir, exist_ok=True)
    bank_dir = os.path.join(root, "script_bank")
    bank = sorted(f for f in os.listdir(bank_dir)
                  if f.endswith(".json")) if os.path.isdir(bank_dir) else []
    cands = []
    if os.path.isfile(os.path.join(root, "script_pending.json")):
        cands.append(os.path.join(root, "script_pending.json"))
    cands += [os.path.join(bank_dir, f) for f in bank]
    if not cands:
        print("== 2/7: SEED YO'Q (script_pending.json ham, script_bank/ ham "
              "bo'sh) ==")
        print("[seed] Arena agent keyingi seedlarni yozguncha kutish — "
              "bu XATO emas (TG xatosiz, exit 0). Eng kuchli model = "
              "Arena agent (user qoidasi 2026-10-25).")
        import sys
        sys.exit(0)
    from . import history as _hist
    hist = None
    try:
        hist = _hist.load()
    except Exception:
        hist = []
    for src in cands:
        name = os.path.basename(src)
        print(f"== 2/7: SKRIPT SEED ({name} — kuchli model) ==")
        data = None
        try:
            with open(src, encoding="utf-8") as f:
                raw = f.read()
            # v13.2 (user 3-tuzatish, 2026-10-26): loop/cta NAVBATMA-NAVBAT
            # (50/50 A/B) — history'dagi oxirgi ending'ga qaraganda;
            # seed'dagi ending_mode endi HISOBGA OLINMAYDI.
            ending = _next_ending(hist)
            if ending not in ("cta", "loop"):
                ending = str((cfg.get("behavior") or {})
                             .get("ending_mode") or "cta").strip()
            data = _parse(raw, ending=ending)
            gerrs = _geo_check(data, cfg)
            serrs = _simple_check(data)
            sim = (_hist.too_similar(data["title"], data["keywords"], hist)
                   if hist else False)
            if gerrs or serrs:
                print(f"[script] SEED RAD ETILDI (lint): "
                      f"{'; '.join((gerrs + serrs)[:3])}")
                data = None
            elif sim:
                print(f"[script] SEED RAD ETILDI (tarix bilan o'xshash): "
                      f"{data['title'][:60]}")
                data = None
        except Exception as e:
            print(f"[script] SEED RAD ETILDI (parse): {str(e)[:160]}")
            data = None
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if data is None:
            try:
                os.replace(src, os.path.join(
                    used_dir, f"rad_{ts}_{name}"))
            except Exception:
                pass
            continue
        _auto_pin(data, cfg)
        data["_ending"] = ending
        data["_topic"] = data.get("place") or data.get("country") or "seed"
        data["_seed"] = True
        try:
            os.replace(src, os.path.join(used_dir, f"script_{ts}.json"))
        except Exception as e:
            print(f"[script] seed consume xatosi: {e}")
        left = sum(1 for c in cands if os.path.exists(c)) - 1
        print(f"[script] SEED qabul qilindi: {data['title'][:60]} "
              f"({len(data['scenes'])} sahna) — barcha lintlar PASS "
              f"(navbatda yana {max(0, left)} ta seed)")
        return data
    # hamma nomzod rad etildi — jimgina to'xtash (xato spami yo'q)
    print("[seed] bankadagi hamma seed rad etildi — Arena agent yangi "
          "seedlarni yozguncha kutish (exit 0).")
    import sys
    sys.exit(0)


def write_script(cfg, trends, history_kws, avoid_title=""):
    seed = _use_pending_script(cfg)
    if seed is not None:
        return seed
    # v12.1 (user 2026-10-26): LLM yo'li BUTUNLAY O'CHIRILGAN.
    # Skript faqat seed bankadan. _use_pending_script banka bo'sh
    # bo'lganda exit(0) qiladi, shuning uchun bu joy amalda
    # erishilmaydi — himoya sifatida qoldirildi.
    raise RuntimeError(
        "Skript topilmadi: script_bank/ bo'sh (Arena agent seed "
        "yozmagan). Bu holatda run allaqachon exit(0) bilan "
        "jimgina tugagan bo'lishi kerak — LLM yo'li mavjud emas.")
