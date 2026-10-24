"""V4 subtitr — rang = ma'no (doc B4).

- 1-3 so'zlik chunklar, so'zma-so'z, katta qalin Montserrat + qora kontur.
- Ranglar: oddiy so'z OQ; AKTIV so'z sariq (#FFD400) + 115% scale;
  highlight so'z O'Z RANGIDA (mamlakat bayrog'i/aksent rangi),
  aktiv bo'lsa + 115% + 0.1s pop.
- Joyi rejimga qarab: map -> y=950, stock -> y=1150 (config).
- Maks kenglik 860px (x: 110..970 safe zone).
- ASS rangi: #RRGGBB -> &H00BBGGRR&.

words = [(word, start, end), ...]
highlights = {"canada": "#FF2D2D", ...}  (kichik harf, tinish belgisiz)
"""
import os
import re

from . import style
from .style import MID_Y

W, H = 1080, 1920
SAFE_W = style.SAFE_W
MAX_WORDS_LINE = 3
FONT = style.FONT_FAMILY
FONT_SIZE = style.CAPTION_SIZE      # doc P1: 96px doimiy
FIT_MIN = style.CAPTION_FIT_MIN    # 80 (kam holatda)
YELLOW = style.YELLOW

_FONT_FILES = [
    "/usr/share/fonts/truetype/montserrat/Montserrat-ExtraBold.ttf",
    "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font_path():
    for p in _FONT_FILES:
        if os.path.exists(p):
            return p
    return None


def text_width(text, size):
    fp = _font_path()
    if fp:
        try:
            from PIL import ImageFont
            return ImageFont.truetype(fp, size).getlength(text)
        except Exception:
            pass
    return max(len(l) for l in text.split("\n")) * size * 0.62


def _ladder(base):
    """100 -> 88 -> 80 -> ... (QC ro'yxati: {100, 88, 80})."""
    vals, s = [], base
    while s >= FIT_MIN:
        vals.append(s)
        s -= 12 if len(vals) == 1 else 8
    return vals or [FIT_MIN]


def fit_font(text, base=FONT_SIZE, max_w=SAFE_W):
    """Doc P1: katta shrift doimiy; keng bo'lsa narvon bo'yicha kichrayadi."""
    for s in _ladder(base):
        if text_width(text, s) <= max_w:
            return s
    return FIT_MIN


def _split2(ch, size):
    """chunk <=3 so'zni 2 qatorga bo'lish (doc P1: shriftni kichraytirma).
    -> (split_index | None, font_size)"""
    words = [str(x[0]).upper() for x in ch]
    plain = " ".join(words)
    if _line_w(words, size, active=True) <= SAFE_W:
        return None, size
    if len(ch) < 2:
        return None, fit_font(plain, size)
    best_k, bw = None, None
    for k in range(1, len(ch)):
        w = max(_line_w(words[:k], size, active=True),
                _line_w(words[k:], size))
        if bw is None or w < bw:
            best_k, bw = k, w
    if bw is not None and bw <= SAFE_W:
        return best_k, size
    if best_k is not None:
        # v10: bir qator sig'madi -> 2 qator + narvon shrifti MAJBUR
        # (aks holda "UNDEFENDED BORDER." 80px bir qator deb toshib ketardi)
        for s2 in _ladder(size):
            if max(_line_w(words[:best_k], s2, active=True),
                   _line_w(words[best_k:], s2)) <= SAFE_W:
                return best_k, s2
        return best_k, FIT_MIN
    return None, fit_font(plain, size)


def _t(s):
    h, m = int(s // 3600), int(s % 3600 // 60)
    return f"{h}:{m:02d}:{s % 60:05.2f}"


def _norm(t):
    return re.sub(r"[^a-z0-9']", "", str(t).lower())


def _clean(t):
    return re.sub(r"[{}\\]", "", str(t))


def _ass_color(hexcolor):
    """#RRGGBB -> &H00BBGGRR&"""
    h = (hexcolor or "").lstrip("#")
    if len(h) != 6:
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None
    return f"&H00{b:02X}{g:02X}{r:02X}&"


def chunk(words, n=MAX_WORDS_LINE):
    """Kenglik-hisob chunking (doc P1): <=3 so'z VA 96px da sig'adi
    (bir qator yoki 2 qator). Shrift kichraytirilmaydi."""
    out, cur = [], []
    for w in words:
        trial = cur + [w]
        if len(trial) > n or not _fits(trial):
            if cur:
                out.append(cur)
            cur = [w]
        else:
            cur = trial
        if str(w[0]).endswith((".", "?", "!", ",")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _line_w(txt_words, size, active=False):
    """Qator kengligi; active=True -> birinchi so'z 115% (doc B4 pop)."""
    if not txt_words:
        return 0.0
    w = text_width(txt_words[0], size)        # v10.1: o'lcham bir xil
    if len(txt_words) > 1:
        w += text_width(" ".join(txt_words[1:]), size) \
            + text_width(" ", size) * (len(txt_words) - 1)
    return w


def _fits(ch, size=FONT_SIZE):
    """chunk 96px da sig'adimi (1 yoki 2 qator)? (render KATTA harfda!)"""
    words = [str(x[0]).upper() for x in ch]
    if _line_w(words, size, active=True) <= SAFE_W:
        return True
    if len(ch) >= 2:
        for k in range(1, len(ch)):
            if max(_line_w(words[:k], size, active=True),
                   _line_w(words[k:], size)) <= SAFE_W:
                return True
    return False


def _ass_head(cfg, y):
    cap = cfg.get("captions", {})
    size = int(cap.get("font_size", FONT_SIZE))
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Cap,{FONT},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,11,3,5,110,110,0,1
Style: Mid,{FONT},132,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,12,5,5,110,110,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
""", size


def caption_y(cfg, mode):
    cap = cfg.get("captions", {})
    if str(mode) == "stock":
        return int(cap.get("y_stock", 1150))
    return int(cap.get("y_map", 950))


def build_scene_ass(cfg, scene, words, dur, path):
    """Segment ASS. Subtitr (cfg.captions.enabled) + v7 katta mid-so'z."""
    y = caption_y(cfg, scene.get("mode", "map"))
    highlights = {}
    for h in (scene.get("highlights") or []):
        w = _norm(h.get("word", ""))
        col = _ass_color(h.get("color", ""))
        if w and col:
            highlights[w] = col
    if not highlights:
        try:
            from . import geo
            work = os.path.dirname(path)
            for iso in (scene.get("country_iso_codes") or [])[:1]:
                col = geo.flag_color(iso, work)
                if col:
                    highlights[_norm(scene.get("map", {}).get("focus", ""))] = \
                        _ass_color("#%02X%02X%02X" % col)
        except Exception:
            pass

    head, size = _ass_head(cfg, y)
    ev, chunk_ts = [], []
    sub_on = bool(cfg.get("captions", {}).get("enabled", True))
    if sub_on:
        mw = max(1, int(cfg.get("captions", {}).get("max_words", 2)))
        for ch in chunk(words, n=mw):
            s = max(0.0, ch[0][1])
            e = min(dur, ch[-1][2] + 0.10)
            if e <= s:
                e = s + 0.12
            chunk_ts.append(round(s, 3))
            split, base = _split2(ch, size)
            parts = []
            for (wtxt, _ws, _we) in ch:
                nw = _norm(wtxt)
                color = highlights.get(nw)
                txt = _clean(wtxt).upper()
                # v10.1 (user): o'lcham HAMMA so'zda BIR XIL (100px);
                # faqat kalit so'z RANGI cyan — kattalik o'zgarmaydi
                if color:
                    parts.append("{\\c" + color + "}" + txt + "{\\r}")
                else:
                    parts.append(txt)
            if split:
                line = " ".join(parts[:split]) + "\\N" + " ".join(parts[split:])
            else:
                line = " ".join(parts)
            ev.append(f"Dialogue: 0,{_t(s)},{_t(e)},Cap,,0,0,0,,"
                      r"{\an5\pos(540," + str(y) + r")\fs" + str(base)
                      + "}"
                      + line)
    # v7 immersive: o'rtadagi katta "reveal" so'zi (IN FRANCE uslubi)
    mid = str(scene.get("mid_text") or "").strip()
    if mid:
        m0 = 0.30
        # v9: mid ham kesishdan 0.35s oldin yo'qoladi (ustma-ust yo'q)
        m1 = min(dur - 0.35, m0 + 1.5)
        if m1 > m0 + 0.2:
            # v9: kenglik fit ("WORST BORDERS ON EARTH" kesilmasin):
            # 132 -> 116 -> 100 -> 88; hali keng bo'lsa 2 qator \N
            txt = _clean(mid).upper()
            shown, size = txt, 132
            for size in (132, 116, 100, 88):
                if text_width(txt, size) <= 880:
                    break
            else:
                size = 88
                ws = txt.split()
                best, bw = txt, text_width(txt, size)
                for k in range(1, len(ws)):
                    l1 = "\\N".join([" ".join(ws[:k]), " ".join(ws[k:])])
                    w1 = max(text_width(p, size) for p in l1.split("\\N"))
                    if w1 < bw:
                        best, bw = l1, w1
                shown = best
            ev.append(f"Dialogue: 1,{_t(m0)},{_t(m1)},Mid,,0,0,0,,"
                      r"{\an5\pos(540," + str(MID_Y) + r")"
                      r"\fscx60\fscy60\t(0,120,\fscx100\fscy100)"
                      r"\t(120,320,\fscx104\fscy104)"
                      r"\t(320,520,\fscx100\fscy100)"
                      r"\fs" + str(size) + "}"
                      + shown)
    # v9: bir xil Style'da dialoglar ustma-ust tushmasin —
    # yangi chiqqanda eskisi avval o'chadi
    import re as _re

    def _ts2s(x):
        h, m, s = x.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    def _s2ts(v):
        v = max(0.0, v)
        return f"{int(v // 3600)}:{int((v % 3600) // 60):02d}:{v % 60:05.2f}"

    _last = {}
    fixed = []
    for line in ev:
        mm = _re.match(r"(Dialogue: \d+,)([\d:.]+),([\d:.]+),([^,]*)(,.*)$",
                       line)
        if not mm:
            fixed.append(line)
            continue
        st, en, sty = _ts2s(mm.group(2)), _ts2s(mm.group(3)), mm.group(4)
        st = max(st, _last.get(sty, -1.0) + 0.001)
        en = max(en, st + 0.05)
        _last[sty] = en
        fixed.append(mm.group(1) + _s2ts(st) + "," + _s2ts(en)
                     + "," + sty + mm.group(5))
    ev = fixed
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(ev) + "\n")
    return path, chunk_ts
