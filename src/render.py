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
import os
import subprocess

from PIL import Image

from . import captions

W, H = 1080, 1920
FPS = 30
TAIL = 0.5          # doc C3: video = ovoz + 0.5s
CRF = "18"
FONT_DIR = "/usr/share/fonts/truetype/montserrat"


def _run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        print("[render] CMD:", " ".join(cmd[:14]), "...")
        print("[render] XATO:", r.stderr[-600:])
        raise RuntimeError(f"ffmpeg xato: {r.returncode}")


def _zexpr(zs, ze, n_total, f0, punches):
    """Global frame hisobidan zoom (+ punch gauss)."""
    z = f"'{zs:.4f}+({ze:.4f}-{zs:.4f})*min({f0}+on,{n_total})/{n_total}'"
    for p in punches:
        z += f"+0.055*exp(-(on-{p}) * (on-{p})/45)"
    return z


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
    img.convert("RGB").save(out, quality=92)
    return out


def _render_map_states(vis, fulls, punches, dur, on_screen, work, i):
    """A-bosqich: holat-subsegmentlar -> segvideo (video-only)."""
    N = max(2, int(round(max(0.4, dur) * FPS)))
    times = sorted({min(N - 1, max(0, int(round(l["t"] * FPS))))
                    for l in fulls if l["t"] < dur - 0.05})
    bounds = [0] + [f for f in times if 0 < f < N] + [N]
    parts = []
    for k in range(len(bounds) - 1):
        f0, f1 = bounds[k], bounds[k + 1]
        n = f1 - f0
        if n < 1:
            continue
        active = [l["path"] for l in fulls if int(round(l["t"] * FPS)) <= f0]
        png = _compose_state(vis["base"], active, work, f"{i:02d}_{k}")
        sd = n / FPS
        vf = (
            "scale=2160:3840:force_original_aspect_ratio=increase,"
            "crop=2160:3840,"
            f"zoompan=z={_zexpr(vis.get('zs', 1.05), vis.get('ze', 1.30), N, f0, [p for p in punches if f0 <= p < f1])}"
            ":d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={W}x{H}:fps={FPS},setsar=1"
        )
        if on_screen:
            tf = os.path.join(work, f"os_{i:02d}_{k}.txt")
            with open(tf, "w", encoding="utf-8") as f:
                f.write(on_screen[:40])
            vf += (f",drawtext=fontfile={FONT_DIR}/Montserrat-ExtraBold.ttf"
                   f":textfile={tf}:fontcolor=white:borderw=6:bordercolor=black"
                   f":fontsize=62:x=(w-text_w)/2:y=104")
        vf += ",format=yuv420p"
        part = os.path.join(work, f"part_{i:02d}_{k}.mp4")
        _run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS),
              "-t", f"{sd + 0.05:.3f}", "-i", png,
              "-vf", vf, "-frames:v", str(n), "-r", str(FPS),
              "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF,
              "-pix_fmt", "yuv420p", "-an", part])
        parts.append(part)
    segv = os.path.join(work, f"segvideo_{i:02d}.mp4")
    lst = segv + ".txt"
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    if len(parts) == 1:
        os.replace(parts[0], segv)
    else:
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
              "-c", "copy", segv])
    return segv


def _render_broll(path, dur, out):
    def probe_dur(p):
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "csv=p=0", p],
                capture_output=True, text=True, timeout=30)
            return float(r.stdout.strip())
        except Exception:
            return 0.0

    cd = probe_dur(path)
    pre = ["-stream_loop", "-1", "-t", f"{dur:.2f}"] if cd < dur + 0.2 else []
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},fps={FPS},setsar=1,format=yuv420p")
    _run(["ffmpeg", "-y", *pre, "-i", path, "-vf", vf,
          "-t", f"{dur:.2f}", "-r", str(FPS),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF, "-an", out])


def _screen_fc(screens, dur):
    """Screen-space qatlamlar: 260px, alpha fade + y-siljish."""
    inputs, fc, last = [], [], "[0:v]"
    for k, ly in enumerate(screens[:4]):
        t0 = float(ly.get("t", 0.2))
        px, py = ly.get("pos") or (0.5, 0.35)
        if isinstance(px, (int, float)) and px <= 1.0:     # nisbiy (0..1)
            X = max(40, min(W - 300, int(px * W) - 130))
            Y = max(120, min(H - 400, int(py * H) - 130))
        else:                                              # geo canvas px
            X = max(40, min(W - 300, int(px * W / 1440.0) - 130))
            Y = max(120, min(H - 400, int(py * H / 2560.0) - 130))
        inputs += ["-loop", "1", "-framerate", str(FPS),
                   "-t", f"{max(0.5, dur):.2f}", "-i", ly["path"]]
        fc.append(f"[{k + 1}:v]scale=260:260,format=rgba,"
                  f"fade=t=in:st={t0:.2f}:d=0.15:alpha=1[ic{k}]")
        fc.append(f"{last}[ic{k}]overlay=x={X}:"
                  f"y='{Y} - (1 - min(1,(t-{t0:.2f})/0.20))*80':"
                  f"enable='gte(t,{t0:.2f})'[v{k}]")
        last = f"[v{k}]"
    return inputs, fc, last


def render(cfg, script, items, work):
    """items: [{scene, visual{type,base,path,zs,ze}, layers, punches,
               audio, words, dur}]"""
    os.makedirs(work, exist_ok=True)
    n = len(items)
    seg_paths = []
    for i, it in enumerate(items):
        vis = it["visual"]
        dur = it["dur"]
        layers = it.get("layers", [])
        punches = [p for p in it.get("punches", []) if 1 < p < int(dur * FPS)]
        fulls = [l for l in layers if l.get("full")]
        screens = [l for l in layers if not l.get("full")]

        if vis["type"] == "map":
            base = _render_map_states(vis, fulls, punches, dur,
                                      it["scene"].get("on_screen", ""), work, i)
        else:
            base = os.path.join(work, f"vis_{i:02d}.mp4")
            _render_broll(vis["path"], dur, base)

        ass = captions.build_scene_ass(
            cfg, it["scene"], it["words"], dur,
            os.path.join(work, f"subs_{i:02d}.ass"))

        sin, fc, last = _screen_fc(screens, dur)
        a_idx = len(screens) + 1
        fc.append(f"{last}ass='{ass}'[vout]")
        tail = TAIL if i == n - 1 else 0.0
        fc.append(f"[{a_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"apad=pad_dur={tail + 0.05:.2f}[af]")

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

    out = os.path.join(work, "final.mp4")
    _mix_music(cfg, joined, out)
    _verify(out, cfg)
    return out


def _mix_music(cfg, joined, out):
    """Doc C4: musiqa -18dB + sidechain ducking + amix normalize=0 +
    1s fade-out; loudnorm -15 mix'dan KEYIN."""
    mus_vol = float(cfg.get("sfx", {}).get("music_volume", 0.125))
    music = cfg.get("sfx", {}).get("music")
    if not (music and os.path.exists(str(music))):
        try:
            from . import sfx as _sfx
            music = _sfx.ensure_music(os.path.dirname(joined) or ".")
        except Exception as e:
            print("[render] musiqa topilmadi:", e)
            music = None
    d = _probe(joined)
    if music:
        try:
            fc = (
                f"[1:a]volume={mus_vol},atrim=0:{d:.2f},"
                f"afade=t=out:st={max(0.0, d - 1.0):.2f}:d=1.0,"
                f"asetpts=PTS-STARTPTS,aresample=48000,"
                f"aformat=channel_layouts=stereo[m];"
                f"[0:a]asplit=2[v1][v2];"
                f"[m][v2]sidechaincompress=threshold=0.03:ratio=8:"
                f"attack=20:release=300[md];"
                f"[v1][md]amix=inputs=2:duration=first:normalize=0[mix];"
                # dinamik loudnorm jim tailni ko'tarib yuboradi -> tail'ni
                # loudnorm'dan KEYIN qayta qo'shamiz (doc C3: oxiri jim)
                f"[mix]atrim=0:{max(0.1, d - TAIL):.3f},"
                f"loudnorm=I=-15:TP=-1.5:LRA=7,"
                f"apad=pad_dur={TAIL + 0.1:.2f},atrim=0:{d:.3f}[a]"
            )
            _run(["ffmpeg", "-y", "-i", joined, "-stream_loop", "-1",
                  "-i", str(music), "-filter_complex", fc,
                  "-map", "0:v", "-map", "[a]", "-t", f"{d:.3f}",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                  "-movflags", "+faststart", out])
            return
        except Exception as e:
            print("[render] musiqa mix xatosi:", e)
    _run(["ffmpeg", "-y", "-i", joined,
          "-af", "loudnorm=I=-15:TP=-1.5:LRA=7",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
          "-movflags", "+faststart", out])


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
