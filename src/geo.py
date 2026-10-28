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


# V2-2: light rejim uchun davlat ranglari (iso3 -> RGB)
_FLAG_TINT = {
    "USA": (90, 120, 180), "CAN": (200, 60, 60), "MEX": (70, 130, 90),
    "DEU": (200, 170, 80), "CHE": (200, 60, 60), "AUT": (200, 200, 210),
    "FRA": (90, 110, 180), "GBR": (140, 150, 180), "ESP": (200, 130, 70),
    "ITA": (110, 170, 110), "RUS": (140, 150, 180), "CHN": (200, 80, 80),
    "JPN": (225, 225, 230), "IND": (200, 130, 90), "BRA": (130, 180, 110),
    "AUS": (110, 150, 200), "NLD": (200, 140, 90), "BEL": (200, 200, 90),
    "LIE": (200, 90, 90), "ZAF": (130, 170, 110), "EGY": (200, 170, 90),
    "MAR": (200, 90, 90), "DZA": (130, 160, 110), "NAM": (150, 170, 130),
    "KAZ": (120, 180, 200), "UZB": (110, 180, 200), "KGZ": (200, 130, 90),
    "TJK": (150, 150, 170), "TKM": (200, 140, 90), "AFG": (160, 170, 130),
    "PAK": (130, 160, 110), "IRN": (130, 160, 110), "TUR": (200, 90, 90),
    "GRC": (110, 170, 200), "PRT": (130, 160, 110), "POL": (200, 200, 90),
    "CZE": (110, 170, 200), "SVK": (200, 200, 90), "HUN": (200, 200, 90),
    "ROU": (200, 140, 90), "BGR": (200, 140, 90), "SRB": (200, 90, 90),
    "HRV": (200, 200, 90), "SVN": (110, 170, 200), "MNE": (200, 90, 90),
    "MKD": (200, 90, 90), "ALB": (200, 90, 90), "BIH": (110, 170, 200),
    "LUX": (110, 170, 200), "DNK": (200, 90, 90), "SWE": (90, 130, 200),
    "NOR": (90, 130, 200), "FIN": (110, 170, 200), "ISL": (90, 130, 200),
    "IRL": (130, 170, 110), "EST": (110, 170, 200), "LVA": (200, 200, 90),
    "LTU": (150, 170, 130), "BLR": (150, 170, 130), "UKR": (200, 140, 90),
    "MDA": (150, 170, 130), "ARM": (200, 140, 90), "AZE": (110, 170, 200),
    "GEO": (200, 200, 90), "CYP": (200, 170, 80), "MLT": (200, 200, 90),
    "SMR": (110, 170, 200), "VAT": (200, 170, 80), "MCO": (200, 170, 80),
    "AND": (110, 170, 200),
}


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
    fills, centroids, fills_area, fills_light = {}, {}, {}, set()
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
        # v11 (V2-2): davlatning oynadagi poligon maydoni — >35% yoki
        # <2% bo'lsa bayroq o'rniga yupqa kontur + yengil to'ldirish.
        # (V2: bayroq >35% ekran bo'lmasin; kichik joyda bayroq
        # o'qilmaydi — davlat rangi bilan ajralib turadi.)
        def _clip_rect(pts):
            # Sutherland-Hodgman: poligonni canvas rect'ga klip (dunyo
            # bo'ylab cho'zilgan davlatlar maydoni 1204% chiqmasin)
            def clip_edge(poly, keep, inter):
                out = []
                if not poly:
                    return out
                for k in range(len(poly)):
                    cur, prev = poly[k], poly[k - 1]
                    kc, kp = keep(cur), keep(prev)
                    if kc:
                        if not kp:
                            out.append(inter(prev, cur))
                        out.append(cur)
                    elif kp:
                        out.append(inter(prev, cur))
                return out
            X0, Y0, X1, Y1 = -160.0, -160.0, W + 160.0, H + 160.0
            p = pts
            p = clip_edge(p, lambda q: q[0] >= X0,
                          lambda a, b: (X0, a[1] + (b[1] - a[1])
                                        * (X0 - a[0]) / (b[0] - a[0])))
            p = clip_edge(p, lambda q: q[0] <= X1,
                          lambda a, b: (X1, a[1] + (b[1] - a[1])
                                        * (X1 - a[0]) / (b[0] - a[0])))
            p = clip_edge(p, lambda q: q[1] >= Y0,
                          lambda a, b: (a[0] + (b[0] - a[0]) * (Y0 - a[1])
                                        / (b[1] - a[1]), Y0))
            p = clip_edge(p, lambda q: q[1] <= Y1,
                          lambda a, b: (a[0] + (b[0] - a[0]) * (Y1 - a[1])
                                        / (b[1] - a[1]), Y1))
            return p

        _area = 0.0
        for (c_a3, _n2, r_a, _c2) in _countries():
            if c_a3 != iso3:
                continue
            for rr in r_a:
                _pts = _clip_rect([to_px(x, y) for (x, y) in rr])
                if len(_pts) >= 3:
                    _s2 = 0.0
                    for _i2 in range(len(_pts)):
                        _x1, _y1 = _pts[_i2]
                        _x2, _y2 = _pts[(_i2 + 1) % len(_pts)]
                        _s2 += _x1 * _y2 - _x2 * _y1
                    _area += abs(_s2) / 2.0
        area_ratio = _area / float(W * H)
        light_mode = area_ratio > 0.35 or area_ratio < 0.02
        fills_area[iso2] = round(area_ratio, 3)
        if light_mode:
            fills_light.add(iso2)
        for (c_iso3, _nm, rings, cen) in _countries():
            if c_iso3 != iso3 or not _in_window(rings, win):
                continue
            _tint_rings = []
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
                        # v13.5 (user #2): flag nusxasi CANVAS masshtabida
                        # yopishtiriladi. Eski kodda s<1 (ulkan davlat:
                        # Xitoy/Rossiya z7+) bo'lganda kichraytirilgan
                        # flag canvas'ga 1:1 yopishilib, ko'rinadigan
                        # hududning faqat bir qismini qoplagan — poligon
                        # ichida to'rtburchak kesilar edi (Badaling
                        # 00:14-00:18: qizil 81-86% to'rtburchak,
                        # chap-tepa burchak).
                        cw, ch = max(2, int(vx1 - vx0) + 2), \
                            max(2, int(vy1 - vy0) + 2)
                        kx = min(fw - ox, max(2, int(cw * s) + 1))
                        ky = min(fh - oy, max(2, int(ch * s) + 1))
                        fvis = f.crop((ox, oy, ox + kx, oy + ky))
                        if fvis.size != (cw, ch):
                            fvis = fvis.resize((cw, ch), Image.LANCZOS)
                        mask = Image.new("L", layer.size, 0)
                        ImageDraw.Draw(mask).polygon(pts, fill=255)
                        a0 = 0.30 if light_mode else 0.75
                        alpha = fvis.split()[3].point(
                            lambda a: int(a * a0))
                        fvis.putalpha(alpha)
                        layer.paste(
                            fvis, (int(vx0), int(vy0)),
                            mask.crop((int(vx0), int(vy0),
                                       int(vx0) + cw, int(vy0) + ch)))
                # v13.5: har ring uchun oq kontur (eski kodda faqat
                # OXIRGI ring chizilar edi — pts loopdan oqib kelardi)
                dl.line(pts + [pts[0]], fill=(255, 255, 255, 255),
                        width=6 if light_mode else 3)
                if light_mode:
                    _tint_rings.append(pts)
            if light_mode and _tint_rings:
                # V2-2: kichik joy / juda katta davlat — davlat rangi
                # yengil to'ldirish + qalin oq kontur (bayroq emas).
                # v13.5: BARCHA ko'rinadigan ringlar bo'yacha (eski:
                # faqat oxirgi ring).
                fill_c = _FLAG_TINT.get(iso3, (120, 170, 255))
                mask2 = Image.new("L", layer.size, 0)
                dm2 = ImageDraw.Draw(mask2)
                for _tp in _tint_rings:
                    dm2.polygon(_tp, fill=70)
                layer.paste(Image.new("RGBA", layer.size,
                                      fill_c + (255,)), (0, 0), mask2)
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
            "fills_area": fills_area,
            "fills_light": fills_light,
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
    qora lavha + oq qalin matn (screen-layer 260px scale uchun KVADRAT).
    v13.5 (user #2): matn HECH QACHON kesilmaydi — uzun nomda shrift
    avtomatik kichrayadi ("KAZAKHSTAN" 72px->60px), quti matnga mos
    kenglikda (width: auto, padding 32px)."""
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
        # v13.5: shrift narvoni — matn 444px (508-64) ga sig'guncha
        # kichrayadi; sig'sa 72px qoladi. Kesilish imkonsiz.
        size = 72
        while size > 40:
            fnt = ImageFont.truetype(
                "/usr/share/fonts/truetype/montserrat/"
                "Montserrat-ExtraBold.ttf", size)
            tw = int(d.textlength(txt.upper(), font=fnt))
            if tw <= 444:
                break
            size -= 4
        fnt = ImageFont.truetype(
            "/usr/share/fonts/truetype/montserrat/"
            "Montserrat-ExtraBold.ttf", size)
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


def country_bbox(target):
    """v13.5: resolve(target) -> (top_lat, bottom_lat, west_lon, east_lon)
    yoki None. Lint: davlat tepasi kadrdan kesilmasin tekshiruvi."""
    iso3s = resolve(target)
    if not iso3s:
        return None
    tops, bottoms, wests, easts = [], [], [], []
    for (i3, _nm, rings, _c) in _countries():
        if i3 not in iso3s:
            continue
        for r in rings:
            for (x, y) in r:
                tops.append(y); bottoms.append(y)
                wests.append(x); easts.append(x)
    if not tops:
        return None
    return (max(tops), min(bottoms), min(wests), max(easts))


def scene_focus(cam, events):
    """v13.5 (user #1): sahna FOKUS nuqtasi — pin/label event koordinati
    (label'da geokod yo'q bo'lsa target davlat centroidi), kamera oynasining
    30% radiusida bo'lsa. Aks holda None (fokus = kamera markazi).
    main.py (render) VA script_gen (lint) bir xil natijani oladi."""
    try:
        cam = cam or {}
        z = max(3, min(12, int(cam.get("zoom_level", 5))))
        wd, hd = _window(z)
        lat = float(cam.get("lat", 0))
        lon = float(cam.get("lon", 0))
        for ev in (events or []):
            k = str(ev.get("type") or "")
            if k not in ("pin", "label"):
                continue
            flon, flat = None, None
            if ev.get("lat") is not None and ev.get("lon") is not None:
                try:
                    flat, flon = float(ev["lat"]), float(ev["lon"])
                except Exception:
                    pass
            if flon is None:
                c = country_centroid(str(ev.get("target") or ""))
                if c:
                    flon, flat = c[0], c[1]
            if flon is None:
                continue
            if abs(flat - lat) <= 0.30 * hd and abs(flon - lon) <= 0.30 * wd:
                return flon, flat
    except Exception:
        pass
    return None


def _merc_y(lat, n):
    """Web-mercator Y (tile birlik): _esri_base _ty bilan bir xil."""
    l = math.radians(max(-85.05, min(85.05, lat)))
    return (1.0 - math.log(math.tan(l) + 1.0 / math.cos(l)) / math.pi) \
        / 2.0 * n


def _merc_inv_y(t, n):
    """_merc_y teskarisi (tile birlik -> lat)."""
    v = (1.0 - 2.0 * t / n) * math.pi
    return math.degrees(math.atan(math.sinh(v)))


def apply_focus(cam, events):
    """v13.5 (user #1): kamera oynasini FOKUS atrofida markazlaydi.

    Fokus (pin/label nuqtasi yoki kamera markazi) canvas (720, 960) ga,
    ya'ni ekranning 37.5% balandligiga tushadi (user: pin 35-40%).
    render.py zoompan shu nuqtaga anchor bo'ladi — zoom davomida fokus
    ekranda QOTIB TURADI (eski: markazga zoom + bias 0.22 -> yakuniy
    zoomda fokus ~19% ga chiqib, ob'ekt tepadan kesilardi).

    lat_c MERCATOR fazida yechiladi (_esri_base proyektsiyasi bilan
    bir xil fixed-point iteratsiya — chiziqli gradusda yechilsa z3-4
    keng oynalarda 300px gacha xato chiqardi).
    Qaytgan cam: lat/lon = OYNA MARKAZI, bias=0 (compose_map va
    project_point o'zgarmasdan ishlaydi)."""
    m = dict(cam or {})
    try:
        z = max(3, min(12, int(m.get("zoom_level", 5))))
        wd, hd = _window(z)
        f = scene_focus(m, events)
        flon, flat = f if f else (float(m.get("lon", 0)),
                                  float(m.get("lat", 0)))
        lat_c = flat - 0.125 * hd          # chiziqli boshlang'ich
        for _ in range(5):
            tz = 2
            for cand in range(2, 14):
                n = 2 ** cand
                ls = ((flon + wd / 2 + 180.0) / 360.0 * n
                      - (flon - wd / 2 + 180.0) / 360.0 * n)
                ts = _merc_y(lat_c - hd / 2, n) - _merc_y(lat_c + hd / 2, n)
                rwt = max(ls, ts * W / H)
                if rwt <= 5.0 and rwt * H / W <= 9.0:
                    tz = cand
                else:
                    break
            n = 2 ** tz
            ls = ((flon + wd / 2 + 180.0) / 360.0 * n
                  - (flon - wd / 2 + 180.0) / 360.0 * n)
            ts = _merc_y(lat_c - hd / 2, n) - _merc_y(lat_c + hd / 2, n)
            rht = max(ls, ts * W / H) * H / W
            lat_new = _merc_inv_y(_merc_y(flat, n) + 0.125 * rht, n)
            if abs(lat_new - lat_c) < 1e-7:
                lat_c = lat_new
                break
            lat_c = lat_new
        lat_c = max(-84.0, min(84.0, lat_c))
        m["lat"], m["lon"], m["bias"] = lat_c, flon, 0.0
        m["_focus"] = [round(flon, 6), round(flat, 6)]
    except Exception:
        m.setdefault("bias", 0.0)
    return m


def project_point(cam, lon, lat):
    """v13.4 (2026-10-28): kamera ostida nuqtaning (x, y) pikseli.

    Esri mercator matematikasining TARMOSIQ nusxasi (_esri_base'dan) —
    seed-lint uchun (CI'da doim esri proyeksiyasi ishlaydi)."""
    import math as _m

    def _tx(x, n):
        return (x + 180.0) / 360.0 * n

    def _ty(y, n):
        l = _m.radians(max(-85.05, min(85.05, y)))
        return (1.0 - _m.log(_m.tan(l) + 1.0 / _m.cos(l)) / _m.pi) / 2.0 * n

    z = max(3, min(12, int(cam.get("zoom_level", 5))))
    la = max(-84.0, min(84.0, float(cam.get("lat", 0))))
    lo = float(cam.get("lon", 0))
    wd, hd = _window(z)
    bias = max(0.0, min(0.4, float(cam.get("bias") or 0.0)))
    la_c = la - bias * hd
    tz = 2
    for cand in range(2, 14):
        n = 2 ** cand
        ls = _tx(lo + wd / 2, n) - _tx(lo - wd / 2, n)
        ts = _ty(la_c - hd / 2, n) - _ty(la_c + hd / 2, n)
        rwt = max(ls, ts * W / H)
        if rwt <= 5.0 and rwt * H / W <= 9.0:
            tz = cand
        else:
            break
    n = 2 ** tz
    cxt, cyt = _tx(lo, n), _ty(la_c, n)
    ls = _tx(lo + wd / 2, n) - _tx(lo - wd / 2, n)
    ts = _ty(la_c - hd / 2, n) - _ty(la_c + hd / 2, n)
    rwt = max(ls, ts * W / H)
    rht = rwt * H / W
    rw, rh = rwt * 256, rht * 256
    x = (_tx(lon, n) - cxt + rwt / 2) * 256 * W / rw
    y = (_ty(lat, n) - cyt + rht / 2) * 256 * H / rh
    return x, y


def country_centroid(target):
    """resolve(target) -> world.geo.json centroid (lon, lat) | None."""
    iso3s = resolve(target)
    if not iso3s:
        return None
    for (i3, _nm, _rings, cen) in _countries():
        if i3 in iso3s:
            return cen
    return None


def snap_to_land(lon, lat, max_deg=0.032, step=0.004):
    """Suvga tushgan nuqtani ENG YAQIN quruqlikka suradi (halqa qidiruv,
    ~400m qadam, ~3km gacha). Kichik yarimorollar NE 110m'da yo'q bo'lsa
    yordam beradi. -> (lon, lat) | None."""
    if point_on_land(lon, lat):
        return lon, lat
    n_rings = int(max_deg / step)
    for r in range(1, n_rings + 1):
        d = r * step
        for k in range(8 * r):
            ang = 2 * math.pi * k / (8 * r)
            lo2 = lon + d * math.cos(ang) / max(0.2, math.cos(math.radians(lat)))
            la2 = lat + d * math.sin(ang)
            if point_on_land(lo2, la2):
                return lo2, la2
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
