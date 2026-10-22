"""4-qadam (media): B-roll — must_contain validatsiyasi bilan.

Qoidalar:
  1) Har sahna uchun visual_query ro'yxati TARTIB BILAN: Pexels -> Pixabay.
  2) Klip faqat metadata (tags/pageURL) da must_contain so'zlaridan
     kamida bittasi bo'lsa qabul qilinadi (Pexels'da tags yo'q ->
     must bo'sh bo'lgandagina qabul).
  3) Watermark/logo/3D belgili klip rad etiladi (blacklist tokenlar).
  4) Hech biri mos kelmasa -> XARITA animatsiyasi (maps.py, zoompan).
     Oxirgi imkoniyat: gradient kartochka.
  5) Bir klip ikki marta ishlatilmaydi (run ichida + history'dagi id'lar).
  6) Har sahnaga 3 tagacha HAR XIL klip (kesishlar uchun).
"""
import os
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont
from src.net import session

PEXELS = "https://api.pexels.com/videos/search"
PIXABAY = "https://pixabay.com/api/videos/"

# Suvs belgisi/3D/render ishorasi bo'lgan klipni rad etish
BLACKLIST_TOKENS = {
    "logo", "watermark", "caption", "sign", "signboard", "banner",
    "placard", "overlay", "graphic", "animation", "render", "3d",
    "cgi", "text", "intro", "template",
}


# ---------- Qidiruv ----------
def _pexels_search(cfg, query):
    key = cfg["secrets"]["pexels_api_key"]
    if not key or key == "FAKE":
        return []
    try:
        r = session().get(
            PEXELS,
            headers={"Authorization": key},
            params={"query": query, "orientation": "portrait",
                    "size": "medium", "per_page": 10},
            timeout=20,
        )
    except Exception as e:
        print(f"[media] Pexels xatosi: {e}")
        return []
    if r.status_code != 200:
        print(f"[media] Pexels {r.status_code}")
        return []
    out = []
    for v in r.json().get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("link")]
        portrait = [f for f in files if (f.get("height") or 0) >= (f.get("width") or 0)]
        ranked = sorted(portrait or files,
                        key=lambda f: -((f.get("width") or 0) * (f.get("height") or 0)))
        if not ranked:
            continue
        # Pexels javobida tags yo'q — url/user nomi bilan cheklangan
        meta = " ".join(filter(None, [
            str(v.get("url", "")),
            str((v.get("user") or {}).get("name", "")),
        ]))
        out.append({"id": f"pex:{v['id']}", "link": ranked[0]["link"], "meta": meta})
    return out


def _pixabay_search(cfg, query):
    key = cfg["secrets"]["pixabay_api_key"]
    if not key or key == "FAKE":
        return []
    try:
        r = session().get(PIXABAY, params={
            "key": key, "q": query, "orientation": "vertical",
            "per_page": 10, "safesearch": "true"}, timeout=20)
    except Exception as e:
        print(f"[media] Pixabay xatosi: {e}")
        return []
    if r.status_code != 200:
        print(f"[media] Pixabay {r.status_code}")
        return []
    out = []
    for h in r.json().get("hits", []):
        vids = h.get("videos", {})
        link = None
        for k in ("medium", "small", "large", "tiny"):
            if k in vids and vids[k].get("url"):
                link = vids[k]["url"]
                break
        if not link:
            continue
        meta = " ".join(filter(None, [
            str(h.get("tags", "")),
            str(h.get("pageURL", "")),
        ]))
        out.append({"id": f"pix:{h['id']}", "link": link, "meta": meta})
    return out


def _accept(item, must, reject=()):
    text = (item["meta"] or "").lower()
    toks = set(re.split(r"[^a-z0-9#]+", text))
    if toks & BLACKLIST_TOKENS:
        return False
    # reject: noto'g'ri mavzu tokenlari (doc C1)
    if reject and any(r in text for r in reject if r):
        return False
    if must:
        return any(m in text for m in must)
    return True


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


# ---------- Oxirgi imkoniyat: rasm kartasi ----------
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/montserrat/Montserrat-ExtraBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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
    W, H = 1080, 1920
    img = Image.new("RGB", (W, H), (18, 18, 26))
    d = ImageDraw.Draw(img)
    for y in range(H):
        c = int(18 + 34 * y / H)
        d.line([(0, y), (W, y)], fill=(c // 3, c // 3, c))
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) < 24:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    d.multiline_text((W // 2, H // 2 - 60), "\n".join(lines), font=_font(88),
                     fill="white", anchor="mm", align="center", spacing=18)
    if subtext:
        d.text((W // 2, H // 2 + 220), subtext, font=_font(54),
               fill=(255, 214, 0), anchor="mm")
    img.save(dest, quality=92)
    return dest


# ---------- Boshqaruvchi ----------
def _frame_at(video_path, frac, out_jpg):
    """Klipning frac nisbatidagi nuqtasidan 1 kadr (validatsiya uchun)."""
    try:
        d = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path]).strip() or "2")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error",
             "-ss", f"{max(0, d * frac - 0.05):.2f}",
             "-i", video_path, "-frames:v", "1", "-vf",
             "scale=540:-2", "-q:v", "4", out_jpg],
            check=True, capture_output=True, timeout=60)
        return os.path.exists(out_jpg) and os.path.getsize(out_jpg) > 1000
    except Exception:
        return False


def _mid_frame(video_path, out_jpg):
    return _frame_at(video_path, 0.5, out_jpg)


def _ocr_text(jpg):
    """tesseract: kadrda matn/suv belgisi bormi? (doc C1)."""
    try:
        r = subprocess.run(["tesseract", jpg, "stdout", "--psm", "11",
                            "-l", "eng", "tsv"],
                           capture_output=True, text=True, timeout=30)
        words = []
        for line in r.stdout.splitlines()[1:]:
            p = line.split("\t")
            if len(p) >= 12 and p[11].strip():
                conf = float(p[10])
                w = p[11].strip()
                if conf > 78 and len(w) >= 4 and w.isalnum():
                    words.append(w)
        return words
    except Exception:
        return []


def _vision_check(cfg, jpg, scene_voice):
    """LLM vision (Claude -> Gemini zanjiri): kadr sahnaga mosmi?
    True/False/None (bilmaymiz)."""
    try:
        from src import llm
        txt = llm.chat(
            cfg,
            "You are a strict stock-footage QA checker. "
            "Answer strictly 'yes' or 'no' — nothing else.",
            "Does this footage frame clearly and safely illustrate this "
            f"narration: \"{scene_voice}\"? Answer strictly yes or no.",
            images=[jpg], temperature=0.0, timeout=30)
    except Exception as e:
        print(f"[media] vision xatosi: {e}")
        return None
    t = (txt or "").strip().lower()
    if t.startswith("yes"):
        return True
    if t.startswith("no"):
        return False
    return None


def fetch_scene_media(cfg, scene, used, prefix, n_want=3):
    """Sahna uchun HAR XIL kliplar ro'yxati (kesishlar uchun 3 tagacha).

    Validatsiya zanjiri (doc C1): slug/meta must_contain + reject ->
    tesseract OCR (matn/watermark yo'q) -> Gemini vision (sahna mos).
    """
    queries = scene.get("visual_query") or []
    must = scene.get("must_contain") or []
    reject = scene.get("reject") or []
    found = []
    for q in queries[:4]:
        for finder in (_pexels_search, _pixabay_search):
            try:
                items = finder(cfg, q)
            except Exception as e:
                print(f"[media] {finder.__name__} xatosi: {e}")
                continue
            for it in items:
                if it["id"] in used:
                    continue
                if any(f["id"] == it["id"] for f in found):
                    continue
                if not _accept(it, must, reject):
                    print(f"[media] rad etildi (must/reject): {it['id']} [{q}]")
                    continue
                dest = f"{prefix}_{len(found)}.bin"
                if not _download(it["link"], dest):
                    continue
                # kadr validatsiyasi: 3 nuqta (25/50/75%) — oraliq
                # kadrlarda chiqadigan titrlar ham ushlanadi (run 14)
                ocr_hit = None
                for fi, frac in enumerate((0.25, 0.5, 0.75)):
                    jpg = f"{dest}_f{fi}.jpg"
                    if _frame_at(dest, frac, jpg):
                        ocr = _ocr_text(jpg)
                        if len(ocr) >= 2:
                            ocr_hit = ocr
                            break
                if ocr_hit:
                    print(f"[media] rad etildi (OCR matn): {ocr_hit[:4]}")
                    os.remove(dest)
                    continue
                    v = _vision_check(cfg, jpg, scene.get("voice", ""))
                    if v is False:
                        print(f"[media] rad etildi (vision): {it['id']}")
                        os.remove(dest)
                        continue
                found.append({"id": it["id"], "path": dest})
                print(f"[media] topildi ({finder.__name__}) {q} -> {it['id']}")
                if len(found) >= n_want:
                    break
            if len(found) >= n_want:
                break
        if len(found) >= n_want:
            break
    if found:
        return found

    # mos klip yo'q -> XARITA animatsiyasi
    place = (scene.get("fallback") or "").replace("map_zoom:", "").strip() \
        or scene.get("on_screen", "")
    img = prefix + "_map.png"
    try:
        from src import maps
        maps.map_image(place or "world", img)
        print(f"[media] mos klip yo'q -> XARITA: {place}")
        return [{"id": f"map:{place}", "path": img}]
    except Exception as e:
        print(f"[media] xarita chizilmadi ({e}) -> kartochka")
        card = prefix + "_card.png"
        make_card(scene.get("on_screen", "")[:60], "", card)
        return [{"id": f"card:{place}", "path": card}]


def fetch_all(cfg, scenes, used_ids=None):
    """Har sahna uchun media ro'yxatlari + ishlatilgan klip id'lari."""
    used = set(used_ids or [])
    tmp = cfg["_paths"]["work"]
    os.makedirs(tmp, exist_ok=True)
    lists = []
    for i, sc in enumerate(scenes):
        lst = fetch_scene_media(cfg, sc, used, os.path.join(tmp, f"m{i:02d}"))
        used.update(x["id"] for x in lst)
        lists.append(lst)
    return lists, used
