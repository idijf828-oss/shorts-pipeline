"""Xarita va bayroq muharriti (Info Hub uslubi).

- Fon: Esri World Imagery sun'iy yo'ldosh plitalari (tile) — kalitsiz.
- Chegara: assets/world.geo.json (Natural Earth) — barcha davlatlar konturi.
- AJRATISH: mamlakat poligoni BAYROQ texturasi bilan to'ldiriladi
  (flagcdn.com, ISO2) + oq kontur + nom yorlig'i.
- Kamera: katta canvas (1440x2560) ustida ffmpeg zoompan — silliq
  zoom-in/zoom-out harakati (1080x1920 ga render).
- Esri ishlamasa -> src/maps.py vektor xaritasi fallback.

Tile matematikasi: Web Mercator (slippy map).
"""
import io
import math
import os

from PIL import Image, ImageDraw, ImageFont

from src.net import session

ESRI = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}")
FLAG_CDN = "https://flagcdn.com/w320/{iso2}.png"
ATTRIB = "Imagery (c) Esri, Maxar, Earthstar Geographics"

GEOJSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets", "world.geo.json")

# Asosiy davlatlar: ISO2 -> ISO3 (world.geo.json id'lari ISO3)
ISO2_TO_ISO3 = {
    "af": "AFG", "al": "ALB", "dz": "DZA", "ar": "ARG", "am": "ARM",
    "au": "AUS", "at": "AUT", "az": "AZE", "bh": "BHR", "bd": "BGD",
    "by": "BLR", "be": "BEL", "bo": "BOL", "ba": "BIH", "bw": "BWA",
    "br": "BRA", "bg": "BGR", "kh": "KHM", "cm": "CMR", "ca": "CAN",
    "td": "TCD", "cl": "CHL", "cn": "CHN", "co": "COL", "cr": "CRI",
    "hr": "HRV", "cu": "CUB", "cy": "CYP", "cz": "CZE", "dk": "DNK",
    "do": "DOM", "ec": "ECU", "eg": "EGY", "sv": "SLV", "ee": "EST",
    "et": "ETH", "fi": "FIN", "fr": "FRA", "ge": "GEO", "de": "DEU",
    "gh": "GHA", "gr": "GRC", "gt": "GTM", "hn": "HND", "hu": "HUN",
    "is": "ISL", "in": "IND", "id": "IDN", "ir": "IRN", "iq": "IRQ",
    "ie": "IRL", "il": "ISR", "it": "ITA", "jm": "JAM", "jp": "JPN",
    "jo": "JOR", "kz": "KAZ", "ke": "KEN", "kw": "KWT", "kg": "KGZ",
    "la": "LAO", "lv": "LVA", "lb": "LBN", "ly": "LBY", "lt": "LTU",
    "lu": "LUX", "my": "MYS", "mt": "MLT", "mx": "MEX", "md": "MDA",
    "mn": "MNG", "me": "MNE", "ma": "MAR", "mm": "MMR", "na": "NAM",
    "np": "NPL", "nl": "NLD", "nz": "NZL", "ni": "NIC", "ng": "NGA",
    "mk": "MKD", "no": "NOR", "om": "OMN", "pk": "PAK", "pa": "PAN",
    "py": "PRY", "pe": "PER", "ph": "PHL", "pl": "POL", "pt": "PRT",
    "qa": "QAT", "ro": "ROU", "ru": "RUS", "sa": "SAU", "sn": "SEN",
    "rs": "SRB", "sg": "SGP", "sk": "SVK", "si": "SVN", "so": "SOM",
    "za": "ZAF", "kr": "KOR", "es": "ESP", "lk": "LKA", "sd": "SDN",
    "se": "SWE", "ch": "CHE", "sy": "SYR", "tw": "TWN", "tj": "TJK",
    "tz": "TZA", "th": "THA", "tn": "TUN", "tr": "TUR", "tm": "TKM",
    "ua": "UKR", "ae": "ARE", "gb": "GBR", "us": "USA", "uy": "URY",
    "uz": "UZB", "ve": "VEN", "vn": "VNM", "ye": "YEM", "zm": "ZMB",
    "zw": "ZWE", "ps": "PSE", "xk": "XKX", "cw": "CUW", "gy": "GUY",
    "sr": "SUR", "bz": "BLZ", "gq": "GNQ", "ga": "GAB", "cg": "COG",
    "cd": "COD", "ao": "AGO", "mz": "MOZ", "mg": "MDG", "mw": "MWI",
    "rw": "RWA", "bi": "BDI", "ml": "MLI", "ne": "NER", "td2": "TCD",
    "bf": "BFA", "bj": "BEN", "tg": "TGO", "ci": "CIV", "gh2": "GHA",
    "lr": "LBR", "sl": "SLE", "gn": "GIN", "gm": "GMB", "mr": "MRT",
    "er": "ERI", "dj": "DJI", "ss": "SSD", "cf": "CAF", "cm2": "CMR",
}

_COUNTRIES = None


def _countries():
    global _COUNTRIES
    if _COUNTRIES is None:
        import json
        with open(GEOJSON, encoding="utf-8") as f:
            gj = json.load(f)
        _COUNTRIES = {}
        for ft in gj["features"]:
            iso3 = ft.get("id") or ""
            name = (ft.get("properties") or {}).get("name", "")
            _COUNTRIES[iso3] = (name, ft["geometry"])
    return _COUNTRIES


def _rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


# ---------- Mercator piksel matematikasi ----------
def _gpx(lat, lon, z):
    """Global piksel (x, y) — zoom z (tile * 256)."""
    n = 256 * (2 ** z)
    x = (lon + 180.0) / 360.0 * n
    la = math.radians(max(-85.05, min(85.05, lat)))
    y = (1.0 - math.log(math.tan(la) + 1.0 / math.cos(la)) / math.pi) / 2.0 * n
    return x, y


def _fetch_tile(z, x, y, cache_dir):
    """Bitta Esri plitasini (cache bilan) yuklaydi."""
    os.makedirs(cache_dir, exist_ok=True)
    dest = os.path.join(cache_dir, f"{z}_{x}_{y}.jpg")
    if os.path.exists(dest) and os.path.getsize(dest) > 500:
        return dest
    r = session().get(ESRI.format(z=z, y=y, x=x), timeout=25)
    if r.status_code != 200 or len(r.content) < 500:
        raise RuntimeError(f"tile {z}/{x}/{y} HTTP {r.status_code}")
    with open(dest, "wb") as f:
        f.write(r.content)
    return dest


def _download_flag(iso2, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    dest = os.path.join(cache_dir, f"{iso2.lower()}.png")
    if os.path.exists(dest) and os.path.getsize(dest) > 300:
        return dest
    r = session().get(FLAG_CDN.format(iso2=iso2.lower()), timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"flag {iso2} HTTP {r.status_code}")
    with open(dest, "wb") as f:
        f.write(r.content)
    return dest


def _font(size):
    for p in ("/usr/share/fonts/truetype/montserrat/Montserrat-ExtraBold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def compose_map(cam, iso_codes, work_dir, W=1440, H=2560):
    """Sun'iy yo'ldosh fon + chegara + bayroq-to'ldirilgan davlatlar.

    cam: {"lat","lon","zoom_level","motion","label"}
    Qaytaradi: (png_yo'l, zoom_start, zoom_end) — render'da zoompan uchun.
    """
    z = max(3, min(16, int(cam["zoom_level"])))
    lat, lon = cam["lat"], cam["lon"]
    cache = os.path.join(work_dir, "tiles")

    cx, cy = _gpx(lat, lon, z)
    ox, oy = cx - W / 2, cy - H / 2          # canvas boshlanishi (global px)
    x0, y0 = int(ox // 256), int(oy // 256)
    x1, y1 = int((ox + W) // 256), int((oy + H) // 256)

    img = Image.new("RGB", (W, H), (8, 14, 24))
    n_tiles = 0
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            try:
                p = _fetch_tile(z, tx, ty, cache)
                tile = Image.open(p).convert("RGB")
                img.paste(tile, (int(tx * 256 - ox), int(ty * 256 - oy)))
                n_tiles += 1
            except Exception as e:
                print(f"[geo] tile o'tkazildi {z}/{tx}/{ty}: {e}")
    if n_tiles < (x1 - x0 + 1) * (y1 - y0 + 1) * 0.5:
        raise RuntimeError("Esri plitalarining yarmi kelmadi — vektorga o'tamiz")

    # ---- chegara + bayroq qatlami ----
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)

    def to_px(lo, la):
        gx, gy = _gpx(la, lo, z)
        return gx - ox, gy - oy

    # barcha davlatlar konturi (nozik oq)
    for iso3, (name, geom) in _countries().items():
        for poly in _rings(geom):
            pts = [to_px(x, y) for x, y in poly[0]]
            if len(pts) < 3:
                continue
            # canvas bilan kesishishini tekshirish (qo'pol)
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if max(xs) < -50 or min(xs) > W + 50 or max(ys) < -50 or min(ys) > H + 50:
                continue
            d.line(pts + [pts[0]], fill=(255, 255, 255, 110), width=2)

    # ajratilgan davlatlar: bayroq to'ldirish
    for iso2 in (iso_codes or []):
        iso3 = ISO2_TO_ISO3.get(iso2.lower())
        if not iso3 or iso3 not in _countries():
            print(f"[geo] {iso2} uchun poligon topilmadi")
            continue
        name, geom = _countries()[iso3]
        try:
            flag = Image.open(_download_flag(iso2, cache)).convert("RGBA")
        except Exception as e:
            print(f"[geo] bayroq kelmadi {iso2}: {e}")
            continue
        for poly in _rings(geom):
            pts = [to_px(x, y) for x, y in poly[0]]
            if len(pts) < 3:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bx0, by0, bx1, by1 = min(xs), min(ys), max(xs), max(ys)
            if bx1 < 0 or bx0 > W or by1 < 0 or by0 > H:
                continue
            # bayroqni bbox'ga moslab, poligon maskasi bilan qo'yish
            bw = max(8, int(bx1 - bx0))
            bh = max(8, int(by1 - by0))
            fl = flag.resize((min(bw, 2048), min(bh, 2048)))
            mask = Image.new("L", (W, H), 0)
            md = ImageDraw.Draw(mask)
            md.polygon(pts, fill=140)          # 55% shaffoflik
            flayer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            flayer.paste(fl, (int(bx0), int(by0)))
            ov = Image.alpha_composite(ov, Image.composite(
                flayer, Image.new("RGBA", (W, H), (0, 0, 0, 0)), mask))
            d = ImageDraw.Draw(ov)
            d.line(pts + [pts[0]], fill=(255, 255, 255, 255), width=6)
            # davlat nomi
            f = _font(54)
            d.text(((bx0 + bx1) / 2, max(20, by0 - 44)), name.upper(),
                   font=f, fill="white", anchor="mm",
                   stroke_width=5, stroke_fill="black")

    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

    # kamera yorlig'i + atributsiya endi render'da drawtext bilan
    # (qat'iy pozitsiya — chuqur zoom'da ham kadr ichida qoladi)
    out = os.path.join(work_dir, f"map_{abs(hash((lat, lon, z))) % 10**8}.png")
    img.save(out, quality=92)
    motion = cam.get("motion", "zoom_in")
    if motion == "zoom_out":
        zs, ze = 1.42, 1.02
    else:
        zs, ze = 1.02, 1.42
    print(f"[geo] xarita tayyor: {cam.get('label') or (lat, lon)} z={z} "
          f"({n_tiles} tile, {len(iso_codes or [])} bayroq)")
    return out, zs, ze
