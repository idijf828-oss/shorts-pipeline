"""5-qadam: ffmpeg bilan 1080x1920, 40-50s Shorts'yig'ish.

Har bir sahna: clip/yoki kart + burned-in overlay matn + badge,
keyin ovoz bilan segment -> barcha segmentlar concat -> final.mp4.
"""
import os
import subprocess

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def _font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    raise RuntimeError("ffmpeg drawtext uchun shrift topilmadi "
                       "(Ubuntu'da: sudo apt install fonts-dejavu-core)")


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg xatosi:\n" + r.stderr[-800:])
    return r


def _ffprobe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=30)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _render_scene(i, scene, dur, media_path, audio_path, out_seg,
                  tmpdir, font, cfg_w, cfg_h):
    """Bitta sahna segmentini (video+ovoz) render qiladi."""
    ov_file = os.path.join(tmpdir, f"ov_{i}.txt")
    with open(ov_file, "w", encoding="utf-8") as f:
        f.write(scene.get("overlay", "")[:200])

    is_image = media_path.lower().endswith((".png", ".jpg", ".jpeg"))
    if is_image:
        vf = (
            f"scale=2160:3840:force_original_aspect_ratio=increase,"
            f"crop=2160:3840,"
            f"zoompan=z='min(zoom+0.0005,1.10)':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={cfg_w}x{cfg_h}:fps=30,setsar=1"
        )
        base = ["ffmpeg", "-y", "-loop", "1", "-framerate", "30",
                "-i", media_path, "-t", f"{dur:.2f}"]
    else:
        vf = (f"scale={cfg_w}:{cfg_h}:force_original_aspect_ratio=increase,"
              f"crop={cfg_w}:{cfg_h},setsar=1,fps=30")
        base = ["ffmpeg", "-y", "-stream_loop", "-1",
                "-i", media_path, "-t", f"{dur:.2f}"]

    badge = scene.get("badge", "")
    draws = []
    if badge:
        draws.append(
            f"drawtext=fontfile={font}:text='{badge}':fontcolor=yellow:"
            f"fontsize=110:borderw=3:bordercolor=black:"
            f"x=w-tw-46:y=84:box=1:boxcolor=black@0.45:boxborderw=18")
    draws.append(
        f"drawtext=fontfile={font}:textfile={ov_file}:fontcolor=white:"
        f"fontsize=76:borderw=4:bordercolor=black@0.85:"
        f"x=(w-text_w)/2:y=h*0.60:line_spacing=14")
    vf = vf + "," + ",".join(draws)

    # ovozni segment davomiylikka moslashtirish (kerak bo'lsa tezlashtirish)
    speech = _ffprobe_duration(audio_path)
    tempo = min(2.0, max(1.0, speech / max(0.5, dur - 0.05)))
    af = f"atempo={tempo:.3f},apad"

    # MUHIM: -shortest apad bilan ishlatilmaydi (cheksiz kutish xavfi).
    # Buning o'rniga har bir input va output aniq -t bilan cheklanadi.
    _run(base + [
        "-t", f"{dur + 0.25:.2f}", "-i", audio_path,
        "-vf", vf,
        "-af", af,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-t", f"{dur:.2f}", out_seg,
    ])


def _mix_music(cfg, out_path, total):
    """Fon musiqasi: ambient pad (A-minor) + 'havo' shovqini.
    Narration gapirganda avtomatik pasayadi (sidechain ducking)."""
    mv = float(cfg.get("sfx", {}).get("music_volume", 0.12))
    if mv <= 0:
        return
    dur = max(1.0, total + 0.5)
    cmd = ["ffmpeg", "-y", "-i", out_path]
    for f in (110.0, 164.81, 220.0, 261.63):     # A2, E3, A3, C4 — Am pad
        cmd += ["-f", "lavfi", "-t", f"{dur:.2f}",
                "-i", f"sine=frequency={f}:sample_rate=44100"]
    cmd += ["-f", "lavfi", "-t", f"{dur:.2f}",
            "-i", "anoisesrc=color=brown:amplitude=0.5:sample_rate=44100"]
    fc = (
        "[1:a]volume=0.30,tremolo=f=0.18:d=0.55[n1];"
        "[2:a]volume=0.26,tremolo=f=0.13:d=0.60[n2];"
        "[3:a]volume=0.20,tremolo=f=0.22:d=0.50[n3];"
        "[4:a]volume=0.16,tremolo=f=0.10:d=0.60[n4];"
        "[5:a]volume=0.35,lowpass=f=420[n5];"
        "[n1][n2][n3][n4][n5]amix=inputs=5:duration=longest:normalize=0,"
        "lowpass=f=1000,aresample=48000,aformat=channel_layouts=stereo,"
        f"volume={mv}[bgm];"
        "[0:a]asplit=2[voice][sc];"
        "[bgm][sc]sidechaincompress=threshold=0.025:ratio=12:"
        "attack=15:release=450[duck];"
        "[voice][duck]amix=inputs=2:duration=first:normalize=0,"
        "alimiter=limit=0.95:level=0[aout]"
    )
    tmp = out_path + ".music.mp4"
    cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-ar", "48000", "-ac", "2", "-movflags", "+faststart", tmp]
    _run(cmd)
    os.replace(tmp, out_path)
    print(f"[render] fon musiqasi qo'shildi (daraja {mv}, ducking bilan)")


def render(cfg, scenes, timeline, media_files, audio_files, out_path):
    tmp = cfg["_paths"]["work"]
    os.makedirs(tmp, exist_ok=True)
    font = _font()
    cfg_w = cfg["video"]["width"]
    cfg_h = cfg["video"]["height"]
    segs = []
    for i, (scene, dur) in enumerate(zip(scenes, timeline)):
        seg = os.path.join(tmp, f"seg_{i:02d}.mp4")
        print(f"[render] sahna {i + 1}/{len(scenes)} - {dur:.1f}s")
        _render_scene(i, scene, dur, media_files[i], audio_files[i],
                      seg, tmp, font, cfg_w, cfg_h)
        segs.append(seg)

    # concat (barcha segmentlar bir xil codec/parametrlar)
    lst = os.path.join(tmp, "concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
          "-c", "copy", "-movflags", "+faststart", out_path])

    total = _ffprobe_duration(out_path)
    # Fon musiqasi (sfx yoqilgan bo'lsa) — concat'dan keyin bitta yakuniy pass
    if cfg.get("sfx", {}).get("enabled", True):
        try:
            _mix_music(cfg, out_path, total)
        except Exception as e:
            print(f"[render] fon musiqasi qo'shilmadi ({e}) — davom etamiz")
        total = _ffprobe_duration(out_path)

    mn, mx = cfg["video"]["min_duration"], cfg["video"]["max_duration"]
    print(f"[render] tayyor: {out_path} ({total:.1f}s)")
    if not (mn - 1.5 <= total <= mx + 1.5):
        print(f"[render] OGOHlantirish: davomiylik {total:.1f}s "
              f"[{mn}-{mx}] diapazondan tashqari")
    return out_path, total
