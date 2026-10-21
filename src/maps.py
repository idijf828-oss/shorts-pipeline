"""Xarita fallback: offline GeoJSON + PIL render (keyin zoompan animatsiya).

Pexels/Pixabay'da must_contain'ga mos klip topilmasa ishlatiladi.
Okean to'q ko'k, mamlakatlar pastel-yashil, maqsadli davlatlar
qizil chegarali + markazda marker + tepada joy nomi.
Ma'lumot: johan/world.geo.json (Natural Earth asosida, 180 mamlakat).
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
GEOJSON = os.path.join(ASSETS, "world.geo.json")

OCEAN = (16, 42, 66)
LAND = [(96, 130, 96), (108, 138, 106), (88, 122, 92), (116, 146, 110)]
BORDER = (24, 36, 28)
HILITE = (224, 62, 62)
HILITE_FILL = (128, 64, 56)

# Maxsus joylar: kichik bbox + qaysi davlatlar ajratilishi
SPECIAL = {
    "baarle": {"bbox": (4.80, 51.38, 5.10, 51.52), "label": "BAARLE (BE/NL)",
               "highlight": ["Belgium", "Netherlands"]},
    "bidasoa": {"bbox": (-1.95, 43.28, -1.55, 43.44), "label": "PHEASANT ISLAND (ES/FR)",
                "highlight": ["Spain", "France"]},
    "pheasant": {"bbox": (-1.95, 43.28, -1.55, 43.44), "label": "PHEASANT ISLAND (ES/FR)",
                 "highlight": ["Spain", "France"]},
    "saint martin": {"bbox": (-63.28, 17.98, -62.92, 18.17), "label": "SAINT MARTIN (FR/NL)",
                     "highlight": ["France", "Netherlands"]},
    "sint maarten": {"bbox": (-63.28, 17.98, -62.92, 18.17), "label": "SAINT MARTIN (FR/NL)",
                     "highlight": ["France", "Netherlands"]},
    "vermont": {"bbox": (-72.35, 44.95, -71.95, 45.15), "label": "US-CANADA LINE",
                "highlight": ["United States of America", "Canada"]},
    "derby": {"bbox": (-72.35, 44.95, -71.95, 45.15), "label": "US-CANADA LINE",
              "highlight": ["United States of America", "Canada"]},
    "india bangladesh": {"bbox": (88.30, 24.95, 89.60, 25.70), "label": "3 LAYERS DEEP",
                         "highlight": ["India", "Bangladesh"]},
    "enclave": {"bbox": (88.30, 24.95, 89.60, 25.70), "label": "3 LAYERS DEEP",
                "highlight": ["India", "Bangladesh"]},
}

_C = None


def _countries():
    global _C
    if _C is None:
        with open(GEOJSON, encoding="utf-8") as f:
            gj = json.load(f)
        _C = [(ft["properties"]["name"], ft["geometry"]) for ft in gj["features"]]
    return _C


def _rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def _bbox(geom):
    xs, ys = [], []
    for poly in _rings(geom):
        for x, y in poly[0]:
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _lookup(place):
    p = str(place).lower().strip()
    for k, v in SPECIAL.items():
        if k in p:
            return v
    for name, geom in _countries():
        if p and (p in name.lower() or name.lower() in p):
            b = _bbox(geom)
            if b:
                return {"bbox": b, "label": str(place).upper()[:28], "highlight": [name]}
    return None


def _label_font(size):
    for p in ("/usr/share/fonts/truetype/montserrat/Montserrat-ExtraBold.ttf",
              "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def map_image(place, dest, width=1080, height=1920):
    """Xarita PNG yaratadi (zoompan keyin render'da animatsiya beradi)."""
    info = _lookup(place) or {
        "bbox": (-12.0, 38.0, 32.0, 60.0),
        "label": str(place).upper()[:28] or "WORLD", "highlight": []}
    x0, y0, x1, y1 = info["bbox"]
    mx = (x1 - x0) * 0.28 or 1.0
    my = (y1 - y0) * 0.28 or 1.0
    x0, y0, x1, y1 = x0 - mx, y0 - my, x1 + mx, y1 + my

    S = 2  # supersample -> silliqlash
    W, H = width * S, height * S
    img = Image.new("RGB", (W, H), OCEAN)
    d = ImageDraw.Draw(img)

    def px(lon, lat):
        return ((lon - x0) / (x1 - x0) * W, (1 - (lat - y0) / (y1 - y0)) * H)

    hset = set(info["highlight"])
    for idx, (name, geom) in enumerate(_countries()):
        hil = name in hset
        fill = HILITE_FILL if hil else LAND[idx % len(LAND)]
        for poly in _rings(geom):
            pts = [px(x, y) for x, y in poly[0]]
            if len(pts) < 3:
                continue
            try:
                d.polygon(pts, fill=fill, outline=HILITE if hil else BORDER)
            except Exception:
                pass

    # markerning halqasi (kichik joylar uchun)
    cx, cy = px((x0 + x1) / 2, (y0 + y1) / 2)
    r = 26 * S
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=HILITE, width=8 * S // 2)
    d.line([cx - r * 1.7, cy, cx + r * 1.7, cy], fill=HILITE, width=4 * S // 2)
    d.line([cx, cy - r * 1.7, cx, cy + r * 1.7], fill=HILITE, width=4 * S // 2)

    # tepada joy nomi
    f = _label_font(58 * S)
    label = info["label"]
    tw = d.textlength(label, font=f)
    d.rectangle([W // 2 - tw / 2 - 26 * S, 118 * S, W // 2 + tw / 2 + 26 * S, 222 * S],
                fill=(12, 12, 18))
    d.text((W // 2, 170 * S), label, font=f, fill="white", anchor="mm")

    img = img.resize((width, height), Image.LANCZOS)
    img.save(dest, quality=92)
    return dest
