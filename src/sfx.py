"""SFX: sintez effektlar + timestamp triggerlar (pop/whoosh/ding/boom/alarm).

Har segment boshida whoosh (kamera almashdi), ikonka paydo bo'lganda pop,
LLM buyurganida boom/alarm/ding — aniq vaqtlarda audioning ichiga aralashadi.
Fon musiqasi (-18dB, ducking) render'da qo'shiladi. Hammasi oflayn sintez.
"""
import math
import os
import random
import struct
import subprocess
import wave

SR = 44100


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
    out, y = [], 0.0
    for i, s in enumerate(samples):
        f = max(40.0, min(16000.0, f_of_t(i / SR)))
        a = min(0.95, 2 * math.pi * f / SR)
        y += a * (s - y)
        out.append(y)
    return out


def _whoosh(path, dur=0.55):
    rng = random.Random(42)
    n = int(dur * SR)
    noise = [rng.uniform(-1, 1) for _ in range(n)]

    def f_of_t(t):
        return 300 + 5200 * math.sin(math.pi * min(1.0, t / dur)) ** 2

    filt = _lowpass_sweep(noise, f_of_t)
    _write_wav(path, [0.85 * s * _env(i / SR, dur, 0.12, 0.18)
                      for i, s in enumerate(filt)])


def _pop(path, dur=0.18):
    """Qisqa "pop" — baland tonli klik (ikonka uchun)."""
    n = int(dur * SR)
    out = []
    for i in range(n):
        t = i / SR
        f = 950 * math.exp(-14 * t) + 320
        e = math.exp(-22 * t)
        out.append(0.8 * math.sin(2 * math.pi * f * t) * e)
    _write_wav(path, out)


def _ding(path, dur=1.0):
    n = int(dur * SR)
    out = []
    for i in range(n):
        t = i / SR
        e = math.exp(-3.2 * t)
        s = (math.sin(2 * math.pi * 880 * t)
             + 0.45 * math.sin(2 * math.pi * 1320 * t))
        out.append(0.75 * 0.33 * s * e)
    _write_wav(path, out)


def _boom(path, dur=0.9):
    """Chuqur "boom" — portlash/drama."""
    n = int(dur * SR)
    rng = random.Random(7)
    out, phase = [], 0.0
    for i in range(n):
        t = i / SR
        f = 90 * math.exp(-5.0 * t) + 34
        phase += 2 * math.pi * f / SR
        thump = math.sin(phase) * math.exp(-3.8 * t)
        burst = rng.uniform(-1, 1) * math.exp(-18 * t) * 0.55
        out.append(1.0 * thump + burst)
    _write_wav(path, out)


def _alarm(path, dur=1.1):
    """Ikki tonli siren (geosiyosiy drama uchun)."""
    n = int(dur * SR)
    out = []
    for i in range(n):
        t = i / SR
        f = 720 if int(t * 7) % 2 == 0 else 980
        e = _env(t, dur, 0.02, 0.3)
        out.append(0.45 * math.sin(2 * math.pi * f * t) * e)
    _write_wav(path, out)


def _riser(path, dur=1.2):
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
        e = (t / dur) ** 1.8
        out.append(0.5 * s * e + 0.30 * math.sin(phase) * e)
    _write_wav(path, out)


def _tick(path, dur=0.08):
    """Juda qisqa "tik" — chegara chizig'i eventi uchun (doc B3)."""
    n = int(dur * SR)
    out = []
    for i in range(n):
        t = i / SR
        e = math.exp(-70 * t)
        out.append(0.7 * (math.sin(2 * math.pi * 2400 * t)
                          + 0.5 * math.sin(2 * math.pi * 4800 * t)) * e)
    _write_wav(path, out)


def ensure_sfx(work_dir):
    d = os.path.join(work_dir, "sfx")
    os.makedirs(d, exist_ok=True)
    makers = {"whoosh": _whoosh, "pop": _pop, "ding": _ding,
              "boom": _boom, "alarm": _alarm, "riser": _riser, "tick": _tick}
    fx = {}
    for name, fn in makers.items():
        p = os.path.join(d, name + ".wav")
        if not os.path.exists(p) or os.path.getsize(p) < 1000:
            fn(p)
        fx[name] = p
    return fx


# ---------- fon musiqasi (protsedur ambient pad, -18dB da) ----------
_CHORDS = [                                    # Am - F - C - G (past registrlar)
    (110.00, 164.81, 220.00, 261.63),
    (87.31, 130.81, 174.61, 220.00),
    (98.00, 146.83, 196.00, 246.94),
    (98.00, 146.83, 196.00, 293.66),
]


def make_music(path, dur=42.0, chord_len=3.0):
    """Sekin ambient pad + yumshoq puls (fon uchun; ovoz -15 LUFS ustida)."""
    n = int(dur * SR)
    buf = [0.0] * n
    # pad: akkordlar ketma-ket, yumshoq attack/release
    for i in range(n):
        t = i / SR
        c = _CHORDS[int(t / chord_len) % len(_CHORDS)]
        ct = (t % chord_len) / chord_len
        env = min(1.0, ct / 0.35) * min(1.0, (1 - ct) / 0.45 + 0.15)
        s = 0.0
        for k, f in enumerate(c):
            # kichik detune -> jonli tovush
            s += math.sin(2 * math.pi * (f + 0.7 * k) * t
                          + 0.9 * k) / (k + 1.6)
        buf[i] += 0.16 * env * s
    # yumshoq puls (0.5s = 120 BPM yarim) — past "thump"
    pn = int(0.5 * SR)
    for start in range(0, n - pn, pn):
        for j in range(pn):
            t = j / SR
            th = math.sin(2 * math.pi * (60 * math.exp(-9 * t) + 42) * t)
            buf[start + j] += 0.13 * th * math.exp(-16 * t)
    # yon effektlar: juda sekin filtered noise shimmer
    rng = random.Random(5)
    for i in range(n):
        t = i / SR
        shimmer = rng.uniform(-1, 1) * 0.012 * math.sin(math.pi * t / dur) ** 2
        buf[i] += shimmer
    # yumshoq fade in/out (loop hissi)
    fade = int(1.2 * SR)
    for i in range(fade):
        g = i / fade
        buf[i] *= g
        buf[n - 1 - i] *= g
    _write_wav(path, buf)
    return path


def ensure_music(work_dir):
    """Haqiqiy CC0 musiqa (assets/music/bed.mp3); yo'q bo'lsa sintez."""
    repo_music = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "music", "bed.mp3")
    if os.path.exists(repo_music) and os.path.getsize(repo_music) > 100_000:
        return repo_music
    d = os.path.join(work_dir, "sfx")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "music.wav")
    if not os.path.exists(p) or os.path.getsize(p) < 10000:
        make_music(p)
    return p


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


def add_triggers(cfg, audio_path, triggers, work, idx):
    """triggers: [(nom, t_sek, volume)] — aniq vaqtda effekt."""
    if not triggers:
        return audio_path
    fx = ensure_sfx(work)
    picks = [(fx[n], max(0.0, t) * 1000, v) for (n, t, v) in triggers
             if n in fx and t is not None]
    if not picks:
        return audio_path
    dest = os.path.join(work, f"seg_{idx:02d}_sfx.wav")
    if _mix_scene(audio_path, picks, dest):
        return dest
    return audio_path
