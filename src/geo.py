"""V4 geo: Natural Earth II raster (public domain) — Esri YO'Q, atributsiya YO'Q.

- Fon: NE2_50M_SR_W (assets/ne2_50m.jpg, 10800x5400, equirect, 30px/deg).
  Keng kadrlar (z<=6, upscale <=2x): raster fon — reference'dagi
  "quyuq-ko'k okean + relyef" ko'rinishi.
  Yaqin kadrlar (z>=7): toza VEKTOR uslub — navy #0B1F33 + graticule +
  ochroq davlat fillarlari (map-explainer estetikasi).
- Bayroqlar: assets/flags/<iso2>.svg (lipis/flag-icons, MIT) ->
  rsvg-convert -> PNG. Tarmoq KERAK EMAS.
- Bayroq-fill: poligon mask + bayroq bbox'ga cho'z + 3px oq kontur —
  ALOHIDA RGBA qatlam sifatida (so'z vaqtida reveal qilinadi).
- Palitra: navy #0B1F33, cyan #00E5FF, red #FF2D2D, yellow #FFD400.
"""
import json
import math
import os
import subprocess
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
NE2 = os.path.join(ASSETS, "ne2_50m.jpg")
GEOJSON = os.path.join(ASSETS, "world.geo.json")
FLAG_DIR = os.path.join(ASSETS, "flags")

W, H = 1440, 2560
RPX_W, RPX_H = 10800, 5400            # NE2 raster (equirect, 30px/deg)
PX_DEG = RPX_W / 360.0

NAVY = (11, 31, 51)                    # #0B1F33
NAVY_LIGHT = (22, 50, 75)              # vektor rejimdagi quruq fill
CYAN = (0, 229, 255)                   # #00E5FF
RED = (255, 45, 45)                    # #FF2D2D
YELLOW = (255, 212, 0)                 # #FFD400

ISO2_TO_ISO3 = {
    "af": "AFG", "al": "ALB", "dz": "DZA", "ar": "ARG", "am": "ARM",
    "au": "AUS", "at": "AUT", "az": "AZE", "bs": "BHS", "bh": "BHR",
    "bd": "BGD", "by": "BLR", "be": "BEL", "bo": "BOL", "ba": "BIH",
    "bw": "BWA", "br": "BRA", "bg": "BGR", "bf": "BFA", "kh": "KHM",
    "cm": "CMR", "ca": "CAN", "td": "TCD", "cl": "CHL", "cn": "CHN",
    "co": "COL", "cr": "CRI", "hr": "HRV", "cu": "CUB", "cy": "CYP",
    "cz": "CZE", "dk": "DNK", "do": "DOM", "ec": "ECU", "eg": "EGY",
    "sv": "SLV", "ee": "EST", "et": "ETH", "fi": "FIN", "fr": "FRA",
    "ge": "GEO", "de": "DEU", "gh": "GHA", "gr": "GRC", "gt": "GTM",
    "hn": "HND", "hu": "HUN", "is": "ISL", "in": "IND", "id": "IDN",
    "ir": "IRN", "iq": "IRQ", "ie": "IRL", "il": "ISR", "it": "ITA",
    "jm": "JAM", "jp": "JPN", "jo": "JOR", "kz": "KAZ", "ke": "KEN",
    "kw": "KWT", "kg": "KGZ", "la": "LAO", "lv": "LVA", "lb": "LBN",
    "ly": "LBY", "lt": "LTU", "lu": "LUX", "my": "MYS", "mt": "MLT",
    "mx": "MEX", "md": "MDA", "mn": "MNG", "me": "MNE", "ma": "MAR",
    "mz": "MOZ", "mm": "MMR", "na": "NAM", "np": "NPL", "nl": "NLD",
    "nz": "NZL", "ni": "NIC", "ng": "NGA", "kp": "PRK", "mk": "MKD",
    "no": "NOR", "om": "OMN", "pk": "PAK", "pa": "PAN", "py": "PRY",
    "pe": "PER", "ph": "PHL", "pl": "POL", "pt": "PRT", "qa": "QAT",
    "ro": "ROU", "ru": "RUS", "sa": "SAU", "sn": "SEN", "rs": "SRB",
    "sg": "SGP", "sk": "SVK", "si": "SVN", "so": "SOM", "za": "ZAF",
    "kr": "KOR", "es": "ESP", "lk": "LKA", "sd": "SDN", "se": "SWE",
    "ch": "CHE", "sy": "SYR", "tw": "TWN", "tj": "TJK", "tz": "TZA",
    "th": "THA", "tn": "TUN", "tr": "TUR", "tm": "TKM", "ug": "UGA",
    "ua": "UKR", "ae": "ARE", "gb": "GBR", "us": "USA", "uy": "URY",
    "uz": "UZB", "ve": "VEN", "vn": "VNM", "ye": "YEM", "zm": "ZMB",
    "zw": "ZWE", "ps": "PSE", "xk": "XKX", "cw": "CUW", "sr": "SUR",
    "gy": "GUY", "bz": "BLZ", "bj": "BEN", "tg": "TGO", "er": "ERI",
    "dj": "DJI", "ga": "GAB", "cg": "COG", "cd": "COD", "ao": "AGO",
    "zm2": "ZMB", "mr": "MRT", "ml": "MLI", "ne": "NER", "td2": "TCD",
    "cf": "CAF", "ss": "SSD", "gq": "GNQ", "gn": "GIN", "sl": "SLE",
    "lr": "LBR", "ci": "CIV", "gh2": "GHA", "bs2": "BHS", "fj": "FJI",
    "pg": "PNG", "nc": "NCL", "mu": "MUS", "sc": "SYC", "mv": "MDV",
    "bt": "BTN", "bn": "BRN", "tl": "TLS", "pg2": "PNG",
}


@lru_cache(maxsize=1)
def _countries():
    """[(iso3, name_lower, rings, centroid)] — world.geo.json'dan."""
    with open(GEOJSON, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for ft in data.get("features", []):
        iso3 = (ft.get("id") or "").upper()
        name = (ft.get("properties", {}).get("name") or "").lower()
        geom = ft.get("geometry") or {}
        rings = []
        if geom.get("type") == "Polygon":
            rings = [geom["coordinates"][0]]
        elif geom.get("type") == "MultiPolygon":
            rings = [p[0] for p in geom["coordinates"]]
        if not rings:
            continue
        xs = [c[0] for r in rings for c in r]
        ys = [c[1] for r in rings for c in r]
        cen = (sum(xs) / len(xs), sum(ys) / len(ys))
        out.append((iso3, name, rings, cen))
    return out


def resolve(target):
    """'NL' / 'netherlands' / 'BE-NL' -> [iso3, ...] (ko'p bo'lishi mumkin)."""
    out, seen = [], set()
    for part in str(target or "").replace("+", "-").split("-"):
        p = part.strip().lower()
        if not p:
            continue
        iso3 = None
        if len(p) == 2 and p in ISO2_TO_ISO3:
            iso3 = ISO2_TO_ISO3[p]
        elif len(p) == 3:
            iso3 = p.upper()
        else:
            for (i3, nm, _, _) in _countries():
                if nm and (p == nm or p in nm or nm in p):
                    iso3 = i3
                    break
        if iso3 and iso3 in {c[0] for c in _countries()} and iso3 not in seen:
            out.append(iso3)
            seen.add(iso3)
    return out


def _flag_png(iso3, work_dir, w=760):
    """ISO3 -> bayroq PNG (assets/flags/<iso2>.svg, rsvg-convert)."""
    iso2 = next((k for k, v in ISO2_TO_ISO3.items() if v == iso3), None)
    if not iso2:
        return None
    svg = os.path.join(FLAG_DIR, iso2 + ".svg")
    if not os.path.exists(svg):
        return None
    d = os.path.join(work_dir, "flags")
    os.makedirs(d, exist_ok=True)
    png = os.path.join(d, iso2 + ".png")
    if not os.path.exists(png):
        r = subprocess.run(["rsvg-convert", "-w", str(w), "-o", png, svg],
                           capture_output=True, timeout=30)
        if r.returncode != 0 or not os.path.exists(png):
            return None
    return png


@lru_cache(maxsize=1)
def _raster():
    return Image.open(NE2).convert("RGB")


def _window(z):
    """zoom_level -> (w_deg, h_deg) kadr oynasi (equirect)."""
    wd = 160.0 * 0.62 ** max(0, z - 2)
    wd = min(wd, 360.0)
    return wd, min(wd * H / W, 175.0)


def _raster_crop(lon, lat, wd, hd):
    """NE2'dan equirect crop (x wrap, y clamp) -> W x H."""
    cy = (90.0 - lat) / 180.0 * RPX_H
    wpx, hpx = wd * PX_DEG, hd * PX_DEG
    y0, y1 = int(max(0, cy - hpx / 2)), int(min(RPX_H, cy + hpx / 2))
    cx = ((lon + 180.0) % 360.0) / 360.0 * RPX_W
    xa = int(cx - wpx / 2) % RPX_W
    xb = int(cx + wpx / 2) % RPX_W
    if xb >= xa:
        img = _raster().crop((xa, y0, xb, y1))
    else:  # 180° chizig'idan o'tadi — ikki qismni tikamiz
        left = _raster().crop((xa, y0, RPX_W, y1))
        right = _raster().crop((0, y0, xb, y1))
        img = Image.new("RGB", (left.width + right.width, y1 - y0), NAVY)
        img.paste(left, (0, 0))
        img.paste(right, (left.width, 0))
    return img.resize((W, H), Image.LANCZOS)


def _in_window(rings, win):
    """Poligon kadr oynasi bilan kesishadimi (qo'pol bbox testi)."""
    lo0, hi1, wd, hd = win
    lo1, hi0 = 90.0, -90.0
    for r in rings:
        for (x, y) in r:
            if lo0 <= x <= lo0 + wd and lo1 >= y >= hi0 - hd:
                return True
    return False


ESRI_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}")
ESRI_CACHE = os.path.join(ASSETS, "esri_cache")


def _esri_base(lon, lat, wd, hd):
    """v10.1: haqiqiy SATELLITE fon (Esri World Imagery tiles).

    -> (RGB Image WxH [atributsiya bilan], to_px) yoki None (tarmoq yo'q).
    to_px WEB MERCATOR — davlat poligonlari satellite bilan aniq mos
    tushadi. Region oldin hisoblanadi, tile'lar region bo'yicha olinadi
    (markaz ANIQ canvas markazida). Tiles diskda keshlanadi."""
    import math as _m
    try:
        import requests
    except ImportError:
        return None

    def _tx(lo, n):
        return (lo + 180.0) / 360.0 * n

    def _ty(la, n):
        l = _m.radians(max(-85.05, min(85.05, la)))
        return (1.0 - _m.log(_m.tan(l) + 1.0 / _m.cos(l)) / _m.pi) / 2.0 * n

    # tile zoom: region <= ~5x9 tile
    z = 2
    for cand in range(2, 14):
        n = 2 ** cand
        ls = _tx(lon + wd / 2, n) - _tx(lon - wd / 2, n)
        ts = _ty(lat - hd / 2, n) - _ty(lat + hd / 2, n)
        rwt = max(ls, ts * W / H)
        if rwt <= 5.0 and rwt * H / W <= 9.0:
            z = cand
        else:
            break
    n = 2 ** z
    # region: markaz atrofida, W:H nisbatda
    cxt, cyt = _tx(lon, n), _ty(lat, n)
    ls = _tx(lon + wd / 2, n) - _tx(lon - wd / 2, n)
    ts = _ty(lat - hd / 2, n) - _ty(lat + hd / 2, n)
    rwt = max(ls, ts * W / H)
    rht = rwt * H / W
    rw, rh = rwt * 256, rht * 256
    ix0 = int(_m.floor(cxt - rwt / 2 - 0.02))
    ix1 = int(_m.ceil(cxt + rwt / 2 + 0.02))
    iy0 = int(_m.floor(cyt - rht / 2 - 0.02))
    iy1 = int(_m.ceil(cyt + rht / 2 + 0.02))
    ix0, ix1 = max(0, ix0), min(n, ix1)
    iy0, iy1 = max(0, iy0), min(n, iy1)
    if (ix1 - ix0) * (iy1 - iy0) > 60 or ix1 - ix0 < 1 or iy1 - iy0 < 1:
        return None
    try:
        os.makedirs(ESRI_CACHE, exist_ok=True)
        canvas = Image.new("RGB", ((ix1 - ix0) * 256, (iy1 - iy0) * 256),
                           (10, 14, 24))
        sess = requests.Session()
        sess.headers["User-Agent"] = "shorts-pipeline/1.0"
        for x in range(ix0, ix1):
            for y in range(iy0, iy1):
                f = os.path.join(ESRI_CACHE, f"{z}_{x}_{y}.jpg")
                if not os.path.exists(f):
                    r = sess.get(ESRI_URL.format(z=z, x=x, y=y), timeout=12)
                    if r.status_code != 200 or len(r.content) < 400:
                        return None
                    with open(f, "wb") as fh:
                        fh.write(r.content)
                try:
                    canvas.paste(Image.open(f).convert("RGB"),
                                 ((x - ix0) * 256, (y - iy0) * 256))
                except Exception:
                    return None
    except Exception:
        return None

    # aniq region kesish (markaz canvas markazida — kafolatlangan)
    px0 = (cxt - rwt / 2 - ix0) * 256
    py0 = (cyt - rht / 2 - iy0) * 256
    img = canvas.crop((int(round(px0)), int(round(py0)),
                       int(round(px0 + rw)), int(round(py0 + rh)))
                      ).resize((W, H), Image.LANCZOS)

    sx, sy = W / rw, H / rh

    def to_px(lo, la):
        return (((_tx(lo, n) - ix0) * 256 - px0) * sx,
                ((_ty(la, n) - iy0) * 256 - py0) * sy)

    # atributsiya (Esri litsenziyasi — O'CHIRILMASIN)
    try:
        from PIL import ImageFont
        d = ImageDraw.Draw(img, "RGBA")
        fnt = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
        d.text((W - 30, H - 44), "Imagery \u00a9 Esri", font=fnt,
               fill=(255, 255, 255, 130), anchor="rs")
    except Exception:
        pass
    return img, to_px


def _proj(win):
    lo0, hi1, wd, hd = win          # hi1 = shimoliy lat
    def to_px(lon, lat):
        x = (lon - lo0) / wd * W
        y = (hi1 - lat) / hd * H
        return x, y
    return to_px


def compose_map(cam, iso_codes, work_dir):
    """cam: {lat, lon, zoom_level, motion} -> base PNG + bayroq qatlamlari.

    Qaytaradi: {"base": png, "fills": {iso2: png}, "zs": .., "ze": ..,
                "to_px": fn, "centroids": {iso2: (x, y)}, "mode": "raster"/"vector"}
    """
    z = max(3, min(12, int(cam.get("zoom_level", 5))))
    lat = max(-84.0, min(84.0, float(cam.get("lat", 0))))
    lon = float(cam.get("lon", 0))
    wd, hd = _window(z)
    # v10.2 (user #3): bias — fokus nuqta kadrda 0.35H'da tursin (subtitr
    # ustida markazda emas). Oyna markazi janubga suriladi; to_px o'sha
    # oynadan -> pin/label ham fokus bilan birga ko'tariladi.
    bias = max(0.0, min(0.4, float(cam.get("bias") or 0.0)))
    lat_c = lat - bias * hd
    win = (lon - wd / 2, lat_c + hd / 2, wd, hd)
    os.makedirs(work_dir, exist_ok=True)

    # v10.1: haqiqiy satellite (Esri) — HAR zoom'da, mercator proyeksiya.
    # Tarmoq yo'q -> NE2 raster (davlat darajasi) -> vektor (navy).
    esri = _esri_base(lon, lat_c, wd, hd)
    mode = "esri" if esri is not None else None
    if esri is not None:
        base, to_px = esri
        use_raster = True
        print(f"[geo] xarita z={z} (esri satellite, bias={bias})")
    else:
        to_px = _proj(win)
        use_raster = (wd * PX_DEG) >= W / 2.0        # upscale <= 2x
        base = _raster_crop(lon, lat_c, wd, hd) if use_raster else None
    if esri is None and not use_raster:
        base = Image.new("RGB", (W, H), NAVY)
        d = ImageDraw.Draw(base, "RGBA")
        # graticule (5°/1°)
        step = 5.0 if wd > 20 else 1.0
        lo0, hi1 = win[0], win[1]
        lonx = math.floor(lo0 / step) * step
        while lonx <= lo0 + wd:
            x = to_px(lonx, 0)[0]
            d.line([(x, 0), (x, H)], fill=(255, 255, 255, 14), width=1)
            lonx += step
        laty = math.floor((hi1 - hd) / step) * step
        while laty <= hi1:
            y = to_px(0, laty)[1]
            d.line([(0, y), (W, y)], fill=(255, 255, 255, 14), width=1)
            laty += step
        # quruq fill (ochroq navy)
        for (iso3, _nm, rings, _c) in _countries():
            if not _in_window(rings, win):
                continue
            for r in rings:
                pts = [to_px(x, y) for (x, y) in r]
                if len(pts) > 2:
                    d.polygon(pts, fill=NAVY_LIGHT + (255,))

    # chegaralar (oq, ustidan)
    d2 = ImageDraw.Draw(base, "RGBA")
    bw = 2 if use_raster else 3
    for (iso3, _nm, rings, _c) in _countries():
        if not _in_window(rings, win):
            continue
        for r in rings:
            pts = [to_px(x, y) for (x, y) in r]
            if len(pts) > 1:
                d2.line(pts, fill=(255, 255, 255, 230), width=bw)

    out_base = os.path.join(work_dir, f"map_{abs(hash((lat, lon, z))) % 10**8}.png")
    base.save(out_base)

    # bayroq-fill qatlamlari (har biri ALOHIDA RGBA — so'z vaqtida reveal)
    fills, centroids = {}, {}
    for iso2 in (iso_codes or [])[:2]:
        iso3s = resolve(iso2)
        if not iso3s:
            print(f"[geo] '{iso2}' topilmadi")
            continue
        iso3 = iso3s[0]
        fp = _flag_png(iso3, work_dir)
        flag = Image.open(fp).convert("RGBA") if fp else None
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        for (c_iso3, _nm, rings, cen) in _countries():
            if c_iso3 != iso3 or not _in_window(rings, win):
                continue
            for r in rings:
                pts = [to_px(x, y) for (x, y) in r]
                if len(pts) <= 2:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                # kadrdan butunlay tashqaridagi ringlar (dengiz orti, va h.k.)
                if (max(xs) < -40 or min(xs) > W + 40
                        or max(ys) < -40 or min(ys) > H + 40):
                    continue
                x0, y0 = min(xs), min(ys)
                bw, bh = max(xs) - x0, max(ys) - y0
                if bw < 3 or bh < 3:
                    continue
                if flag:
                    # faqat KO'RINADIGAN qism (canvas+margin); bbox to'liq
                    # mamlakat bo'lishi mumkin (coarse geojson) -> OIM oldini olish
                    vx0, vy0 = max(x0, -200.0), max(y0, -200.0)
                    vx1 = min(x0 + bw, W + 200.0)
                    vy1 = min(y0 + bh, H + 200.0)
                    if vx1 - vx0 >= 2 and vy1 - vy0 >= 2:
                        s = min(1.0, 4096.0 / max(bw, bh))
                        fw, fh = max(2, int(bw * s)), max(2, int(bh * s))
                        f = flag.resize((fw, fh))
                        ox, oy = int((vx0 - x0) * s), int((vy0 - y0) * s)
                        ow = max(2, min(fw - ox, int((vx1 - vx0) * s) + 2))
                        oh = max(2, min(fh - oy, int((vy1 - vy0) * s) + 2))
                        fvis = f.crop((ox, oy, ox + ow, oy + oh))
                        mask = Image.new("L", layer.size, 0)
                        ImageDraw.Draw(mask).polygon(pts, fill=255)
                        alpha = fvis.split()[3].point(lambda a: int(a * 0.58))
                        fvis.putalpha(alpha)
                        layer.paste(
                            fvis, (int(vx0), int(vy0)),
                            mask.crop((int(vx0), int(vy0),
                                       int(vx0) + ow, int(vy0) + oh)))
                dl.line(pts + [pts[0]], fill=(255, 255, 255, 255), width=3)
            centroids[iso2] = to_px(cen[0], cen[1])
        if centroids.get(iso2):
            lp = os.path.join(work_dir, f"fill_{iso2}_{abs(hash((lat, lon, z))) % 10**8}.png")
            layer.save(lp)
            fills[iso2] = lp

    motion = cam.get("motion", "zoom_in")
    zs, ze = (1.42, 1.02) if motion == "zoom_out" else (1.02, 1.42)
    print(f"[geo] xarita z={z} ({mode or ('raster' if use_raster else 'vektor')}), "
          f"{len(fills)} bayroq-qatlam, {os.path.basename(out_base)}")
    return {"base": out_base, "fills": fills, "zs": zs, "ze": ze,
            "to_px": to_px, "centroids": centroids, "win": win,
            "mode": mode or ("raster" if use_raster else "vector")}


def country_layer(iso_target, style, work_dir, ctx, tag=""):
    """highlight (cyan glow) / line (qalin sariq chegara) qatlami."""
    iso3s = resolve(iso_target)
    if not iso3s:
        return None
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    to_px = ctx["to_px"]
    for (iso3, _nm, rings, _c) in _countries():
        if iso3 not in iso3s:
            continue
        for r in rings:
            pts = [to_px(x, y) for (x, y) in r]
            if len(pts) <= 2:
                continue
            if style == "highlight":
                d.polygon(pts, fill=CYAN + (70,))
                d.line(pts + [pts[0]], fill=CYAN + (255,), width=5)
            else:  # line
                d.line(pts + [pts[0]], fill=YELLOW + (255,), width=9)
    if style == "highlight":
        layer = layer.filter(ImageFilter.GaussianBlur(6))
        layer2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d2 = ImageDraw.Draw(layer2)
        for (iso3, _nm, rings, _c) in _countries():
            if iso3 not in iso3s:
                continue
            for r in rings:
                pts = [to_px(x, y) for (x, y) in r]
                if len(pts) > 2:
                    d2.polygon(pts, fill=CYAN + (60,))
                    d2.line(pts + [pts[0]], fill=CYAN + (255,), width=4)
        layer = Image.alpha_composite(layer, layer2)
    out = os.path.join(work_dir, f"lyr_{style}_{tag}_{abs(hash(iso_target)) % 10**8}.png")
    layer.save(out)
    return out


def pin_png(work_dir, color=YELLOW, label=""):
    """Pin + ixtiyoriy shahar nomi yozuvi ("Canberra") — joy belgilash.

    Label har xil bo'lsa har biri alohida fayl (kesh kaliti label'da)."""
    import re as _re
    safe = _re.sub(r"[^A-Za-z0-9]+", "", str(label))[:18]
    out = os.path.join(work_dir, f"pin_{safe}.png" if safe else "pin.png")
    if os.path.exists(out):
        return out
    S = 512
    Wc = 512 + (26 * (len(safe) + 1) if safe else 0)   # label uchun joy
    img = Image.new("RGBA", (max(S, Wc), S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([(96, 16), (416, 336)], fill=color + (255,), outline=(0, 0, 0, 255), width=12)
    d.polygon([(196, 300), (316, 300), (256, 480)], fill=color + (255,),
              outline=(0, 0, 0, 255))
    d.ellipse([(196, 116), (316, 236)], fill=(255, 255, 255, 230))
    if safe:
        try:
            from PIL import ImageFont
            fnt = ImageFont.truetype(
                "/usr/share/fonts/truetype/montserrat/"
                "Montserrat-ExtraBold.ttf", 54)
            d.text((452, 120), str(label)[:18],
                   font=fnt, fill=(255, 255, 255, 255),
                   stroke_width=8, stroke_fill=(0, 0, 0, 255))
        except Exception:
            pass
    img.save(out)
    return out


def label_png(name, work_dir):
    """v10: davlat nomi yorlig'i — kvadrat kanvasda markazda kichik
    qora lavha + oq qalin matn (screen-layer 260px scale uchun KVADRAT)."""
    import re as _re
    txt = _re.sub(r"[^A-Za-z0-9 .'-]", "", str(name or "")).strip()[:22]
    if not txt:
        return None
    key = _re.sub(r"[^A-Za-z0-9]+", "_", txt).strip("_")
    out = os.path.join(work_dir, f"lbl_{key}.png")
    if os.path.exists(out):
        return out
    try:
        from PIL import ImageFont
        S = 512
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        fnt = ImageFont.truetype(
            "/usr/share/fonts/truetype/montserrat/Montserrat-ExtraBold.ttf", 72)
        tw = int(d.textlength(txt.upper(), font=fnt))
        w, h = min(508, tw + 64), 118
        x0, y0 = (S - w) // 2, (S - h) // 2
        d.rounded_rectangle([x0, y0, x0 + w - 1, y0 + h - 1], radius=22,
                            fill=(10, 12, 18, 222),
                            outline=(255, 255, 255, 80), width=3)
        d.text((x0 + 32, y0 + 22), txt.upper(), font=fnt,
               fill=(255, 255, 255, 255))
        img.save(out)
        return out
    except Exception:
        return None


def point_on_land(lon, lat):
    """(lon, lat) QAYSI DIR davlatda bo'lsa ham — quruqlikda.
    Chevron: chegara bo'yidagi exclave (Büsingen kabi) NE geometriyasida
    yo'qolishi mumkin; 'target davlatda emas' -> centroid qaytarish
    noto'g'ri. Faqat OKEAN bo'lsa demote qilamiz."""
    for (_iso3, _nm, rings, _c) in _countries():
        for r in rings:
            inside = False
            n = len(r)
            for i in range(n):
                (x1, y1), (x2, y2) = r[i], r[(i + 1) % n]
                if (y1 > lat) != (y2 > lat):
                    xint = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
                    if lon < xint:
                        inside = not inside
            if inside:
                return True
    return False


def point_in_country(iso_target, lon, lat):
    """(lon, lat) nuqta mamlakat poligonida (quruqlikda) yoki yo'qmi.
    Pin okeanga tushib qolmasligi uchun (ray-casting)."""
    iso3s = resolve(iso_target)
    if not iso3s:
        return None                     # bilmaymiz
    inside = False
    for (iso3, _nm, rings, _c) in _countries():
        if iso3 not in iso3s:
            continue
        for r in rings:
            n = len(r)
            for i in range(n):
                (x1, y1), (x2, y2) = r[i], r[(i + 1) % n]
                if (y1 > lat) != (y2 > lat):
                    xint = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
                    if lon < xint:
                        inside = not inside
    return inside


def flag_color(iso2, work_dir=None):
    """Bayroqning dominant rangi (subtitr highlight uchun)."""
    iso3s = resolve(iso2)
    if not iso3s:
        return None
    fp = _flag_png(iso3s[0], work_dir or os.path.join(ROOT, "work"))
    if not fp:
        return None
    im = Image.open(fp).convert("RGBA").resize((32, 32))
    best, n = None, 0
    counts = {}
    for (r, g, b, a) in im.getdata():
        if a < 128 or max(r, g, b) < 60 or (r > 235 and g > 235 and b > 235):
            continue
        mx, mn = max(r, g, b), min(r, g, b)
        if mx - mn < 25 and mx < 150:
            continue
        k = (r // 24 * 24, g // 24 * 24, b // 24 * 24)
        counts[k] = counts.get(k, 0) + 1
    for c, k in counts.items():
        if k > n:
            best, n = c, k
    return best
