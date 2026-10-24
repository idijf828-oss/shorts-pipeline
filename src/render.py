"""V4 render — map-explainer montaji (doc B/C), past xotira arxitekturasi.

Har xarita segmenti IKKI bosqichda:
  A) HOLAT-SUBSEGMENTLAR: full-qatlamlar (bayroq-fill/highlight/line)
     paydo bo'lish vaqtlari bo'yicha holatlarga bo'linadi; har holat
     uchun base+aktiv qatlamlar PIL'da BITTA still PNG'ga kompozit
     qilinadi va BITTA zoompan (zs->ze + punch) bilan render qilinadi.
     Zoom ifodasi global frame hisobidan o'tadi — subsegmentlar orasida
     uzluksiz. (Ko'p parallel zoompan zanjiri OOM berardi — sabab: har
     zanjir ~400MB; bittaga cheklandi.)
  B) YAKUNIY PASS (yengil): screen-space ikonkalar/pinlar/strelkalar
     (fade+slide) + rangli subtitr (ass) + audio + apad tail.

B-roll segmentlari: bitta pass (klip + ikonkalar + ass + audio).
Yakuniy: concat -> musiqa (CC0 fayl, -18dB, sidechain ducking, 1s
fade-out) -> loudnorm -15:TP=-1.5 mix'dan KEYIN (doc C4).
Oxirgi segment +0.5s tail — oxirgi gap hech qachon kesilmaydi.
Atributsiya kadrda YO'Q (public domain fon).
"""
import math
import os
import subprocess

from PIL import Image

from . import captions, style

W, H = 1080, 1920
FPS = 30
TAIL = 0.30         # v9: 0.5 -> 0.30 (audio oxiri endi +0.25s pad bilan)
CRF = "18"
FONT_DIR = "/usr/share/fonts/truetype/montserrat"


def _run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        print("[render] CMD:", " ".join(cmd[:14]), "...")
        print("[render] XATO:", r.stderr[-600:])
        raise RuntimeError(f"ffmpeg xato: {r.returncode}")


def _zexpr(zs, ze, n_total, f0, punches, motion="zoom_in"):
    """Global frame hisobidan zoom (+ punch gauss). v10.1: pan rejimlari."""
    if motion == "zoom_out":
        zs, ze = ze, zs
    if motion in ("pan_left", "pan_right", "pan_up", "pan_down"):
        zm = (zs + ze) / 2.0
        z = f"'{zm:.4f}'"
    else:
        z = f"'{zs:.4f}+({ze:.4f}-{zs:.4f})*min({f0}+on,{n_total})/{n_total}'"
    for p in punches:
        z += f"+0.055*exp(-(on-{p}) * (on-{p})/45)"
    return z


def _pan_xy(motion, n_total, f0):
    """v10.1: pan uchun zoompan x/y ifodalari (view 4% siljiydi)."""
    prog = f"min({f0}+on,{n_total})/{n_total}"
    cx = "'iw/2-(iw/zoom/2)'"
    cy = "'ih/2-(ih/zoom/2)'"
    if motion == "pan_left":
        return (f"'(iw/2-(iw/zoom/2))+({prog})*iw*0.04'", cy)
    if motion == "pan_right":
        return (f"'(iw/2-(iw/zoom/2))-({prog})*iw*0.04'", cy)
    if motion == "pan_up":
        return (cx, f"'(ih/2-(ih/zoom/2))+({prog})*ih*0.04'")
    if motion == "pan_down":
        return (cx, f"'(ih/2-(ih/zoom/2))-({prog})*ih*0.04'")
    return cx, cy


def _pers_coeffs(dst_quad, src_quad):
    """PERSPECTIVE koeffitsientlari (dst -> src), 8x8 Gauss yechimi."""
    A, b = [], []
    for (X, Y), (x, y) in zip(dst_quad, src_quad):
        A.append([X, Y, 1, 0, 0, 0, -x * X, -x * Y]); b.append(x)
        A.append([0, 0, 0, X, Y, 1, -y * X, -y * Y]); b.append(y)
    for i in range(8):                          # Gauss elim.
        p = max(range(i, 8), key=lambda k: abs(A[k][i]))
        A[i], A[p], b[i], b[p] = A[p], A[i], b[p], b[i]
        if abs(A[i][i]) < 1e-12:
            return None
        for k in range(i + 1, 8):
            f = A[k][i] / A[i][i]
            A[k] = [a - f * c for a, c in zip(A[k], A[i])]
            b[k] -= f * b[i]
    c = [0.0] * 8
    for i in range(7, -1, -1):
        c[i] = (b[i] - sum(a * x for a, x in zip(A[i][i + 1:], c[i + 1:]))) / A[i][i]
    return c


def _tilt(img):
    """v10.1: biroz egilgan 3D perspektiva (tepasi ~4% tor) — qo'llanma
    uslubi. 8% overscan -> bo'sh burchak qolmaydi."""
    try:
        w, h = img.size
        k = 0.04 * w
        src = img.resize((int(w * 1.08), int(h * 1.08)), Image.LANCZOS)
        sw, sh = src.size
        sx0, sy0 = (sw - w) / 2, (sh - h) / 2
        sx1, sy1 = sx0 + w, sy0 + h
        co = _pers_coeffs([(0, 0), (w, 0), (w, h), (0, h)],
                          [(sx0 + k, sy0), (sx1 - k, sy0),
                           (sx1, sy1), (sx0, sy1)])
        if co:
            return src.transform((w, h), Image.PERSPECTIVE, co,
                                 Image.BICUBIC)
    except Exception:
        pass
    return img


def _compose_state(base_png, layer_paths, work, tag):
    """base + aktiv full-qatlamlar -> BITTA still PNG."""
    img = Image.open(base_png).convert("RGBA")
    for p in layer_paths:
        try:
            ly = Image.open(p).convert("RGBA")
            if ly.size != img.size:
                ly = ly.resize(img.size, Image.LANCZOS)
            img = Image.alpha_composite(img, ly)
        except Exception as e:
            print(f"[render] qatlam kompozit xatosi ({p}): {e}")
    out = os.path.join(work, f"state_{tag}.png")
    # v10.1h (user): tilt O'CHIRILDI — trapetsiya + zoom kuchayishi
    # "torilanib ketadi" ta'sir berdi. Xarita to'g'ri, to'liq kadr.
    img.convert("RGB").save(out, quality=92)
    return out


def _fit_onscreen(text):
    """Doc P1: tepa yorliq >=72px, kalit-ibora (oxirgi so'zlar saqlanadi)."""
    t = " ".join(str(text or "").split())[:60]
    # v10.2 (user #4): so'z o'rtasidan kesmasin — probelgacha qisqartir
    if len(t) == 60 and " " in t:
        t = t[:t.rfind(" ")]
    words = t.split()
    for n in (len(words), 4, 3, 2, 1):
        cand = " ".join(words[-n:]) if n < len(words) else t
        for size in (style.ONSCREEN_SIZE, 76, 72):
            if captions.text_width(cand, size) <= 880:
                return cand, size
    return words[-1], 72


def _render_map_states(vis, fulls, punches, dur, on_screen, work, i):
    """A-bosqich: holat-subsegmentlar -> segvideo (video-only)."""
    N = max(2, int(round(max(0.4, dur) * FPS)))
    times = sorted({min(N - 1, max(0, int(round(l["t"] * FPS))))
                    for l in fulls if l["t"] < dur - 0.05})
    bounds = [0] + [f for f in times if 0 < f < N] + [N]
    parts, part_frames = [], []
    motion = str((vis.get("motion") or "zoom_in")).lower()
    for k in range(len(bounds) - 1):
        f0, f1 = bounds[k], bounds[k + 1]
        n = f1 - f0
        if n < 1:
            continue
        active = [l["path"] for l in fulls if int(round(l["t"] * FPS)) <= f0]
        png = _compose_state(vis["base"], active, work, f"{i:02d}_{k}")
        sd = n / FPS
        xexpr, yexpr = _pan_xy(motion, N, f0)
        vf = (
            "scale=2160:3840:force_original_aspect_ratio=increase,"
            "crop=2160:3840,"
            f"zoompan=z={_zexpr(vis.get('zs', 1.05), vis.get('ze', 1.30), N, f0, [p for p in punches if f0 <= p < f1], motion)}"
            f":d=1:x={xexpr}:y={yexpr}"
            f":s={W}x{H}:fps={FPS},setsar=1"
        )
        vf += ",format=yuv420p"
        vf = vf.replace("OSDUR", f"{style.ONSCREEN_MAX_DUR:.2f}") \
               .replace("F0SEC", f"{f0 / FPS:.3f}")
        part = os.path.join(work, f"part_{i:02d}_{k}.mp4")
        _run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS),
              "-t", f"{sd + 0.05:.3f}", "-i", png,
              "-vf", vf, "-frames:v", str(n), "-r", str(FPS),
              "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF,
              "-pix_fmt", "yuv420p", "-an", part])
        parts.append(part)
        part_frames.append(n)
    segv = os.path.join(work, f"segvideo_{i:02d}.mp4")
    if len(parts) == 1:
        os.replace(parts[0], segv)
        return segv
    # v10.1: holatlar orasida CROSSFADE — bayroq/label reveal yumshoq
    X = 0.22
    min_sd = min(part_frames) / FPS
    if min_sd < 0.45:                       # juda qisqa part -> qattiq kesish
        lst = segv + ".txt"
        with open(lst, "w") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
              "-c", "copy", segv])
        return segv
    inputs = []
    for p in parts:
        inputs += ["-i", p]
    fc, prev, total = [], "[0:v]", part_frames[0] / FPS
    for k in range(1, len(parts)):
        off = total - X
        fc.append(f"{prev}[{k}:v]xfade=transition=fade:"
                  f"duration={X:.2f}:offset={off:.3f}[x{k}]")
        prev = f"[x{k}]"
        total += part_frames[k] / FPS - X
    _run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc),
          "-map", prev, "-c:v", "libx264", "-preset", "veryfast", "-crf",
          CRF, "-pix_fmt", "yuv420p", "-an", segv])
    return segv


def _render_broll(paths, dur, out):
    """Stock sahna: klip har <=2.5s da almashadi (doc P3: bitta klip
    <=2.5s), har biriga bir xil navy-teal grade (doc P1).
    -> (out, slot_cut_times)"""
    if isinstance(paths, str):
        paths = [paths]
    slot = style.CLIP_MAX_S
    n_slots = max(1, int(math.ceil(dur / slot - 1e-6)))
    parts, cuts = [], []
    for k in range(n_slots):
        t0 = k * slot
        sd = min(slot, dur - t0)
        if sd <= 0.05:
            break
        src = paths[k % len(paths)]
        # har slot boshqa in-point (bir klip takrorlansa ham har xil ko'rinadi)
        off = (k * 1.3) % max(0.5, _probe(src) - 1.0) if len(paths) == 1 else 0.0
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},{style.GRADE_STOCK},fps={FPS},setsar=1,"
              f"format=yuv420p")
        part = out.replace(".mp4", f"_{k}.mp4")
        _run(["ffmpeg", "-y", "-ss", f"{off:.2f}", "-t", f"{sd + 0.03:.3f}",
              "-i", src, "-vf", vf, "-frames:v", str(int(sd * FPS) + 2),
              "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
              "-crf", CRF, "-an", part])
        parts.append(part)
        if k > 0:
            cuts.append(round(t0, 3))
    if len(parts) == 1:
        os.replace(parts[0], out)
    else:
        lst = out + ".txt"
        with open(lst, "w") as f:
            for p in parts:
                f.write(f"file '{p}'\n")
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
              "-c", "copy", out])
    return out, cuts


def _screen_fc(screens, dur, sub_y=None):
    """v11 (V2-1): ZONALI joylashtirish.
    - ikonka/strelka: ZONA C qatori (y=1430), bir nechtasi bo'lsa X bo'ylab
      yoyiladi (bir-biriga tegishmaydi);
    - pin: xarita koordinatasida (bias bilan yuqorida), ZONA B'ga tushsa
      avtomatik siljiydi;
    - label: xarita koordinatasida, ekranda TO'LIQ, ZONA B'dan tashqarida.
    -> (inputs, fc, last, boxes); boxes = (x, y, s, vx, vy, vw, vh)
    (to'liq quti + ko'rinadigan quti)."""
    inputs, fc, last, boxes = [], [], "[0:v]", []
    B0, B1 = (sub_y - 80, sub_y + 80) if sub_y else (None, None)
    # ko'rinadigan quti (kvadrat kanvas markazidagi grafika ulushi)
    VIS = {"icon": (0.10, 0.10, 0.80, 0.80),
           "arrow": (0.10, 0.10, 0.80, 0.80),
           "pin": (0.08, 0.08, 0.84, 0.84),
           "label": (0.06, 0.36, 0.88, 0.28)}
    kinds = [str(ly.get("kind") or "") for ly in screens[:4]]
    n_stick = sum(1 for k in kinds if k in ("icon", "arrow"))
    i_stick = 0
    for k, ly in enumerate(screens[:4]):
        t0 = float(ly.get("t", 0.2))
        px, py = ly.get("pos") or (0.5, 0.35)
        kind = kinds[k]
        S = 420 if kind == "label" else 380 if kind == "arrow" else 340
        half = S // 2
        if kind in ("icon", "arrow"):
            # ZONA C: bitta qatorda, X bo'ylab yoyilgan
            S = 320
            cx = 540 + (i_stick - (n_stick - 1) / 2.0) * 380
            i_stick += 1
            X = max(20, min(W - S - 20, int(cx) - S // 2))
            Y = style.ZONE_C[0] + 10
        elif isinstance(px, (int, float)) and px <= 1.0:     # nisbiy
            X = max(20, min(W - S - 20, int(px * W) - half))
            Y = max(90, min(H - S - 160, int(py * H) - half))
        else:                                              # geo canvas px
            X = max(20, min(W - S - 20, int(px * W / 1440.0) - half))
            Y = max(90, min(H - S - 160, int(py * H / 2560.0) - half))
        # ko'rinadigan quti
        fx, fy, fw, fh = VIS.get(kind, (0.1, 0.1, 0.8, 0.8))
        # ZONA B (subtitr) bilan kesishsa - pin/label siljiydi
        if kind in ("pin", "label") and B0 is not None:
            vx, vy = X + int(S * fx), Y + int(S * fy)
            vw, vh = int(S * fw), int(S * fh)
            if vy < B1 and vy + vh > B0:
                up = B0 - 8 - vh - int(S * fy)          # tepaga
                down = B1 + 8 - int(S * fy)             # pastga
                if up >= 90:
                    Y = up
                elif down + int(S * (fy + fh)) <= H - 60:
                    Y = down
        # pin/label ekranda TO'LIQ (qirqilmasin)
        X = max(6, min(W - S - 6, X))
        Y = max(6, min(H - S - 6, Y))
        vx, vy = X + int(S * fx), Y + int(S * fy)
        boxes.append((int(X), int(Y), int(S),
                      int(vx), int(vy), int(S * fw), int(S * fh)))
        inputs += ["-loop", "1", "-framerate", str(FPS),
                   "-t", f"{max(0.5, dur):.2f}", "-i", ly["path"]]
        fc.append(f"[{k + 1}:v]scale={S}:{S},format=rgba,"
                  f"fade=t=in:st={t0:.2f}:d=0.15:alpha=1[ic{k}]")
        fc.append(f"{last}[ic{k}]overlay=x={X}:"
                  f"y='{Y} - (1 - min(1,(t-{t0:.2f})/0.20))*80':"
                  f"enable='gte(t,{t0:.2f})'[v{k}]")
        last = f"[v{k}]"
    return inputs, fc, last, boxes


def _static_title(script):
    """v11 (V2-1): ZONA A uchun bitta statik sarlavha.
    Manba: headline (kuchli model skriptida) -> place -> hook so'zlari."""
    import re as _re
    import unicodedata as _ud
    t = str(script.get("headline") or script.get("place") or "").strip()
    if not t:
        q = str(script.get("question") or script.get("title") or "")
        t = " ".join(q.split()[:4])
    # diakritikani translit qilib keyin tozalash (u -> u, emas: Bsingen)
    t = "".join(c for c in _ud.normalize("NFKD", t)
                if not _ud.combining(c))
    t = _re.sub(r"[^A-Za-z0-9 .'\-]", "", t).strip().upper()
    return t[:30].strip()


def _title_fc(fc, last, title, seg_i, words, dur, work, chunk_ts=None):
    """ZONA A statik sarlavhasi: oq matn, qora kontur, opacity 100%.
    Subtitrda sarlavha so'zi ko'rinayotganda sarlavha yashirinadi
    (V2-1 qoida: dublikat = 0). Yashirish BUTUN CHUNK davomida —
    so'z tugasa ham chunk (masalan "CANADA RIGHT NOW?") o'qiladi.
    -> box dict | None."""
    from .captions import text_width, fit_font
    txt = str(title or "").strip()
    if not txt:
        return None
    # V2: sarlavha >=72px KAFOLATI — sig'masa oxirgi so'zlar tashlanadi
    # (bir so'z qolsa ham 72px+; "AFRICA'S STRAIGHT LINES" -> 64px YO'Q)
    size = 104
    while size > 72 and text_width(txt, size) > style.TITLE_MAX_W:
        size -= 8
    while (size <= 72 and text_width(txt, size) > style.TITLE_MAX_W
           and " " in txt):
        txt = " ".join(txt.split()[:-1])     # oxirgi so'zni tashla
        size = 104
        while size > 72 and text_width(txt, size) > style.TITLE_MAX_W:
            size -= 8
    if text_width(txt, size) > style.TITLE_MAX_W:
        size = fit_font(txt, 104, style.TITLE_MAX_W)
    toks = set()
    for w in txt.split():
        w_ = w.strip(".,!?\"'").lower()
        if len(w_) >= 4:
            toks.add(w_)
    hide = []
    if toks:
        # chunk chegaralari: chunk_ts (boshlanish vaqtlari) + oxirgi chegar
        cts = sorted({max(0.0, float(c)) for c in (chunk_ts or [])})
        bounds = cts + [dur]
        wds = [(str(w).strip(".,!?\"'").lower(), float(t0), float(t1))
               for (w, t0, t1) in (words or [])]
        for ci, c0 in enumerate(bounds[:-1]):
            c1 = bounds[ci + 1]
            # chunk ichida sarlavha tokeni bormi?
            if any(w in toks and t0 >= c0 - 0.02 and t0 < c1
                   for (w, t0, t1) in wds):
                a = max(0.0, c0 - 0.10)
                b = (min(dur, c1 + 0.10) if ci + 1 < len(cts)
                     else min(dur, c1 + 0.25))
                hide.append((a, b))
        # kesishgan oynalarni birlashtirish
        hide.sort()
        merged = []
        for (a, b) in hide:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        hide = merged
    alpha = "min(1,t/0.25)" if seg_i == 0 else "1"
    for (a, b) in hide[:8]:
        # 0.12s FADE — keskin o'chib-yonish (miltillash) yo'q
        alpha += (f"*(1-clip((t-{a:.2f})/0.12,0,1)"
                  f"+clip((t-{b:.2f})/0.12,0,1))")
    cy = (style.ZONE_A[0] + style.ZONE_A[1]) // 2
    tfp = os.path.join(work, f"ttl_{seg_i:02d}.txt")
    with open(tfp, "w", encoding="utf-8") as f:
        f.write(txt)
    fc.append(
        f"{last}drawtext=fontfile={FONT_DIR}/Montserrat-ExtraBold.ttf"
        f":textfile={tfp}:fontcolor=white:borderw=6:bordercolor=black"
        f":shadowcolor=black@0.35:shadowx=3:shadowy=3:fontsize={size}"
        f":alpha='{alpha}'"
        f":x=(w-text_w)/2:y=({cy}-th/2)[vt{seg_i}]")
    w_ = int(text_width(txt, size))
    return {"x": max(80, (1080 - w_) // 2), "y": cy - (size + 16) // 2,
            "w": min(w_, 940), "h": size + 16, "size": size, "text": txt}



def render(cfg, script, items, work):
    """items: [{scene, visual{type,base,path,paths,zs,ze}, layers, punches,
               audio, words, dur}] -> final.mp4 (+ work/events.json, doc P4)"""
    os.makedirs(work, exist_ok=True)
    n = len(items)
    seg_paths = []
    ev_log = []                     # doc P4: events.json
    segments = []
    TTL_TEXT = _static_title(script)
    seg_start = 0.0
    for i, it in enumerate(items):
        vis = it["visual"]
        dur = it["dur"]
        scene = it["scene"]
        mode = "stock" if vis["type"] == "clip" else "map"
        layers = it.get("layers", [])
        punches = [p for p in it.get("punches", []) if 1 < p < int(dur * FPS)]
        fulls = [l for l in layers if l.get("full")]
        screens = [l for l in layers if not l.get("full")]

        ev_log.append({"t": round(seg_start, 3), "type": "cut",
                       "seg": i, "mode": mode})
        if mode == "map":
            _m = scene.get("map") or {}
            ev_log.append({"t": round(seg_start, 3), "type": "map_view",
                           "seg": i,
                           "lat": round(float(_m.get("lat", 0)), 2),
                           "lon": round(float(_m.get("lon", 0)), 2),
                           "z": int(_m.get("zoom_level", 5))})
        if vis["type"] == "map":
            base = _render_map_states(vis, fulls, punches, dur,
                                      "", work, i)
        else:
            base = os.path.join(work, f"vis_{i:02d}.mp4")
            paths = vis.get("paths") or [vis["path"]]
            base, slot_cuts = _render_broll(paths, dur, base)
            for c in slot_cuts:
                ev_log.append({"t": round(seg_start + c, 3),
                               "type": "cut", "seg": i, "mode": mode})

        ass, chunk_ts = captions.build_scene_ass(
            cfg, scene, it["words"], dur,
            os.path.join(work, f"subs_{i:02d}.ass"))

        for l in layers:
            _e = {"t": round(seg_start + l["t"], 3),
                  "type": str(l.get("kind", "event")),
                  "seg": i,
                  "word_t": round(seg_start + l.get("word_t",
                                                    l["t"]), 3)}
            if l.get("iso") is not None:
                _e["iso"] = str(l["iso"])
            if l.get("area") is not None:
                _e["area"] = l["area"]  # V2-2: fill ekran maydon nisbati
            if l.get("light"):
                _e["light"] = True      # V2-2: kontur+tint rejimi
            ev_log.append(_e)
        for p in punches:
            ev_log.append({"t": round(seg_start + p / FPS, 3),
                           "type": "zoom_punch", "seg": i})
        if vis["type"] == "map":
            # v7: xarita sahnasi uzluksiz zoompan harakati — har 1.4s da
            # motion hodisasi (subtitr yo'q, dinamizm shu bilan ta'minlanadi)
            for mt in range(1, max(1, int((dur - 0.4) / 1.4)) + 1):
                ev_log.append({"t": round(seg_start + mt * 1.4, 3),
                               "type": "zoom_motion", "seg": i})
        for ct in chunk_ts:
            ev_log.append({"t": round(seg_start + ct, 3),
                           "type": "caption", "seg": i})

        last_word_end = max((w[2] for w in (it.get("words") or [(-1, 0, 0)])),
                            default=0.0)
        segments.append({"i": i, "mode": mode, "t0": round(seg_start, 3),
                         "t1": round(seg_start + dur, 3),
                         "voice_end": round(seg_start + last_word_end, 3),
                         "voice": " ".join(
                             str(w[0]) for w in (it.get("words") or []))})
        seg_start += dur

        from .captions import caption_y
        sub_y = caption_y(cfg, mode)
        seg_t0 = seg_start - dur          # segment boshi (seg_start allaqachon ++)
        sin, fc, last, scr_boxes = _screen_fc(screens, dur, sub_y)
        for ly, (bx, by, bs, vx, vy, vw, vh) in zip(screens[:4], scr_boxes):
            ev_log.append({"t": round(seg_t0 + float(ly.get("t", 0.2)), 3),
                           "type": str(ly.get("kind") or "screen"), "seg": i,
                           "x": bx, "y": by, "s": bs,
                           "vx": vx, "vy": vy, "vw": vw, "vh": vh})
        a_idx = len(screens) + 1
        fc.append(f"{last}ass='{ass}'[assv]")
        # v11 (V2-1): ZONA A — bitta STATIK sarlavha butun video davomida
        # (har segmentda bir xil — kesishlarda uzluksiz). Eski har-sahna
        # OSD yorlig'i va MID matn o'lib, matn dublikati yo'qoldi.
        ttl_box = _title_fc(fc, "[assv]", TTL_TEXT, i,
                            it.get("words") or [], dur, work,
                            chunk_ts=chunk_ts)
        if ttl_box:
            ev_log.append({"t": round(seg_start - dur, 3), "type": "title",
                           "seg": i, "x": ttl_box["x"], "y": ttl_box["y"],
                           "w": ttl_box["w"], "h": ttl_box["h"],
                           "size": ttl_box["size"], "text": ttl_box["text"]})
        tail = TAIL if i == n - 1 else 0.0
        # oxirgi segmentda video ham tail'gacha yetamiz (oxirgi kadr
        # ushlab turiladi — pleyerlarga mustahkam)
        tpad = (f",tpad=stop_mode=clone:stop_duration={tail:.2f}"
                if tail > 0 else "")
        _vsrc = f"[vt{i}]" if ttl_box else "[assv]"
        fc.append(f"{_vsrc}{style.GRADE_ALL}{tpad},format=yuv420p[vout]")
        # audio BUTUN segment uzunligiga padlanadi (dur pad-sukunatni
        # o'z ichiga oladi!) — aks holda concat'da audio videodan
        # qolqib, A/V desync bo'ladi (run 15/16 o'lchovlarining ildizi)
        fc.append(f"[{a_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"apad=whole_dur={dur + tail + 0.05:.3f}[af]")

        seg = os.path.join(work, f"seg_{i:02d}.mp4")
        _run(["ffmpeg", "-y", "-i", base, *sin, "-i", it["audio"],
              "-filter_complex", ";".join(fc),
              "-map", "[vout]", "-map", "[af]",
              "-t", f"{dur + tail:.3f}",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF,
              "-pix_fmt", "yuv420p", "-r", str(FPS),
              "-c:a", "aac", "-b:a", "192k", "-ar", "48000", seg])
        seg_paths.append(seg)
        print(f"[render] segment {i + 1}/{n} ({vis['type']}, {dur:.2f}s, "
              f"{len(fulls)} full, {len(screens)} ekran, {len(punches)} punch)")

    lst = os.path.join(work, "concat.txt")
    with open(lst, "w") as f:
        for p in seg_paths:
            f.write(f"file '{p}'\n")
    joined = os.path.join(work, "joined.mp4")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
          "-c", "copy", joined])

    # doc P4: events.json (hodisa vaqti + so'z vaqti)
    ev_log.sort(key=lambda e: e["t"])
    import json as _j
    with open(os.path.join(work, "events.json"), "w", encoding="utf-8") as f:
        _j.dump({"fps": FPS, "engine": (items[0].get("engine", "edge")
                                        if items else "edge"),
                 "voice_end": segments[-1]["voice_end"] if segments else 0.0,
                 "segments": segments, "events": ev_log}, f, indent=1)

    out = os.path.join(work, "final.mp4")
    _mix_music(cfg, joined, out)
    _verify(out, cfg)
    return out


def _mix_music(cfg, joined, out, mus_vol=None):
    """Doc C4/P2: voice zanjiri (highpass+compressor+presence+limiter)
    -> musiqa -18dB + sidechain ducking + amix normalize=0 + 1s fade-out
    -> loudnorm -15 mix'dan KEYIN."""
    if mus_vol is None:
        mus_vol = float(cfg.get("sfx", {}).get("music_volume", 0.125))
    music = cfg.get("sfx", {}).get("music")
    if not (music and os.path.exists(str(music))):
        try:
            from . import sfx as _sfx
            music = _sfx.ensure_music(os.path.dirname(joined) or ".")
        except Exception as e:
            print("[render] musiqa topilmadi:", e)
            music = None
    music_on = bool(cfg.get("sfx", {}).get("music_enabled", True))
    d = _probe(joined)
    if music_on and music:
        try:
            # A) mix (voice zanjiri + musiqa sidechain) -> wav (loudnorm'siz)
            fc = (
                f"[1:a]volume={mus_vol},atrim=0:{d:.2f},"
                f"afade=t=out:st={max(0.0, d - 1.0):.2f}:d=1.0,"
                f"asetpts=PTS-STARTPTS,aresample=48000,"
                f"aformat=channel_layouts=stereo[m];"
                # doc P2 voice zanjiri: HPF -> kompressor -> presence -> limiter
                f"[0:a]highpass=f=80,"
                f"acompressor=threshold=0.10:ratio=4:attack=4:release=70,"
                f"equalizer=f=3500:t=q:w=1:g=3,alimiter=limit=0.95,"
                f"asplit=2[v1][v2];"
                f"[m][v2]sidechaincompress=threshold=0.03:ratio=8:"
                f"attack=20:release=300[md];"
                f"[v1][md]amix=inputs=2:duration=first:normalize=0,"
                f"atrim=0:{max(0.1, d - TAIL):.3f}[mix]"
            )
            mixw = os.path.join(os.path.dirname(out) or ".", "mix_tmp.wav")
            _run(["ffmpeg", "-y", "-i", joined, "-stream_loop", "-1",
                  "-i", str(music), "-filter_complex", fc,
                  "-map", "[mix]", "-ar", "48000", "-ac", "2", mixw])
            # B) MASTERING: o'lchangan STATIK gain + brickwall limiter
            # (doc P2 maqsadi: I=-15, TP<=-1.5, bir marta, oxirida).
            # Dinamik loudnorm jim pad'larni ko'tarib yuborardi (run
            # 15/16: musiqa darajasi o'zgarmasa ham oyna -18.4); statik
            # gain pad nisbatlarini saqlaydi -> musiqa o'lchovi
            # deterministik bo'ladi.
            meas = _ebur128(mixw)
            gain = max(-12.0, min(12.0, -14.0 - meas["I"]))
            print(f"[render] master: I={meas['I']:.1f} TP={meas['TP']:.1f} "
                  f"-> gain {gain:+.2f} dB + limiter")
            _run(["ffmpeg", "-y", "-i", joined, "-i", mixw,
                  "-filter_complex",
                  f"[1:a]volume={gain:.2f}dB,"
                  f"alimiter=limit=0.794:level=false:attack=5,"
                  f"alimiter=limit=0.780:level=false:attack=1:release=25,"
                  f"apad=pad_dur={TAIL + 0.1:.2f},"
                  f"atrim=0:{d:.3f}[a]",
                  "-map", "0:v", "-map", "[a]", "-t", f"{d:.3f}",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                  "-movflags", "+faststart", out])
            return
        except Exception as e:
            print("[render] musiqa mix xatosi:", e)
    else:
        # v7 immersive (referens uslubi): MUSIQA YO'Q — faqat ovoz zanjiri
        try:
            fc = (
                f"[0:a]highpass=f=80,"
                f"acompressor=threshold=0.10:ratio=4:attack=4:release=70,"
                f"equalizer=f=3500:t=q:w=1:g=3,alimiter=limit=0.95,"
                f"atrim=0:{max(0.1, d - TAIL):.3f}[mix]"
            )
            mixw = os.path.join(os.path.dirname(out) or ".", "mix_tmp.wav")
            _run(["ffmpeg", "-y", "-i", joined, "-filter_complex", fc,
                  "-map", "[mix]", "-ar", "48000", "-ac", "2", mixw])
            meas = _ebur128(mixw)
            gain = max(-12.0, min(12.0, -14.0 - meas["I"]))
            print(f"[render] master (musiqasiz): I={meas['I']:.1f} "
                  f"TP={meas['TP']:.1f} -> gain {gain:+.2f} dB + limiter")
            _run(["ffmpeg", "-y", "-i", joined, "-i", mixw,
                  "-filter_complex",
                  f"[1:a]volume={gain:.2f}dB,"
                  f"alimiter=limit=0.794:level=false:attack=5,"
                  f"alimiter=limit=0.780:level=false:attack=1:release=25,"
                  f"apad=pad_dur={TAIL + 0.1:.2f},"
                  f"atrim=0:{d:.3f}[a]",
                  "-map", "0:v", "-map", "[a]", "-t", f"{d:.3f}",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                  "-movflags", "+faststart", out])
            return
        except Exception as e:
            print("[render] musiqasiz master xatosi:", e)
    _run(["ffmpeg", "-y", "-i", joined,
          "-af", "loudnorm=I=-14:TP=-1.0:LRA=9",   # v10: qo'llanma -14 LUFS
          "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
          "-movflags", "+faststart", out])


def remix(cfg, work_dir, out, mus_vol=None):
    """QC retry uchun: faqat audio remiks (joined.mp4 saqlanadi)."""
    joined = os.path.join(work_dir, "joined.mp4")
    if not os.path.exists(joined):
        raise RuntimeError("remix: joined.mp4 yo'q")
    _mix_music(cfg, joined, out, mus_vol=mus_vol)
    _verify(out, cfg)
    return out


def _ebur128(path):
    """Ikki passli loudnorm uchun o'lchov (I/TP/LRA/threshold)."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", path, "-af",
         "ebur128=peak=true:framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True, timeout=180)
    o = r.stderr
    import re as _re
    I = float(_re.findall(r"I:\s+(-?[\d.]+) LUFS", o)[-1])
    TP = float(_re.findall(r"Peak:\s+(-?[\d.]+) dBFS", o)[-1])
    LRA = float(_re.findall(r"LRA:\s+(-?[\d.]+) LU", o)[-1])
    th = _re.findall(r"Threshold:\s+(-?[\d.]+) LUFS", o)
    thresh = float(th[-1]) if th else (I - 10.0)
    return {"I": I, "TP": TP, "LRA": LRA, "thresh": thresh}


def _probe(p):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", p], capture_output=True, text=True, timeout=30)
    return float(r.stdout.strip())


def _verify(out, cfg):
    import json as _json
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-show_entries",
         "format=duration", "-of", "json", out],
        capture_output=True, text=True, timeout=30)
    meta = _json.loads(r.stdout or "{}")
    st = (meta.get("streams") or [{}])[0]
    w, h = int(st.get("width", 0)), int(st.get("height", 0))
    d = float(meta.get("format", {}).get("duration", 0))
    if (w, h) != (W, H):
        raise RuntimeError(f"O'lcham xato: {w}x{h}, kutilgan {W}x{H}")
    mx = float(cfg.get("video", {}).get("max_duration", 40))
    mn = float(cfg.get("video", {}).get("min_duration", 35))
    if not (mn - 0.8 <= d <= mx + 0.8):
        raise RuntimeError(f"Davomiylik {d:.1f}s — [{mn}..{mx}] ichida emas")
    print(f"[render] final OK: {W}x{H}, {d:.2f}s")
