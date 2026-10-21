"""Ikonkalar (stickers): OpenMoji PNG + PIL chizilgan strelkalar.

LLM "overlay_icons" da kalit so'z + emoji beradi -> bu modul ikonka PNG'sini
topadi/yuklaydi (cache) va render'ga uzatadi. Animatsiya (pop-in) render'da:
alpha fade + siljish + SFX "pop".
"""
import os

from PIL import Image, ImageDraw

from src.net import session

OPENMOJI = ("https://raw.githubusercontent.com/hfg-gmuend/openmoji/"
            "master/color/618x618/{code}.png")

# Chizilgan shakllar (emoji yo'q bo'lsa yoki tarmoq yo'q)
SHAPES = ("arrow_right", "arrow_left", "arrow_up", "arrow_down", "star",
          "exclamation")


def _code(emoji):
    """Emoji -> OpenMoji kodi: HEX katta harf, '-' bilan; FE0F tashlanadi."""
    return "-".join(f"{ord(c):X}" for c in emoji
                    if ord(c) > 0x2000 and ord(c) != 0xFE0F)


def _shape_path(name, cache):
    """PIL bilan sariq strelka/yulduz chizish."""
    dest = os.path.join(cache, f"shape_{name}.png")
    if os.path.exists(dest):
        return dest
    S = 618
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = (255, 214, 0, 255)
    o = (30, 30, 30, 255)
    if name == "arrow_right":
        d.polygon([(40, 200), (400, 200), (400, 90), (580, 309),
                   (400, 528), (400, 418), (40, 418)], fill=y, outline=o)
    elif name == "arrow_left":
        img2 = Image.open(_shape_path("arrow_right", cache)) if os.path.exists(
            os.path.join(cache, "shape_arrow_right.png")) else None
        if img2 is None:
            _shape_path("arrow_right", cache)
        img2 = Image.open(os.path.join(cache, "shape_arrow_right.png"))
        img = img2.transpose(Image.FLIP_LEFT_RIGHT)
        img.save(dest)
        return dest
    elif name == "arrow_up":
        d.polygon([(200, 580), (200, 220), (90, 220), (309, 40),
                   (528, 220), (418, 220), (418, 580)], fill=y, outline=o)
    elif name == "arrow_down":
        d.polygon([(200, 40), (200, 400), (90, 400), (309, 580),
                   (528, 400), (418, 400), (418, 40)], fill=y, outline=o)
    elif name == "star":
        import math
        pts = []
        for k in range(10):
            r = 300 if k % 2 == 0 else 130
            a = math.pi / 2 + k * math.pi / 5
            pts.append((309 + r * math.cos(a), 309 + r * math.sin(a)))
        d.polygon(pts, fill=y, outline=o)
    elif name == "exclamation":
        d.rounded_rectangle([(240, 60), (380, 380)], 40, fill=y, outline=o)
        d.ellipse([(240, 440), (380, 580)], fill=y, outline=o)
    img.save(dest)
    return dest


def get_icon(spec, work_dir, size=300):
    """Ikonka yo'lini topadi (emoji yoki shape). RGBA PNG qaytaradi."""
    cache = os.path.join(work_dir, "icons")
    os.makedirs(cache, exist_ok=True)
    emoji = (spec.get("emoji") or "").strip()
    if not emoji:
        return None
    # shape nomlari
    key = emoji.lower().replace(" ", "_")
    if key in SHAPES:
        p = _shape_path(key, cache)
        img = Image.open(p).convert("RGBA")
    else:
        code = _code(emoji)
        if not code:
            return None
        dest = os.path.join(cache, f"{code}.png")
        if not (os.path.exists(dest) and os.path.getsize(dest) > 500):
            r = session().get(OPENMOJI.format(code=code.upper()), timeout=20)
            if r.status_code != 200 or len(r.content) < 500:
                print(f"[icons] OpenMoji kelmadi: {emoji}")
                return None
            with open(dest, "wb") as f:
                f.write(r.content)
        img = Image.open(dest).convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    out = os.path.join(cache, f"r_{abs(hash((emoji, size))) % 10**8}.png")
    img.save(out)
    return out
