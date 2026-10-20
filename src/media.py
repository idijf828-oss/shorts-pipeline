"""4-qadam (media): sahna uchun video topish.

Fallback zanjiri (video hech qachon muvaffaqiyatsiz bo'lmaydi):
  1) Pexels API (portrait/vertical kliplar)
  2) Pixabay API
  3) config'dagi generic_queries (umumiy mavzular)
  4) Pillow bilan generated image card + ffmpeg zoom (Ken Burns)

Ikkalasi ham bepul tier. Pexels: 200 so'rov/soat, 20 000/oy.
Pixabay: 100 so'rov/60 soniya.
ESLATMA (2026-10): Pexels YANGI API kalitlarini vaqtincha
to'xtatgan - kalit olmagan bo'lsangiz Pixabay'dan foydalaning
(kod ikkalasini ham biladi).
"""
import os
import random

from PIL import Image, ImageDraw, ImageFont
from src.config import ROOT
from src.net import session

PEXELS = "https://api.pexels.com/videos/search"
PIXABAY = "https://pixabay.com/api/videos/"


# ---------- Pexels ----------
def _pexels(cfg, query):
    key = cfg["secrets"]["pexels_api_key"]
    if not key:
        return None
    try:
        r = session().get(
            PEXELS,
            headers={"Authorization": key},
            params={"query": query, "orientation": "portrait",
                    "size": "medium", "per_page": 6},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"[media] Pexels {r.status_code}: {r.text[:120]}")
            return None
        vids = r.json().get("videos", [])
        pool = [v for v in vids if v.get("width", 0) >= 720] or vids
        if not pool:
            return None
        # deterministik tanlash -> natija barqaror
        random.seed(query)
        v = pool[random.randrange(len(pool))]
        files = sorted(v["video_files"],
                       key=lambda f: -(f.get("width", 0) * f.get("height", 0)))
        portrait = [f for f in files if f["height"] >= f["width"]]
        return (portrait or files)[0]["link"]
    except Exception as e:
        print(f"[media] Pexels xatosi: {e}")
        return None


# ---------- Pixabay ----------
def _pixabay(cfg, query):
    key = cfg["secrets"]["pixabay_api_key"]
    if not key:
        return None
    try:
        r = session().get(PIXABAY, params={
            "key": key, "q": query, "orientation": "vertical",
            "per_page": 5, "safesearch": "true"}, timeout=20)
        if r.status_code != 200:
            print(f"[media] Pixabay {r.status_code}")
            return None
        hits = r.json().get("hits", [])
        if not hits:
            return None
        vids = hits[0].get("videos", {})
        for k in ("small", "medium", "large"):
            if k in vids and vids[k].get("url"):
                return vids[k]["url"]
        return None
    except Exception as e:
        print(f"[media] Pixabay xatosi: {e}")
        return None


def _download(url, dest):
    try:
        with session().get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        return os.path.getsize(dest) > 20_000
    except Exception as e:
        print(f"[media] yuklab olish xatosi: {e}")
        return False


# ---------- Rasm kartasi (oxirgi fallback) ----------
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _font(size):
    for p in _FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def make_card(text, subtext, dest):
    """Generatsiya qilingan rasm kartasi (gradient fon + matn)."""
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (18, 18, 26))
    d = ImageDraw.Draw(img)
    for y in range(H):  # oddiy gradient
        c = int(18 + 34 * y / H)
        d.line([(0, y), (W, y)], fill=(c // 3, c // 3, c))
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) < 26:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    body = "\n".join(lines)
    d.multiline_text((W // 2, H // 2 - 60), body, font=_font(92),
                     fill="white", anchor="mm", align="center", spacing=18)
    if subtext:
        d.text((W // 2, H // 2 + 220), subtext, font=_font(54),
               fill=(255, 214, 0), anchor="mm")
    img.save(dest, quality=92)
    return dest


# ---------- Boshqaruvchi ----------
def fetch_scene_media(cfg, scene, dest):
    """Sahna uchun media fayl topadi. Hech bo'lmasa kartani qaytaradi."""
    queries = [scene["pexels_query"]] + cfg["sources"]["generic_queries"]
    for q in queries:
        for finder in (_pexels, _pixabay):
            url = finder(cfg, q)
            if url and _download(url, dest):
                print(f"[media] topildi ({finder.__name__}): {q}")
                return dest
    # oxirgi variant: generated image card
    card = dest.rsplit(".", 1)[0] + ".png"
    make_card(scene.get("overlay", "")[:120],
              scene.get("badge", ""), card)
    print("[media] clip topilmadi -> rasm kartasi ishlatildi")
    return card


def fetch_all(cfg, scenes):
    tmp = cfg["_paths"]["work"]
    os.makedirs(tmp, exist_ok=True)
    out = []
    for i, sc in enumerate(scenes):
        dest = os.path.join(tmp, f"scene_{i:02d}_media.bin")
        out.append(fetch_scene_media(cfg, sc, dest))
    return out
