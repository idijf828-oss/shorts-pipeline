"""V3 render: xarita kameralari + ikonka overlaylari + markaziy subtitr.

Segment turlari:
  map   -> geo.compose_map() PNG + ffmpeg zoompan (zs->ze, geo dan)
  clip  -> stock b-roll (faqat fallback_broll_query bo'lsa; media.py)

Har segment: [vizual] -> ikonkalar (fade+slide+enable) -> ass subtitr -> audio.
Yakuniy: concat -> musika (-18dB, ducking) -> loudnorm -15 -> +faststart.
Oxirgi segment +0.3s quyruq (apad+tpad mantiqi -t orqali): oxirgi so'z kesilmaydi.
"""
import os
import subprocess

from . import captions

W, H = 1080, 1920
FPS = 30
TAIL = 0.3          # oxirgi so'zdan keyingi minimal bo'shliq (loop uchun ham)
GAP = 0.15          # segment audio oxiri va keyingi boshlanish orasi
CRF = "18"
ATTRIB = "Imagery (c) Esri, Maxar, Earthstar Geographics"
FONT_DIR = "/usr/share/fonts/truetype/montserrat"


def _run(cmd, timeout=600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        print("[render] CMD:", " ".join(cmd[:14]), "...")
        print("[render] XATO:", r.stderr[-600:])
        raise RuntimeError(f"ffmpeg xato: {r.returncode}")


def _render_map_anim(png, zs, ze, dur, out, label=""):
    """Bitta statik xarita PNG -> silliq zoom kamera (zs->ze).

    Yorliq va atributsiya drawtext bilan QAT'IY pozitsiyada chiqadi —
    zoom qancha chuqur bo'lsa ham kadr ichida qoladi.
    """
    d = max(0.4, dur)
    frames = int(d * FPS)
    vf = (
        "scale=2160:3840:force_original_aspect_ratio=increase,"
        "crop=2160:3840,"
        f"zoompan=z='{zs:.4f}+({ze:.4f}-{zs:.4f})*min(on,{frames})/{frames}'"
        ":d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s={W}x{H}:fps={FPS},setsar=1"
    )
    if label:
        lf = out.replace(".mp4", "_label.txt")
        with open(lf, "w", encoding="utf-8") as f:
            f.write(label.upper()[:24])
        vf += (f",drawtext=fontfile={FONT_DIR}/Montserrat-ExtraBold.ttf"
               f":textfile={lf}:fontcolor=white:borderw=7:bordercolor=black"
               f":fontsize=58:x=(w-text_w)/2:y=88")
    af = os.path.join(os.path.dirname(out) or ".", "attrib.txt")
    with open(af, "w", encoding="utf-8") as f:
        f.write(ATTRIB)
    vf += (f",drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
           f":textfile={af}:fontcolor=white@0.72:borderw=2:bordercolor=black@0.72"
           f":fontsize=20:x=(w-text_w)/2:y=h-30,format=yuv420p")
    _run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS),
          "-t", f"{d + 0.05:.2f}", "-i", png,
          "-vf", vf, "-t", f"{d:.2f}", "-r", str(FPS),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF, "-an", out])


def _render_broll(path, dur, out):
    """Stock klip -> 1080x1920 oyna (qisqa bo'lsa loop)."""
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


def _icon_fc(icons, dur):
    """Ikonka overlaylari: 300px, alpha fade-in + y-siljish + enable."""
    inputs, fc, last = [], [], "[0:v]"
    for k, ic in enumerate(icons[:3]):
        inputs += ["-loop", "1", "-framerate", str(FPS),
                   "-t", f"{max(0.5, dur):.2f}", "-i", ic["path"]]
        t0 = float(ic.get("t", 0.3))
        px, py = ic.get("pos", (0.5, 0.5))
        X = max(60, min(W - 360, int(px * W) - 150))
        Y = max(120, min(H - 420, int(py * H) - 150))
        fc.append(
            f"[{k + 1}:v]scale=300:300,format=rgba,"
            f"fade=t=in:st={t0:.2f}:d=0.12:alpha=1[ic{k}]")
        fc.append(
            f"{last}[ic{k}]overlay=x={X}:"
            f"y='{Y} - (1 - min(1,(t-{t0:.2f})/0.20))*90'"
            f":enable='gte(t,{t0:.2f})'[v{k}]")
        last = f"[v{k}]"
    return inputs, fc, last


def render(cfg, script, items, work):
    """items: [{scene, visual{type,path,zs,ze}, icons[{path,t,pos}], audio, words, dur}]"""
    os.makedirs(work, exist_ok=True)
    n = len(items)
    seg_paths = []

    for i, it in enumerate(items):
        vis = it["visual"]
        dur = it["dur"]
        base = os.path.join(work, f"vis_{i:02d}.mp4")
        if vis["type"] == "map":
            _render_map_anim(vis["path"], vis.get("zs", 1.05),
                             vis.get("ze", 1.30), dur, base,
                             label=vis.get("label", ""))
        else:
            _render_broll(vis["path"], dur, base)

        ass = captions.build_scene_ass(
            cfg, it["scene"], it["words"], dur,
            os.path.join(work, f"subs_{i:02d}.ass"))

        icon_in, fc, last = _icon_fc(it.get("icons", []), dur)
        # input tartibi: [0]=vizual, [1..K]=ikonkalar, [K+1]=audio
        a_idx = len(it.get("icons", [])) + 1

        fc.append(f"{last}ass='{ass}'[vout]")
        tail = TAIL if i == n - 1 else 0.0
        fc.append(f"[{a_idx}:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"apad=pad_dur={tail + 0.05:.2f}[af]")

        seg = os.path.join(work, f"seg_{i:02d}.mp4")
        _run(["ffmpeg", "-y", "-i", base, *icon_in, "-i", it["audio"],
              "-filter_complex", ";".join(fc),
              "-map", "[vout]", "-map", "[af]",
              "-t", f"{dur + tail:.3f}",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", CRF,
              "-pix_fmt", "yuv420p", "-r", str(FPS),
              "-c:a", "aac", "-b:a", "160k", "-ar", "48000", seg])
        seg_paths.append(seg)
        print(f"[render] segment {i + 1}/{n} tayyor ({vis['type']}, "
              f"{dur:.2f}s, {len(it.get('icons', []))} ikonka)")

    # concat
    lst = os.path.join(work, "concat.txt")
    with open(lst, "w") as f:
        for p in seg_paths:
            f.write(f"file '{p}'\n")
    joined = os.path.join(work, "joined.mp4")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
          "-c", "copy", joined])

    # musika + loudnorm
    out = os.path.join(work, "final.mp4")
    _mix_music(cfg, joined, out)
    _verify(out, cfg)
    return out


def _mix_music(cfg, joined, out):
    mus_vol = float(cfg.get("sfx", {}).get("music_volume", 0.125))
    music = cfg.get("sfx", {}).get("music")
    if not (music and os.path.exists(str(music))):
        try:
            from . import sfx as _sfx
            music = _sfx.ensure_music(os.path.dirname(joined) or ".")
        except Exception as e:
            print("[render] musika sintezi o'tkazildi:", e)
            music = None
    if music and os.path.exists(str(music)):
        try:
            fc = (
                f"[1:a]volume={mus_vol},aresample=48000,"
                f"aformat=channel_layouts=stereo[m];"
                f"[0:a]aresample=48000,aformat=channel_layouts=stereo,"
                f"loudnorm=I=-15:TP=-1.5:LRA=11[voice];"
                f"[voice][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                f"alimiter=limit=0.95[aout]"
            )
            _run(["ffmpeg", "-y", "-i", joined, "-i", str(music),
                  "-filter_complex", fc, "-map", "0:v", "-map", "[aout]",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                  "-movflags", "+faststart", out])
            return
        except Exception as e:
            print("[render] musika qo'shib bo'lmadi:", e)
    _run(["ffmpeg", "-y", "-i", joined,
          "-af", "loudnorm=I=-15:TP=-1.5:LRA=11",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
          "-movflags", "+faststart", out])


def _verify(out, cfg):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-show_entries",
         "format=duration", "-of", "json", out],
        capture_output=True, text=True, timeout=30)
    import json as _json
    meta = _json.loads(r.stdout or "{}")
    st = (meta.get("streams") or [{}])[0]
    w, h = int(st.get("width", 0)), int(st.get("height", 0))
    d = float(meta.get("format", {}).get("duration", 0))
    if (w, h) != (W, H):
        raise RuntimeError(f"O'lcham xato: {w}x{h}, kutilgan {W}x{H}")
    mx = float(cfg.get("video", {}).get("max_duration", 30))
    mn = float(cfg.get("video", {}).get("min_duration", 18))
    if not (mn - 0.6 <= d <= mx + 0.6):
        raise RuntimeError(f"Davomiylik {d:.1f}s — [{mn}..{mx}] ichida emas")
    print(f"[render] final OK: {W}x{H}, {d:.2f}s")
