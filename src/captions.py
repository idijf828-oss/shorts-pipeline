"""Markaziy 1-2 SO'ZLIK pop-in subtitrlar (Info Hub uslubi).

- Ekran MARKAZIDA (y~960), bir vaqtda maks 2 so'z
- Qalin oq shrift (Montserrat ExtraBold) + qora kontur + soya
- Har chunk POP-IN masshtab animatsiyasi bilan kiradi (\t transform)
- Maksimal kenglik 800px -> x har doim [140..940] ichida
- So'z vaqtlari: edge-tts WordBoundary (aniq) / gTTS taxminiy

words = [(word, start_sec, end_sec), ...]
"""
import os
import re

W, H = 1080, 1920
SAFE_W = 800
MAX_WORDS_LINE = 2
FONT = "Montserrat ExtraBold"
FONT_SIZE = 110

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


def fit_font(text, base=FONT_SIZE, max_w=SAFE_W):
    size = base
    while size > 44 and text_width(text, size) > max_w:
        size -= 4
    return size


def _t(s):
    h, m = int(s // 3600), int(s % 3600 // 60)
    return f"{h}:{m:02d}:{s % 60:05.2f}"


def _clean(t):
    return re.sub(r"[{}\\]", "", str(t))


def chunk(words, n=MAX_WORDS_LINE):
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
    y = int(cap.get("y", 960))
    size = int(cap.get("font_size", FONT_SIZE))
    global SAFE_W, MAX_WORDS_LINE
    SAFE_W = int(cap.get("safe_w", SAFE_W))
    MAX_WORDS_LINE = int(cap.get("max_words", MAX_WORDS_LINE))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Cap,{FONT},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,10,4,5,110,110,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    return head, y


def build_scene_ass(cfg, scene, words, dur, path):
    """Segment subtitri: 1-2 so'zlik chunklar, pop-in bilan."""
    head, y = _ass_head(cfg)
    ev = []
    for ch in chunk(words):
        line = " ".join(_clean(w[0]) for w in ch).upper()
        if not line.strip():
            continue
        fsize = fit_font(line)
        s = max(0.0, ch[0][1])
        e = min(dur, ch[-1][2] + 0.12)
        if e <= s:
            e = s + 0.12
        ev.append(f"Dialogue: 0,{_t(s)},{_t(e)},Cap,,0,0,0,,"
                  r"{\an5\pos(540," + str(y) + r")\fs" + str(fsize)
                  + r"\fscx25\fscy25\t(0,110,\fscx100\fscy100)}"
                  + line)
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(ev) + "\n")
    return path
