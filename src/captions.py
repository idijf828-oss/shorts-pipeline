"""Safe-zone matn + Hormozi-uslub so'zma-so'z subtitrlar (ASS).

Qoidalar (1080x1920 Shorts):
  - maksimal matn kengligi 860 px -> x har doim [110, 970] ichida
  - bir vaqtda 1-3 so'z; aytilayotgan so'z SARIQ + 115% masshtab
  - dinamik subtitr y~1150 (Shorts UI yopmaydigan zonada)
  - statik on_screen matn tepada (y~300), 16 belgi/qator

words = [(word, start_sec, end_sec), ...]
"""
import os
import re

W, H = 1080, 1920
SAFE_W = 860
MAX_WORDS_LINE = 3
FONT = "Montserrat ExtraBold"   # workflow'da fonts-montserrat o'rnatiladi
FONT_SIZE = 96

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
    """Qator kengligi pikselda (PIL bilan aniq, bo'lmasa taxminiy)."""
    fp = _font_path()
    if fp:
        try:
            from PIL import ImageFont
            return ImageFont.truetype(fp, size).getlength(text)
        except Exception:
            pass
    return max(len(l) for l in text.split("\n")) * size * 0.62


def fit_font(text, base=FONT_SIZE, max_w=SAFE_W):
    """Eng uzun qator max_w ga sig'gunicha shriftni kichraytirish."""
    size = base
    while size > 40 and text_width(text, size) > max_w:
        size -= 4
    return size


def wrap_title(text, max_chars=16):
    """Statik sarlavha: qisqa qatorlarga bo'lish (16 belgi/qator)."""
    words, lines, cur = text.upper().split(), [], ""
    for w in words:
        if len((cur + " " + w).strip()) > max_chars and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def _t(s):
    h, m = int(s // 3600), int(s % 3600 // 60)
    return f"{h}:{m:02d}:{s % 60:05.2f}"


def _clean(t):
    r"""ASS matnida qavslar ({}) ishlamaydi — olib tashlash."""
    return re.sub(r"[{}\\]", "", str(t))


def chunk(words, n=MAX_WORDS_LINE):
    """1-3 so'zlik guruhlar; tinish belgisi bo'lsa erta uzish."""
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == n or str(w[0]).endswith((".", "?", "!", ",", "...")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _ass_head(cfg):
    cap = cfg.get("captions", {})
    y = int(cap.get("y", 1150))
    size = int(cap.get("font_size", FONT_SIZE))
    top_size = int(cap.get("top_size", 64))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Cap,{FONT},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H60000000,-1,0,0,0,100,100,0,0,1,8,3,5,110,110,0,1
Style: Top,{FONT},{top_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H60000000,-1,0,0,0,100,100,0,0,1,6,2,5,110,110,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    return head, y


def build_scene_ass(cfg, scene, words, dur, path):
    """Sahna subtitri: dinamik so'zlar (y~1150) + statik on_screen (tepa)."""
    head, y = _ass_head(cfg)
    ev = []

    # --- statik on_screen (tepa, butun sahna davomida) ---
    ov = wrap_title(_clean(scene.get("on_screen", ""))[:80])
    if ov.strip():
        base_top = int(cfg.get("captions", {}).get("top_size", 64))
        fsize = fit_font(ov, base=base_top)
        ev.append(f"Dialogue: 0,{_t(0.05)},{_t(max(dur - 0.1, 0.2))},Top,,0,0,0,,"
                  r"{\an5\pos(540,300)\fs" + str(fsize) + "}"
                  + ov.replace("\n", r"\N"))

    # --- dinamik so'zma-so'z subtitr ---
    for ch in chunk(words):
        line = " ".join(_clean(w[0]) for w in ch).upper()
        fsize = fit_font(line)
        for i, (w, s, e) in enumerate(ch):
            end = ch[i + 1][1] if i + 1 < len(ch) else e
            end = min(end, dur)
            parts = []
            for j, (ww, _, _) in enumerate(ch):
                ww = _clean(ww).upper()
                if j == i:
                    parts.append(r"{\c&H00FFFF&\fscx115\fscy115}" + ww
                                 + r"{\c&HFFFFFF&\fscx100\fscy100}")
                else:
                    parts.append(ww)
            ev.append(f"Dialogue: 0,{_t(max(0.0, s))},{_t(end)},Cap,,0,0,0,,"
                      r"{\an5\pos(540," + str(y) + r")\fs" + str(fsize) + "}"
                      + " ".join(parts))

    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(ev) + "\n")
    return path
