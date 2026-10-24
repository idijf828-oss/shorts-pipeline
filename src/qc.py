"""Doc P4 — avtomatik QC darvozasi (render'dan keyin MAJBURIY).

Har FAIL -> main.produce_with_qc retry (musiqa remiks / stock'siz render),
3 urinishdan keyin Telegram'ga yuborilmaydi (main.py shunga qaraydi).

Tekshiruvlar (doc D0/D + P4 qo'shimchalar):
  1. 1080x1920, >=30fps, 45-55.2s (v6 listicle)
  2. LUFS -16..-14, true peak <= -1 dBTP (ebur128)
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
    o = _run(["tesseract", jp, "stdout", "--psm", "6"])
    words = [w for w in re.findall(r"[A-Za-z]{4,}", o) if not w.islower()]
    return len(words) == 0, " ".join(words[:6])


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
        ("LUFS -15..-13", -15.2 <= lufs <= -12.8, f"{lufs:.1f}"),  # v10: -14
        ("true peak <= -1", tp <= -1.0, f"{tp:.1f}"),
        ("tail 0.2-0.7s (ovoz oxiri)", 0.2 <= tail <= 0.7, f"{tail:.2f}s"),
        # v10 explainer: pauzalar qisqa; >1.7s = xato (qo'llanma: tez)
        ("uzun jimlik >1.7s = 0", not any(d > 1.7 for _s, d in mid),
         f"{len(mid)} pauza, eng uzuni {max((d for _s, d in mid), default=0):.2f}s"),
    ]

    # --- events.json (doc P4) ---
    evs = ev.get("events") or []
    if evs:
        ts = sorted(float(e["t"]) for e in evs)
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
        # doc P1: 96 doimiy; 80 faqat kam holatda (bitta uzun so'z)
        checks.append(("subtitr shrift 100 (88/80 kam holat)",
                       sizes <= {100, 88, 80},
                       "/".join(str(x) for x in sorted(sizes)) + "px"))

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

    bad = 0
    print("== QC (doc P4) ==")
    for name, ok, val in checks:
        print(("PASS" if ok else "FAIL"), name, "->", val)
        bad += (not ok)
    return bad == 0, checks
