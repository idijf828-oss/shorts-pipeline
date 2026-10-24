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

from . import style

SR = 44100
MAX_SAME_TIME = 2          # doc P2: bir vaqtda <=2 SFX


def _write_wav(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(s * 32767))))
            for s in samples))


def _write_wav_st(path, left, right):
    """Stereo wav (doc P2: whoosh chapdan o'ngga panning)."""
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(
            struct.pack("<hh",
                        max(-32767, min(32767, int(l * 32767))),
                        max(-32767, min(32767, int(r * 32767))))
            for l, r in zip(left, right)))


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


def _whoosh(path, dur=0.28):
    """Cut/zoom whoosh (doc P2: 0.25s, chapdan o'ngga stereo pan)."""
    rng = random.Random(42)
    n = int(dur * SR)
    noise = [rng.uniform(-1, 1) for _ in range(n)]

    def f_of_t(t):
        return 300 + 5200 * math.sin(math.pi * min(1.0, t / dur)) ** 2

    filt = _lowpass_sweep(noise, f_of_t)
    left, right = [], []
    for i, s in enumerate(filt):
        t = i / SR
        env = _env(t, dur, 0.10, 0.12)
        pan = t / dur                       # 0=chap ... 1=o'ng
        left.append(0.85 * s * env * (1.0 - 0.75 * pan))
        right.append(0.85 * s * env * (0.25 + 0.75 * pan))
    _write_wav_st(path, left, right)


def _swish(path, dur=0.22):
    """Arrow swish — yumshoq, balandroq, whoosh'dan farqli (doc P2)."""
    rng = random.Random(77)
    n = int(dur * SR)
    noise = [rng.uniform(-1, 1) for _ in range(n)]

    def f_of_t(t):
        return 900 + 3800 * (t / dur)

    filt = _lowpass_sweep(noise, f_of_t)
    left, right = [], []
    for i, s in enumerate(filt):
        t = i / SR
        env = _env(t, dur, 0.05, 0.08)
        pan = (t / dur) ** 0.7
        left.append(0.8 * s * env * (1.0 - 0.6 * pan))
        right.append(0.8 * s * env * (0.4 + 0.6 * pan))
    _write_wav_st(path, left, right)


def _zip(path, dur=0.16):
    """Chegara chizilishi "pen-draw/zip" (doc P2: -13dB)."""
    n = int(dur * SR)
    out_l, out_r = [], []
    phase = 0.0
    for i in range(n):
        t = i / SR
        f = 2000 - 1500 * (t / dur)
        phase += 2 * math.pi * f / SR
        e = math.sin(math.pi * min(1.0, t / dur)) ** 0.8
        s = 0.7 * math.sin(phase) * e
        out_l.append(s * 0.9)
        out_r.append(s * 1.0)
    _write_wav_st(path, out_l, out_r)


def _drop(path, dur=0.20):
    """Pin "tick/drop" — pastga tushuvchi ikki bosqich (doc P2: -12dB)."""
    n = int(dur * SR)
    out = []
    phase = 0.0
    for i in range(n):
        t = i / SR
        if t < 0.09:
            f = 1400 - 500 * (t / 0.09)
            e = math.exp(-14 * t)
        else:
            f = 700 - 260 * ((t - 0.09) / 0.11)
            e = 0.55 * math.exp(-16 * (t - 0.09))
        phase += 2 * math.pi * f / SR
        out.append(0.75 * math.sin(phase) * e)
    _write_wav(path, out)


def _impact(path, dur=0.5):
    """Impact (hook 3.0s / oxirgi twist, doc P2: -8/-9dB)."""
    n = int(dur * SR)
    rng = random.Random(23)
    out, phase = [], 0.0
    for i in range(n):
        t = i / SR
        f = 120 * math.exp(-6.0 * t) + 38
        phase += 2 * math.pi * f / SR
        thump = math.sin(phase) * math.exp(-6.5 * t)
        burst = rng.uniform(-1, 1) * math.exp(-26 * t) * 0.7
        out.append(1.0 * thump + burst)
    _write_wav(path, out)


def _flagpop(path, dur=0.30):
    """flag_fill: soft pop + shimmer (doc P2: -11dB)."""
    n = int(dur * SR)
    out = []
    for i in range(n):
        t = i / SR
        f = 950 * math.exp(-14 * t) + 300
        pop = math.sin(2 * math.pi * f * t) * math.exp(-20 * t) * 0.8
        shim = (math.sin(2 * math.pi * 3400 * t)
                + 0.6 * math.sin(2 * math.pi * 4600 * t)) \
            * math.exp(-9 * t) * 0.16
        out.append(pop + shim)
    _write_wav(path, out)


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
              "boom": _boom, "alarm": _alarm, "riser": _riser,
              "tick": _tick, "flagpop": _flagpop, "swish": _swish,
              "zip": _zip, "drop": _drop, "impact": _impact}
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
    """Haqiqiy CC0 musiqa (assets/music/*.mp3, doc P2: kamida 3 ta) —
    tasodifiy tanlov (har kun boshqa kayfiyat). Yo'q bo'lsa sintez."""
    repo_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "music")
    if os.path.isdir(repo_dir):
        tracks = [os.path.join(repo_dir, f) for f in sorted(os.listdir(repo_dir))
                  if f.lower().endswith((".mp3", ".ogg", ".m4a"))
                  and os.path.getsize(os.path.join(repo_dir, f)) > 100_000]
        if tracks:
            pick = random.choice(tracks)
            print(f"[sfx] musiqa: {os.path.basename(pick)} "
                  f"({len(tracks)} ta CC0 trek)")
            return pick
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
    """triggers: [(nom, t_sek, volume)] — aniq vaqtda effekt.

    Doc P2: bir vaqtda <=2 SFX (0.12s oynada); darajalar style.SFX_DB.
    """
    if not triggers:
        return audio_path
    fx = ensure_sfx(work)
    _mode = str((cfg.get("sfx") or {}).get("mode", ""))
    minimal = _mode == "minimal"
    explainer = _mode == "explainer"
    picks = []
    for (n, t, v) in triggers:
        if n in fx and t is not None:
            vol = v
            if vol is None:
                # v7 immersive: minimal rejimda yanada yumshoq (referens:
                # deyarli toza ovoz, faqat nozik kesish tovushi)
                if minimal:
                    db = style.MINIMAL_SFX_DB.get(n,
                                                 style.SFX_DB.get(n, -12))
                elif explainer:
                    db = style.EXPLAINER_SFX_DB.get(n,
                                                    style.SFX_DB.get(n, -12))
                else:
                    db = None
                vol = (10 ** ((db + 2) / 20)) if db is not None \
                    else style.sfx_vol(n)
            picks.append((fx[n], max(0.0, t) * 1000, round(vol, 3)))
    picks.sort(key=lambda p: p[1])              # vaqt bo'yicha
    kept, near = [], []                         # <=2 SFX per 120ms oyna
    for p in picks:
        near = [q for q in near if p[1] - q[1] <= 120]
        if len(near) >= MAX_SAME_TIME:
            continue
        near.append(p)
        kept.append(p)
    if not kept:
        return audio_path
    dest = os.path.join(work, f"seg_{idx:02d}_sfx.wav")
    if _mix_scene(audio_path, kept, dest):
        return dest
    return audio_path
