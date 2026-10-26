"""Doc P4 — avtomatik QC darvozasi (render'dan keyin MAJBURIY).

Har FAIL -> main.produce_with_qc retry (musiqa remiks / stock'siz render),
3 urinishdan keyin Telegram'ga yuborilmaydi (main.py shunga qaraydi).

Tekshiruvlar (doc D0/D + P4 qo'shimchalar):
  1. 1080x1920, >=30fps, 45-55.2s (v6 listicle)
  2. LUFS -14±1, true peak <= -1 dBTP (ebur128)
  3. tail 0.2-0.7s (VOICE oxiri — events.json'dan; musiqa fonida
     silencedetect musiqa pauzasini "ovoz" deb biladi)
  4. ichki jimlik >=0.25s = 0 (silencedetect -35dB)
  5. events.json: har 1.2s oynada >=1 hodisa (max gap <= 1.2s)
  6. event <-> so'z farqi <= 0.15s (edge) / 0.30s (gTTS)
  7. subtitr baz shrift o'lchami bir xil (96 yoki 80..96)
  8. tepa yorliq: yo'q yoki >=72px va <=1.2s
  9. safe-zone: x<100 / x>980 chetlarida subtitr pikseli yo'q
 10. stock segmentlarda OCR matni yo'q
 11. musiqa pauzada eshitiladi: oxirgi oynada mean_volume -33..-24 dB
 12. V2 (topshiriq #5): 0.33s kadr ekstraksiya + OCR/piksel:
     - ZONA A statik sarlavha (bor, barqaror, 72px+, dup=0)
     - ZONA B faqat subtitr (<=6 so'z), kesilgan matn = 0
     - fill <=35%, element ekranda, ZONA tekshiruvlari (events.json)
     - bir xil kadr >2.2s = 0 (frame-diff)
"""
import json
import os
import re
import subprocess


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return r.stderr + r.stdout


def _probe(path):
    o = _run(["ffprobe", "-v", "error", "-select_streams", "v:0",
              "-show_entries",
              "stream=width,height,r_frame_rate:format=duration",
              "-of", "default=nw=1", path])
    w = int(re.search(r"width=(\d+)", o).group(1))
    h = int(re.search(r"height=(\d+)", o).group(1))
    n, d = re.search(r"r_frame_rate=(\d+)/(\d+)", o).groups()
    dur = float(re.search(r"duration=([\d.]+)", o).group(1))
    return w, h, int(n) / int(d), dur


def _audio(path):
    o = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
              "ebur128=peak=true,silencedetect=n=-35dB:d=0.25",
              "-f", "null", "-"])
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", o)[-1])
    tp = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", o)[-1])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", o)]
    ends = [(float(a), float(b)) for a, b in
            re.findall(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", o)]
    return lufs, tp, starts, ends


def _mean_vol(path, t0, t1):
    o = _run(["ffmpeg", "-hide_banner", "-ss", f"{max(0, t0):.2f}",
              "-to", f"{t1:.2f}", "-i", path, "-af", "volumedetect",
              "-f", "null", "-"])
    m = re.search(r"mean_volume: (-?[\d.]+) dB", o)
    return float(m.group(1)) if m else -99.0


def _frame(path, t, out_jpg):
    _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", path,
          "-frames:v", "1", out_jpg])
    return os.path.exists(out_jpg) and os.path.getsize(out_jpg) > 1000


def _ass_safe_zone(work):
    """Subtitr matni x in [110,970] da (doc P4c) — ASS parse orqali.
    Xarita chiziqlari piksel-testda yolg'on positive beradi, shuning
    uchun kenglik anik hisoblanadi (PIL font metrics)."""
    from src import captions
    worst = 0.0
    for fn in sorted(os.listdir(work)):
        if not (fn.startswith("subs_") and fn.endswith(".ass")):
            continue
        with open(os.path.join(work, fn), encoding="utf-8") as f:
            for line in f:
                if not line.startswith("Dialogue"):
                    continue
                m = re.search(r"\\fs(\d+)", line)
                if not m:
                    continue
                size = int(m.group(1))
                txt = line.rsplit(",,", 1)[-1]
                txt = re.sub(r"\{[^}]*\}", "", txt).replace("\\N", "\n")
                # aktiv so'z 115% chunking'da hisoblangan -> plain <= 880
                w = max(captions.text_width(l, size)
                        for l in txt.split("\n"))
                worst = max(worst, 540 + w / 2)
                # x0 = 540-w/2 >= 110  <=>  540-w/2; x1 = 540+w/2 <= 970
    return worst


def _ocr_clean(path, t):
    jp = f"/tmp/qc_ocr_{int(t*10)}.jpg"
    if not _frame(path, t, jp):
        return True                      # kadr olinmadi -> tekshirilmaydi
    # V2: ZONA B (y 660-900, subtitr doim turadi) ni bo'yab tashlaymiz —
    # subtitr stock-OCR'ga "matn bor" deb false-positive berdi (saboq)
    try:
        from PIL import Image, ImageDraw
        im = Image.open(jp).convert("RGB")
        ImageDraw.Draw(im).rectangle([0, 660, 1080, 900], fill=(0, 0, 0))
        im.save(jp)
    except Exception:
        pass
    o = _run(["tesseract", jp, "stdout", "--psm", "6"])
    words = [w for w in re.findall(r"[A-Za-z]{4,}", o) if not w.islower()]
    return len(words) == 0, " ".join(words[:6])


# ---------- V2 (topshiriq #5): kadr-darajasidagi tekshiruvlar ----------

ZONE_A = (120, 320)     # style.py bilan bir xil (mustaqil nusxa — review
ZONE_B = (700, 860)     # ham shunday; atayin hardcode-emas, pastda sync)
ZONE_C = (1400, 1750)


def _extract_frames(path, out_dir, fps=3.0):
    """Butun videodan fps=kadrlar (0.33s) — bitta ffmpeg chaqiruv."""
    os.makedirs(out_dir, exist_ok=True)
    for fn in os.listdir(out_dir):
        if fn.endswith(".jpg"):
            os.remove(os.path.join(out_dir, fn))
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", path, "-vf", f"fps={fps}",
         os.path.join(out_dir, "f_%05d.jpg")],
        capture_output=True, text=True, timeout=600)
    fs = sorted(f for f in os.listdir(out_dir) if f.endswith(".jpg"))
    return [os.path.join(out_dir, f) for f in fs]


def _strip(img_p, y0, y1, out_p):
    """Kadrning gorizontal yo'lakasini kesib saqlaydi (OCR uchun)."""
    from PIL import Image
    im = Image.open(img_p)
    im.crop((0, y0, im.size[0], y1)).save(out_p)
    return out_p


def _ocr_words(img_p, min_len=3):
    """[(so'z, x, y, w, h, conf)] — tesseract TSV (conf bilan)."""
    o = _run(["tesseract", img_p, "stdout", "--psm", "6", "tsv"])
    out = []
    for ln in o.splitlines():
        p = ln.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        try:
            conf = float(p[10])
        except ValueError:
            continue
        w = p[11].strip().strip(".,:;!?")
        if conf < 55 or len(w) < min_len or not re.search(r"[A-Za-z]", w):
            continue
        try:
            out.append((w.upper(), int(p[6]), int(p[7]),
                        int(p[8]), int(p[9]), conf))
        except ValueError:
            continue
    return out


def _hard_edge_white(img_p, y0, y1):
    """Zonadagi 'oq piksel + yaqin qora qo'shni' soni (konturli oq matn).
    Satellite fonda OCR mo'rt — bu piksel metrikasi deterministik
    (sarlavha: oq + borderw 6 qora; qor/bulut yumshoq gradyan)."""
    from PIL import Image
    im = Image.open(img_p).convert("L")
    st = im.crop((0, y0, im.size[0], y1))
    w, h = st.size
    px = st.load()
    cnt = 0
    for y in range(6, h - 6):
        for x in range(7, w - 7):
            if px[x, y] > 200:
                if (px[x, y - 6] < 90 or px[x, y + 6] < 90
                        or px[x - 7, y] < 90 or px[x + 7, y] < 90):
                    cnt += 1
    return cnt


def _edge_text_pixels(img_p, y0, y1):
    """Chetka ustunlardagi oq+qora-konturli piksellar — haqiqiy kesilgan
    matn belgisi (OCR bbox'iga yopishgan fon artefaktlariga aldanmaydi:
    WEUROPE'S x=0 conf89 -> piksel 0)."""
    from PIL import Image
    im = Image.open(img_p).convert("L")
    st = im.crop((0, y0, im.size[0], y1))
    w, h = st.size
    px = st.load()
    cnt = 0
    for y in range(6, h - 6):
        for x in list(range(0, 14)) + list(range(w - 14, w)):
            if px[x, y] > 200:
                if (px[x, y - 6] < 90 or px[x, y + 6] < 90
                        or (x >= 7 and px[x - 7, y] < 90)
                        or (x < w - 7 and px[x + 7, y] < 90)):
                    cnt += 1
    return cnt


def _gray_small(img_p, w=54, h=96):
    from PIL import Image
    im = Image.open(img_p).convert("L").resize((w, h))
    return list(im.getdata())


def v2_frame_checks(path, dur, ev, checks, step=0.333):
    """V2 qo'shimcha: OCR + piksel. checks ro'yxatiga qo'shib boradi."""
    try:
        from PIL import Image
    except ImportError:
        checks.append(("V2 kadr tekshiruvi", False, "PIL yo'q"))
        return
    # PID-asosli: parallel qc/review chaqiruvlari bir-birining
    # kadrlarini o'chirmasin (proof+compare poygasi saboq)
    fdir = f"/tmp/qc_v2_frames_{os.getpid()}"
    frames = _extract_frames(path, fdir, fps=round(1.0 / step, 2))
    if len(frames) < 8:
        checks.append(("V2 kadrlar olindi", False, f"{len(frames)} kadr"))
        return
    evs = ev.get("events") or []
    ttl_ev = [e for e in evs if str(e.get("type")) == "title"]
    ttl_txt = str(ttl_ev[0].get("text", "")) if ttl_ev else ""
    ttl_tokens = {w for w in re.findall(r"[A-Z0-9]{4,}", ttl_txt)}

    # --- events.json asosidagi (deterministik) V2 tekshiruvlari ---
    if ttl_ev:
        t0 = ttl_ev[0]
        in_a = (ZONE_A[0] - 40 <= int(t0.get("y", 0))
                <= ZONE_A[1] - int(t0.get("h", 0)) + 60)
        checks.append(("V2 sarlavha ZONA A + 72px+",
                       in_a and int(t0.get("size", 0)) >= 72,
                       f"y={t0.get('y')} h={t0.get('h')} "
                       f"size={t0.get('size')}px"))
    else:
        checks.append(("V2 sarlavha ZONA A + 72px+", False, "title yo'q"))

    # bayroq fill maydoni <=35% — FAQAT bayroq teksturali fill'lar
    # uchun (light rejim: >35% yoki <2% -> kontur+tint, V2-2 ruxsat)
    areas = [float(e.get("area") or 0) for e in evs
             if str(e.get("type")) == "flag_fill" and e.get("area")
             and not e.get("light")]
    lights = [(str(e.get("iso")), float(e.get("area") or 0)) for e in evs
              if str(e.get("type")) == "flag_fill" and e.get("light")]
    light_ok = all(a > 0.34 or a < 0.03 for _i, a in lights)
    checks.append(("V2 bayroq fill <=35% ekr",
                   all(a <= 0.36 for a in areas) and light_ok,
                   (f"bayroq max {max(areas) if areas else 0:.0%}; "
                    + (f"light: {lights[:2]}" if lights else "light yo'q"))))

    # ko'rinish qutilari: ekranda + ZONA B bilan kesishmasin
    off, clash = [], []
    for e in evs:
        if str(e.get("type")) in ("icon", "arrow", "pin", "label",
                                  "screen"):
            vx, vy = e.get("vx"), e.get("vy")
            vw, vh = e.get("vw"), e.get("vh")
            if None in (vx, vy, vw, vh):
                continue
            if vx < 0 or vy < 0 or vx + vw > 1080 or vy + vh > 1920:
                off.append(f"{e.get('type')}@{e.get('t'):.1f}s")
            if vy < ZONE_B[1] and vy + vh > ZONE_B[0]:
                clash.append(f"{e.get('type')}@{e.get('t'):.1f}s")
            if str(e.get("type")) in ("icon", "arrow") and e.get(
                    "y") is not None:
                y, sz = int(e["y"]), int(e.get("s") or 320)
                if not (ZONE_C[0] - 60 <= y <= ZONE_C[1]):
                    off.append(f"{e.get('type')}-zonadan@{e.get('t'):.1f}s")
    checks.append(("V2 element ekrandan chiqmadi", not off,
                    ",".join(off[:3]) or "ok"))
    checks.append(("V2 ZONA B boshqalar bilan to'qnashmadi", not clash,
                    ",".join(clash[:3]) or "ok"))

    # title <-> ko'rinish qutilari kesishuvi (matn-matn/matn-ikonka = 0)
    overlap = []
    if ttl_ev:
        tb = ttl_ev[0]
        tx0, ty0 = int(tb.get("x", 0)), int(tb.get("y", 0))
        tx1, ty1 = tx0 + int(tb.get("w", 0)), ty0 + int(tb.get("h", 0))
        for e in evs:
            if str(e.get("type")) in ("icon", "arrow", "pin", "label",
                                      "screen") and None not in (
                    e.get("vx"), e.get("vy"), e.get("vw"), e.get("vh")):
                if (int(e["vx"]) < tx1 and int(e["vx"]) + int(e["vw"]) > tx0
                        and int(e["vy"]) < ty1
                        and int(e["vy"]) + int(e["vh"]) > ty0):
                    overlap.append(f"{e.get('type')}@{e.get('t'):.1f}s")
    checks.append(("V2 sarlavha<->element kesishuv=0", not overlap,
                    ",".join(overlap[:3]) or "ok"))

    # --- OCR + piksel kadrlar bo'yicha ---
    pres_a, dup_frames, extra_b, clipped, words_b_max = [], [], [], [], 0
    grays = []
    _wb = [re.compile(r"\b" + re.escape(t) + r"\b")
           for t in sorted(ttl_tokens)]
    for k, fp in enumerate(frames):
        a_p = _strip(fp, ZONE_A[0] - 40, ZONE_A[1] + 40,
                     f"/tmp/qc_v2_a_{k:04d}.png")
        b_p = _strip(fp, ZONE_B[0] - 40, ZONE_B[1] + 40,
                     f"/tmp/qc_v2_b_{k:04d}.png")
        wa = _ocr_words(a_p)
        wb = _ocr_words(b_p)
        grays.append(_gray_small(fp))
        a_txt = " ".join(w for w, *_ in wa)
        has_ttl = bool(ttl_tokens) and any(
            t in a_txt for t in ttl_tokens)
        pres_a.append(has_ttl)
        b_txt = " ".join(w for w, *_ in wb)
        # dup: SO'Z CHEGARASI bilan ("RULER" != "RULERS", "EUROPE" !=
        # "EUROPEAN") — substring noto'g'ri dup berdi (africa 3.7s)
        if (ttl_tokens and has_ttl
                and any(r.search(b_txt) for r in _wb)):
            dup_frames.append(round(k * step, 1))
        if len(wb) > 6:
            extra_b.append(round(k * step, 1))
        # kesilgan: PIKSEL (chetka ustunlarda konturli oq belgi) — OCR
        # bbox yopishgan artefaktlarga aldanmaydi
        # chegara 200: xarita shovqini (qor/dengiz cheti) <=141
        # o'lchandi, haqiqiy kesilgan matn ~286+ (simulyatsiya)
        if (_edge_text_pixels(fp, ZONE_A[0] - 40, ZONE_A[1] + 40) >= 200
                or _edge_text_pixels(fp, ZONE_B[0] - 40,
                                     ZONE_B[1] + 40) >= 200):
            clipped.append(f"chekka@{k * step:.1f}s")
        words_b_max = max(words_b_max, len(wb))
        os.remove(a_p)
        os.remove(b_p)

    # sarlavha barqarorligi (statik + fade): PIKSEL (oq+kontur) — OCR
    # band satellite fonda ishonchsiz (us_canada: 44% "yo'q" chiqqan,
    # holbuki piksel 11-13k barqar). Boshqa frameda esa aksincha.
    pres_px = [_hard_edge_white(fp, ZONE_A[0] - 40, ZONE_A[1] + 40) > 6000
               for fp in frames]
    n = len(pres_px)
    on_ratio = sum(pres_px) / n if n else 0
    toggles = sum(1 for a, b in zip(pres_px, pres_px[1:]) if a != b)
    checks.append(("V2 sarlavha barqar (piksel ZONA A)",
                   on_ratio >= 0.60 and toggles <= 12,
                   f"{on_ratio:.0%} kadrdа, {toggles} almashuv"))
    checks.append(("V2 sarlavha so'zi subtitrda TAKRORLANMASIN",
                   not dup_frames,
                   ",".join(str(x) for x in dup_frames[:4]) or "dup=0"))
    checks.append(("V2 ZONA B faqat subtitr (<=6 so'z)", not extra_b,
                    f"eng ko'p {words_b_max} so'z"))
    checks.append(("V2 matn kesilmagan (chekka=0)", not clipped,
                    ",".join(clipped[:4]) or "ok"))

    # bir xil kadr >2.2s = 0 (frame-diff)
    same_run = best = 0
    for g0, g1 in zip(grays, grays[1:]):
        d = sum(abs(a - b) for a, b in zip(g0, g1)) / len(g0)
        if d < 2.0:
            same_run += 1
            best = max(best, same_run)
        else:
            same_run = 0
    static_s = best * step
    checks.append(("V2 bir xil kadr >2.2s yo'q", static_s <= 2.2,
                   f"eng uzun {static_s:.1f}s"))

    # vaqtinchalik kadrlarni tozalash
    for fp in frames:
        try:
            os.remove(fp)
        except OSError:
            pass


def run_checks(path, cfg=None, work=None):
    """-> (all_ok, [(nom, ok, qiymat), ...]) — stdout ga jadval chiqaradi."""
    cfg = cfg or {}
    work = work or os.path.dirname(os.path.abspath(path))
    w, h, fps, dur = _probe(path)
    lufs, tp, starts, ends = _audio(path)

    ev = {}
    try:
        with open(os.path.join(work, "events.json"), encoding="utf-8") as f:
            ev = json.load(f)
    except Exception:
        pass

    # --- tail: VOICE oxiri (doc P4: musiqa eshitiladi, jimlik emas) ---
    voice_end = ev.get("voice_end")
    if not voice_end:
        sil = [(e - d, e) for e, d in ends]
        if len(starts) > len(ends):
            sil.append((starts[-1], dur))
        tail = max([dur - s for s, e in sil if e >= dur - 0.15], default=0.0)
    else:
        tail = dur - float(voice_end)

    sil_pairs = [(e - d, e) for e, d in ends]
    if len(starts) > len(ends):
        sil_pairs.append((starts[-1], dur))
    mid = [(round(s, 2), round(e - s, 2)) for s, e in sil_pairs
           if s > 0.3 and e < dur - 0.15]

    checks = [
        ("1080x1920", (w, h) == (1080, 1920), f"{w}x{h}"),
        (">=30 fps", fps >= 29.9, f"{fps:.2f}"),
        (f"{cfg['video']['min_duration']}-{cfg['video']['max_duration']} s",
         cfg["video"]["min_duration"] <= dur <= cfg["video"]["max_duration"] + 0.2,
         f"{dur:.2f}s"),
        # v10.2 (user #5): QAT'IY -14±1 (aks holda PASS yo'q)
        ("LUFS -14±1", -15.0 <= lufs <= -13.0, f"{lufs:.1f}"),
        ("true peak <= -1", tp <= -1.0, f"{tp:.1f}"),
        ("tail 0.2-0.7s (ovoz oxiri)", 0.2 <= tail <= 0.7, f"{tail:.2f}s"),
        # v10 explainer: pauzalar qisqa; >1.7s = xato (qo'llanma: tez)
        ("uzun jimlik >1.7s = 0", not any(d > 1.7 for _s, d in mid),
         f"{len(mid)} pauza, eng uzuni {max((d for _s, d in mid), default=0):.2f}s"),
    ]

    # --- events.json (doc P4) ---
    evs = ev.get("events") or []
    if evs:
        # v10.2: video tugashidan keyingi "fantom" hodisalar hisobga kirsin emas
        ts = sorted(float(e["t"]) for e in evs if float(e["t"]) <= dur + 0.05)
        max_gap = max([b - a for a, b in zip([0.0] + ts, ts + [dur])],
                      default=dur)
        checks.append(("har <=2.2s da vizual o'zgarish (qo'llanma)",
                       max_gap <= 2.2,
                       f"max gap {max_gap:.2f}s ({len(evs)} hodisa)"))
        engine = str(ev.get("engine", "edge"))
        tol = 0.30 if engine == "gtts" else 0.15
        worst = 0.0
        for e in evs:
            if "word_t" in e:
                worst = max(worst, abs(float(e["t"]) - float(e["word_t"])))
        checks.append((f"event<->so'z <= {tol:.2f}s", worst <= tol + 0.01,
                       f"eng katta farq {worst:.3f}s"))
        osd = [e for e in evs if e.get("type") == "on_screen"]
        if osd:
            o0 = osd[0]
            checks.append(("tepa yorliq >=72px, <=3.2s",
                           int(o0.get("size", 0)) >= 72
                           and float(o0.get("dur", 9)) <= 3.2,
                           f"{o0.get('size')}px/{o0.get('dur')}s"))
        else:
            checks.append(("tepa yorliq yo'q yoki >=72px", True, "yo'q"))
        hook = min(ts) if ts else 9.9
        checks.append(("hook <=0.5s da harakat", hook <= 0.5, f"{hook:.2f}s"))
        # v10.1 (user): kamida 3 xil xarita ko'rinishi
        mv = {(e.get("lat"), e.get("lon"), e.get("z"))
              for e in evs if e.get("type") == "map_view"}
        checks.append((">=3 xil xarita ko'rinishi", len(mv) >= 3,
                       f"{len(mv)} xil ko'rinish"))
    else:
        checks.append(("events.json mavjud", False, "yo'q"))

    # --- subtitr shrift bir xilligi (doc P4a; v7: subtitrsiz rejimda yo'q) ---
    sizes = set()
    if not bool((cfg.get("captions") or {}).get("enabled", True)):
        sizes = set()  # subtitr o'chiq -> pastdagi blok o'tkazib yuboriladi
    for fn in sorted(os.listdir(work)) if os.path.isdir(work) else []:
        if fn.startswith("subs_") and fn.endswith(".ass"):
            with open(os.path.join(work, fn), encoding="utf-8") as f:
                sizes |= set(int(x) for x in re.findall(r"\\fs(\d+)", f.read()))
    if bool((cfg.get("captions") or {}).get("enabled", True)) and sizes:
        # v10.2-a: so'z narxoni 100->88->80->72 (pop YO'Q, bitta tanlov)
        checks.append(("subtitr shrift 100 (narxon 88/80/72)",
                       sizes <= {100, 88, 80, 72},
                       "/".join(str(x) for x in sorted(sizes)) + "px"))

    # --- v10.2 (user, topshiriq #4): qiyin so'z yo'q (on_screen + OCR) ---
    HARD = ("jurisdiction", "contiguous", "exclave", "enclave", "feudal",
            "sovereignty", "sovereign", "demarcation", "cession",
            "irredentist", "condominium", "estoppel", "pursuant",
            "whereas")
    hard_bad = []
    for e in (ev.get("events") or []):
        if str(e.get("type")) == "on_screen":
            t = " " + re.sub(r"[^a-z]+", " ",
                             str(e.get("text") or "").lower()) + " "
            for b in HARD:
                if f" {b} " in t or f" {b}s " in t:
                    hard_bad.append(f"on_screen:{b}")
    try:
        mid = dur / 2.0
        for tt in (mid - 1.0, mid + 1.0):
            if tt < 0.3 or tt > dur - 0.3:
                continue
            jp = f"/tmp/qc_hard_{int(tt*10)}.jpg"
            if _frame(path, tt, jp):
                o = _run(["tesseract", jp, "stdout", "--psm", "6"])
                low = " " + re.sub(r"[^a-z]+", " ", o.lower()) + " "
                for b in HARD:
                    if f" {b} " in low or f" {b}s " in low:
                        hard_bad.append(f"ocr@{tt:.0f}s:{b}")
    except Exception:
        pass
    checks.append(("qiyin so'z yo'q (7-8 yosh tili)", not hard_bad,
                    ",".join(sorted(set(hard_bad))[:3]) or "toza"))

    # --- v10.2 (user, topshiriq #2): ikonka/strelka subtitr ustida emas ---
    sub_y = None
    if os.path.isdir(work):
        for fn in sorted(os.listdir(work)):
            if fn.startswith("subs_") and fn.endswith(".ass"):
                with open(os.path.join(work, fn), encoding="utf-8") as f:
                    m = re.search(r"\\pos\(540,(\d+)\)", f.read())
                if m:
                    sub_y = int(m.group(1))
                break
    band_bad = []
    if sub_y:
        for e in (ev.get("events") or []):
            if str(e.get("type")) in ("icon", "arrow") and e.get("y") is not None:
                sz = int(e.get("s") or 340)
                if e["y"] < sub_y + 180 and e["y"] + sz > sub_y - 180:
                    band_bad.append(f"seg{e.get('seg')}:{e.get('type')}")
    checks.append(("ikonka/strelka subtitr ustida emas", not band_bad,
                    ",".join(band_bad[:3]) or f"banda yo'q (sub_y={sub_y})"))

    # --- v10.2 (user, topshiriq #3): kamera — zoom o'sishi + pin ---
    mvs = [e for e in (ev.get("events") or [])
           if str(e.get("type")) == "map_view"]
    cam_ok, cam_note = True, "xarita sahna yo'q"
    if mvs:
        zs = [int(e.get("z") or 0) for e in mvs]
        distinct = len({(e.get("lat"), e.get("lon"), e.get("z"))
                        for e in mvs})
        prog = all(b >= a for a, b in zip(zs, zs[1:]))
        pin = any(str(e.get("type")) == "pin"
                  for e in (ev.get("events") or []))
        cam_ok = bool(prog and distinct >= 3 and zs and max(zs) >= 6 and pin)
        cam_note = (f"z={zs}, {distinct} xil kadr, pin="
                    + ("bor" if pin else "yo'q"))
    checks.append(("kamera: zoom o'sadi + pin bor", cam_ok, cam_note))

    # --- v10.2 (user, topshiriq #1): so'z ichida uzilish YO'Q ---
    seg_voices = [str(sg.get("voice") or "").lower()
                  for sg in (ev.get("segments") or [])]
    broken = []
    if os.path.isdir(work) and bool((cfg.get("captions") or {})
                                    .get("enabled", True)):
        for fn in sorted(os.listdir(work)):
            if not (fn.startswith("subs_") and fn.endswith(".ass")):
                continue
            try:
                i_seg = int(fn[5:7])
            except ValueError:
                continue
            vw = set()
            if i_seg < len(seg_voices):
                vw = set(re.sub(r"[^a-z0-9'\- ]", " ",
                                seg_voices[i_seg]).split())
            with open(os.path.join(work, fn), encoding="utf-8") as f:
                for line in f:
                    if not line.startswith("Dialogue:") or ",Cap," not in line:
                        continue
                    body = ",".join(line.split(",", 9)[9:])
                    clean = re.sub(r"\{[^}]*\}", "", body)
                    for ln in clean.split("\\N"):
                        for tok in re.findall(r"[A-Za-z][A-Za-z\-']*", ln):
                            t_ = tok.strip("'-").lower()
                            if t_ and vw and t_ not in vw:
                                broken.append(f"{fn[:-4]}:{tok}")
    checks.append(("so'z ichida bo'linish yo'q", not broken,
                    ",".join(broken[:3]) if broken else "ok"))

    # --- safe-zone (doc P4c): subtitr x in [110,970] ---
    if os.path.isdir(work) and bool((cfg.get("captions") or {})
                                    .get("enabled", True)):
        edge = _ass_safe_zone(work)            # eng chekkadagi matn chizig'i
        checks.append(("safe-zone subtitr x in [110,970]",
                       edge <= 976, f"eng chetki x={edge:.0f}"))

    # --- stock OCR (doc P4d) ---
    stock_segs = [sg for sg in (ev.get("segments") or [])
                  if sg.get("mode") == "stock"]
    if stock_segs:
        ocr_bad = []
        for sg in stock_segs:
            mid_t = (float(sg["t0"]) + float(sg["t1"])) / 2
            clean, txt = _ocr_clean(path, mid_t)
            if not clean:
                ocr_bad.append(txt)
        checks.append(("stock kadrlarda OCR matni yo'q",
                       not ocr_bad, "; ".join(ocr_bad)[:60] or "toza"))
    else:
        checks.append(("stock kadrlarda OCR matni yo'q", True, "stock yo'q"))

    # --- musiqa pauzada eshitiladi (doc P2/P4e; v7 musiqasiz -> o'tadi) ---
    if bool((cfg.get("sfx") or {}).get("music_enabled", True)):
        wins = []
        for sg in (ev.get("segments") or [])[:-1]:
            gap = float(sg["t1"]) - float(sg.get("voice_end", sg["t1"]))
            if gap >= 0.30:
                wins.append((float(sg["voice_end"]), float(sg["t1"])))
        if wins:
            mvs = []
            for (a, b) in wins:
                w0, w1 = a + 0.08, min(b - 0.02, a + 0.63)
                if w1 - w0 >= 0.15:
                    mvs.append(_mean_vol(path, w0, w1))
            mvs.sort()
            mv = mvs[len(mvs) // 2] if mvs else -99.0
            checks.append(("musiqa pauzada M -33..-24 dB (median)",
                           -33.5 <= mv <= -24.0,
                           f"{mv:.1f} dB ({len(mvs)} oyna)"))
        else:                            # pauza yo'q -> tail (fade ichida)
            ve = float(ev.get("voice_end") or (dur - 0.5))
            w0, w1 = ve + 0.03, dur - 0.03
            mv = _mean_vol(path, w0, max(w0 + 0.20, w1))
            checks.append(("musiqa tail'da eshitiladi (>=-36 dB)",
                           mv >= -36.0, f"{mv:.1f} dB @ {w0:.1f}s"))
    else:
        checks.append(("musiqa: o'chirilgan (v7 immersive)", True,
                       "pauzalar tabiiy jim (referens)"))

    # --- V2 (topshiriq #5): kadr-darajasidagi tekshiruvlar ---
    try:
        v2_frame_checks(path, dur, ev, checks)
    except Exception as e:
        checks.append(("V2 kadr tekshiruvi", False, f"xato: {e}"))

    # v13 (user 3-A): LOOP rejimi — oxirgi kadr ≈ birinchi kadr
    # (faqat render_meta.json ending_mode=loop bo'lsa; boshqa holda skip)
    try:
        meta_p = os.path.join(work, "render_meta.json")
        if os.path.isfile(meta_p):
            meta = json.load(open(meta_p, encoding="utf-8"))
            if str(meta.get("ending_mode")) == "loop":
                f0 = os.path.join(work, "qc_loop_first.jpg")
                fn = os.path.join(work, "qc_loop_last.jpg")
                _frame(path, 0.0, f0)
                # konteyner davomiyligi video oqimidan uzun bo'lishi mumkin
                # (audio tail) — oxirgi HAQIQIY kadrni topguncha orqaga
                last_ok = False
                for _dt in (0.04, 0.10, 0.20, 0.35):
                    if _frame(path, max(0.0, dur - _dt), fn):
                        last_ok = True
                        break
                if not last_ok:
                    raise RuntimeError("oxirgi kadr olinmadi")
                from PIL import Image as _I
                a = _I.open(f0).convert("L").resize((270, 480))
                b = _I.open(fn).convert("L").resize((270, 480))
                pa, pb = list(a.getdata()), list(b.getdata())
                diff = sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)
                checks.append(("LOOP oxirgi kadr≈birinchi kadr (tutash)",
                               diff < 10.0,
                               f"o'rtacha farq {diff:.1f}/255"))
    except Exception:
        pass

    bad = 0
    print("== QC (doc P4) ==")
    for name, ok, val in checks:
        print(("PASS" if ok else "FAIL"), name, "->", val)
        bad += (not ok)

    return bad == 0, checks
