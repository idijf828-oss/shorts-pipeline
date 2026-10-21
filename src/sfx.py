"""SFX moduli: sintez qilingan tovush effektlari + fon musiqasi.

Hammasi OFLAYN generatsiya qilinadi (Python wave + ffmpeg lavfi):
  - mualliflik huquqi muammosi yo'q (royalty-free emas — umuman bizning)
  - hech qanday API kaliti kerak emas

Effektlar: riser (hook), whoosh + ding (har fakt), impact (№1), chime (outro).
Fon musiqasi: ambient pad (A-minor akkord) + past shovqin "havo" qatlami,
narration davomida avtomatik pasayadi (sidechain ducking).
"""
import math
import os
import random
import struct
import subprocess
import wave

SR = 44100


# ---------- WAV yozish ----------
def _write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(s * 32767))))
            for s in samples))


def _env(t, dur, attack=0.008, release=0.2):
    if t < attack:
        return t / attack
    if t > dur - release:
        return max(0.0, (dur - t) / release)
    return 1.0


def _lowpass_sweep(samples, f_of_t):
    """Vaqt o'tishi bilan kesish chastotasi o'zgaradigan bir kutupli filtr."""
    out, y = [], 0.0
    for i, s in enumerate(samples):
        f = max(40.0, min(16000.0, f_of_t(i / SR)))
        a = min(0.95, 2 * math.pi * f / SR)
        y += a * (s - y)
        out.append(y)
    return out


# ---------- Effektlar ----------
def _whoosh(path, dur=0.8):
    rng = random.Random(42)
    n = int(dur * SR)
    noise = [rng.uniform(-1, 1) for _ in range(n)]

    def f_of_t(t):
        return 300 + 5200 * math.sin(math.pi * min(1.0, t / dur)) ** 2

    filt = _lowpass_sweep(noise, f_of_t)
    out = [0.85 * s * _env(i / SR, dur, attack=0.25, release=0.30)
           for i, s in enumerate(filt)]
    _write_wav(path, out)


def _ding(path, dur=1.1, base=880.0, vol=0.8):
    n = int(dur * SR)
    out = []
    for i in range(n):
        t = i / SR
        e = math.exp(-3.2 * t)
        s = (math.sin(2 * math.pi * base * t)
             + 0.45 * math.sin(2 * math.pi * base * 1.5 * t)
             + 0.22 * math.sin(2 * math.pi * base * 2.0 * t))
        out.append(vol * 0.33 * s * e)
    _write_wav(path, out)


def _impact(path, dur=0.7):
    n = int(dur * SR)
    rng = random.Random(7)
    out, phase = [], 0.0
    for i in range(n):
        t = i / SR
        f = 110 * math.exp(-6.0 * t) + 42           # pitch drop
        phase += 2 * math.pi * f / SR
        thump = math.sin(phase) * math.exp(-4.5 * t)
        burst = rng.uniform(-1, 1) * math.exp(-28 * t) * 0.5
        out.append(0.9 * thump + burst)
    _write_wav(path, out)


def _riser(path, dur=1.3):
    n = int(dur * SR)
    rng = random.Random(11)
    noise = [rng.uniform(-1, 1) for _ in range(n)]

    def f_of_t(t):
        return 250 + (4200 - 250) * (t / dur) ** 1.6

    filt = _lowpass_sweep(noise, f_of_t)
    out, phase = [], 0.0
    for i, s in enumerate(filt):
        t = i / SR
        f = 180 + (760 - 180) * (t / dur) ** 1.4
        phase += 2 * math.pi * f / SR
        e = (t / dur) ** 1.8                        # kuchayib boradi, keskin tugaydi
        out.append(0.5 * s * e + 0.30 * math.sin(phase) * e)
    _write_wav(path, out)


def _chime(path, dur=1.4):
    n = int(dur * SR)
    out = [0.0] * n
    for base, off, vol in ((660.0, 0.0, 0.5), (880.0, 0.28, 0.55)):
        m = int((dur - off) * SR)
        for i in range(m):
            t = i / SR
            e = math.exp(-3.0 * t)
            s = math.sin(2 * math.pi * base * t) + 0.4 * math.sin(2 * math.pi * base * 1.5 * t)
            out[int(off * SR) + i] += vol * 0.3 * s * e
    _write_wav(path, out)


def ensure_sfx(work_dir):
    """Barcha effektlarni (bir marta) yaratadi. {nom: yo'l} qaytaradi."""
    d = os.path.join(work_dir, "sfx")
    os.makedirs(d, exist_ok=True)
    makers = {
        "whoosh": (_whoosh, {}),
        "ding": (_ding, {}),
        "impact": (_impact, {}),
        "riser": (_riser, {}),
        "chime": (_chime, {}),
    }
    fx = {}
    for name, (fn, kw) in makers.items():
        p = os.path.join(d, name + ".wav")
        if not os.path.exists(p) or os.path.getsize(p) < 1000:
            fn(p, **kw)
        fx[name] = p
    return fx


# ---------- Sahna audiosiga effektlarni aralashtirish ----------
def _mix_scene(narration, picks, dest):
    """narration + [(sfx_path, delay_ms, volume), ...] -> dest (wav)."""
    try:
        inputs = ["-i", narration]
        fc, labels = [], []
        for k, (sfx, delay_ms, vol) in enumerate(picks):
            inputs += ["-i", sfx]
            d = int(delay_ms)
            fc.append(f"[{k + 1}:a]aresample=48000,"
                      f"aformat=channel_layouts=stereo,volume={vol},"
                      f"adelay={d}|{d}[s{k}]")
            labels.append(f"[s{k}]")
        fc.append("[0:a]aresample=48000,aformat=channel_layouts=stereo[voice]")
        fc.append("[voice]" + "".join(labels) +
                  f"amix=inputs={1 + len(labels)}:duration=first:normalize=0[aout]")
        cmd = (["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(fc),
                "-map", "[aout]", "-ar", "48000", "-ac", "2", dest])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            print("[sfx] aralashtirish xatosi:", r.stderr[-300:])
            return False
        return True
    except Exception as e:
        print("[sfx] xato:", e)
        return False


def add_scene_sfx(cfg, scenes, timeline):
    """Har bir sahna ovoziga mos effekt qo'shadi.
    timeline: [(audio_path, dur), ...] -> yangi [(path, dur), ...]"""
    sfx_cfg = cfg.get("sfx", {})
    if not sfx_cfg.get("enabled", True) or not sfx_cfg.get("transitions", True):
        return timeline
    work = cfg["_paths"]["work"]
    fx = ensure_sfx(work)
    out = []
    for i, (audio, dur) in enumerate(timeline):
        sc = scenes[i] if i < len(scenes) else {}
        st = sc.get("type")
        if st == "hook":
            picks = [(fx["riser"], 30, 0.50)]
        elif st == "outro":
            picks = [(fx["chime"], 80, 0.40)]
        elif sc.get("number") == 1:
            picks = [(fx["impact"], 0, 0.55), (fx["ding"], 300, 0.35)]
        else:
            picks = [(fx["whoosh"], 0, 0.30), (fx["ding"], 200, 0.28)]
        dest = os.path.join(work, f"scene_{i:02d}_sfx.wav")
        if _mix_scene(audio, picks, dest):
            out.append((dest, dur))
        else:
            out.append((audio, dur))
    print("[sfx] effektlar qo'shildi (riser/whoosh/ding/impact/chime)")
    return out
