"""5-qadam: ffmpeg montaj — kesishlar + ASS subtitr + musiqa.

Har sahna:
  2-3 sekundlik SUB-KLIPLAR (hook'da majburiy cut) -> concat ->
  sahna audiosi (SFX bilan) + dinamik subtitr (ass) + statik on_screen ->
  segment.
Keyin: barcha segmentlar concat -> fon musiqasi (ducking) ->
loudnorm (-15 LUFS) -> faststart. Rezolyutsiya qattiq tekshiriladi.
"""
import math
import os
import subprocess

from src import captions


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


def _ffprobe_size(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=30)
    try:
        w, h = r.stdout.strip().split(",")
        return int(w), int(h)
    except Exception:
        return 0, 0


def plan_scene_subs(cfg, scene, dur):
    """Sahnani 2-3s lik sub-kliplarga bo'lish rejasi.
    Hook'da kamida 1 cut majburiy (n=2)."""
    if scene.get("type") == "hook":
        n = 2
    else:
        n = max(1, math.ceil(dur / 3.0))
    n = max(1, min(n, 3))
    return {"n": n, "sub": dur / n, "cuts": [dur / n * k for k in range(1, n)]}


_SRC_DUR = {}


def _src_dur(path):
    if path not in _SRC_DUR:
        _SRC_DUR[path] = _ffprobe_duration(path)
    return _SRC_DUR[path]


def _render_sub(media_path, sub_dur, out, cfg_w, cfg_h, variant=0):
    """Bitta sub-klip (2-3s, ovozsiz). variant — boshqa zoom/oyna har xilligi."""
    is_image = media_path.lower().endswith((".png", ".jpg", ".jpeg"))
    if is_image:
        z = 0.0009 * (variant + 1)
        vf = (f"scale=2160:3840:force_original_aspect_ratio=increase,"
              f"crop=2160:3840,"
              f"zoompan=z='min(zoom+{z:.4f},1.15)':d=1:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"s={cfg_w}x{cfg_h}:fps=30,setsar=1")
        base = ["ffmpeg", "-y", "-loop", "1", "-framerate", "30",
                "-t", f"{sub_dur:.2f}", "-i", media_path]
    else:
        vf = (f"scale={cfg_w}:{cfg_h}:force_original_aspect_ratio=increase,"
              f"crop={cfg_w}:{cfg_h},setsar=1,fps=30")
        sd = _src_dur(media_path)
        if sd and sd > sub_dur + 0.3:
            span = max(0.0, sd - sub_dur - 0.1)
            off = min(span, variant * min(2.0, span))
            base = ["ffmpeg", "-y", "-ss", f"{off:.2f}", "-i", media_path]
        else:
            base = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", media_path]
    _run(base + ["-vf", vf, "-t", f"{sub_dur:.2f}", "-r", "30",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-pix_fmt", "yuv420p", "-an", out])


def _concat(files, out):
    lst = out + ".txt"
    with open(lst, "w", encoding="utf-8") as f:
        for p in files:
            f.write(f"file '{p}'\n")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
          "-c", "copy", out])


def _mix_music(cfg, out_path, total):
    """Fon musiqasi + yakuniy loudnorm (-15 LUFS, telefon uchun)."""
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
        "loudnorm=I=-15:TP=-1.5:LRA=11[aout]"
    )
    tmp = out_path + ".music.mp4"
    cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            "-ar", "48000", "-ac", "2", "-movflags", "+faststart", tmp]
    _run(cmd)
    os.replace(tmp, out_path)
    print("[render] fon musiqasi + loudnorm(-15 LUFS) qo'shildi")


def render(cfg, script, items):
    """items: [{"scene", "audio", "dur", "words", "media": [{id,path}]}]"""
    tmp = cfg["_paths"]["work"]
    os.makedirs(tmp, exist_ok=True)
    w, h = cfg["video"]["width"], cfg["video"]["height"]
    segs = []
    for i, it in enumerate(items):
        scene, dur = it["scene"], it["dur"]
        media = it["media"]
        plan = plan_scene_subs(cfg, scene, dur)
        print(f"[render] sahna {i + 1}/{len(items)} — {dur:.1f}s, "
              f"{plan['n']} sub-klip")
        subs = []
        for k in range(plan["n"]):
            m = media[k % len(media)]
            sub_out = os.path.join(tmp, f"sub_{i:02d}_{k}.mp4")
            _render_sub(m["path"], plan["sub"], sub_out, w, h, variant=k)
            subs.append(sub_out)
        visual = os.path.join(tmp, f"scenev_{i:02d}.mp4")
        if len(subs) == 1:
            os.replace(subs[0], visual)
        else:
            _concat(subs, visual)
        ass = captions.build_scene_ass(
            cfg, scene, it["words"], dur, os.path.join(tmp, f"scene_{i:02d}.ass"))
        seg = os.path.join(tmp, f"seg_{i:02d}.mp4")
        _run(["ffmpeg", "-y", "-i", visual, "-i", it["audio"],
              "-vf", f"ass={ass}", "-af", "apad",
              "-map", "0:v:0", "-map", "1:a:0",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
              "-pix_fmt", "yuv420p", "-r", "30",
              "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
              "-t", f"{dur:.2f}", seg])
        segs.append(seg)

    out_path = os.path.join(cfg["_paths"]["output"], "short.mp4")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    _concat(segs, out_path)
    total = _ffprobe_duration(out_path)
    if cfg.get("sfx", {}).get("enabled", True):
        try:
            _mix_music(cfg, out_path, total)
        except Exception as e:
            print(f"[render] fon musiqasi qo'shilmadi ({e}) — davom etamiz")
        total = _ffprobe_duration(out_path)

    # --- QATIY TEKSHIRUV (qabul mezonlari) ---
    wq, hq = _ffprobe_size(out_path)
    if (wq, hq) != (w, h):
        raise RuntimeError(f"Rezolyutsiya {wq}x{hq} — {w}x{h} kutilgan!")
    print(f"[render] TAYYOR: {out_path} ({total:.1f}s, {wq}x{hq})")
    mn, mx = cfg["video"]["min_duration"], cfg["video"]["max_duration"]
    if not (mn - 2 <= total <= mx + 2):
        print(f"[render] OGOHLANTIRISH: davomiylik {total:.1f}s [{mn}-{mx}]")
    return out_path, total
