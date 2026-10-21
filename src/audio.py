"""Audio post-processing (Info Hub standarti).

1) O'LIK HAVONI KESISH: gaplar (phrase) oralasidagi >0.28s sukunatlar
   0.11s ga siqiladi — so'z vaqtlari ANIQ qayta hisoblanadi (Whisper/
   edge-tts timestamplaridan foydalanib, pydub'siz, sof ffmpeg bilan).
2) TURBO: atempo (pitch buzmagan tezlashtirish) — so'z vaqtlari moslashadi.
3) DUM: oxirgi so'z hech qachon kesilmaydi (render'da +0.3s apad).

words = [(word, start, end), ...] -> (yangi_audio, yangi_words)
"""
import os
import subprocess


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-300:])
    return r


def _probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _silence(dest, dur, work):
    p = os.path.join(work, "sil.wav")
    if not (os.path.exists(p) and abs(_probe(p) - dur) < 0.005):
        _run(["ffmpeg", "-y", "-f", "lavfi", "-t", f"{dur:.3f}",
              "-i", "anullsrc=r=48000:cl=stereo", "-c:a", "pcm_s16le", p])
    return p


def _silences(src, noise_db=-38, min_d=0.10):
    """Audiodagi haqiqiy jimlik oynalari (silencedetect)."""
    r = _run(["ffmpeg", "-i", src, "-af",
              f"silencedetect=noise={noise_db}dB:d={min_d}", "-f", "null", "-"])
    dur = _probe(src)
    sil, cur = [], None
    for line in r.stderr.splitlines():
        if "silence_start" in line:
            cur = max(0.0, float(line.split(":")[-1]))
        elif "silence_end" in line and cur is not None:
            e = float(line.split("silence_end:")[1].split("|")[0])
            sil.append((cur, min(e, dur)))
            cur = None
    if cur is not None:
        sil.append((cur, dur))
    return sil


def strip_dead_air(words, src, work, gap=0.10, thresh=0.16, margin=0.020):
    """AUDIO-ASOSLI sukunat siqish: >thresh jimlik -> gap sekundga qisqaradi.

    Kesish nuqtalari haqiqiy nutq hududlaridan (silencedetect) olinadi —
    so'z vaqtlari taxminiy bo'lsa ham (gTTS) aniq ishlaydi.
    So'z vaqtlari yangi timeline'ga qayta proyeksiyalanadi.
    """
    dur = _probe(src)
    sil = _silences(src)
    # nutq hududlari = [0,dur] minus jimliklar
    speech, t = [], 0.0
    for (s, e) in sil:
        if s - t > 0.04:
            speech.append((t, s))
        t = max(t, e)
    if dur - t > 0.04:
        speech.append((t, dur))
    if not speech:
        return src, words, dur
    # tutash hududlarni birlashtir (oradagi gap <= thresh)
    groups = [list(speech[0])]
    for (s, e) in speech[1:]:
        if s - groups[-1][1] <= thresh:
            groups[-1][1] = e
        else:
            groups.append([s, e])
    cuts = [(max(0.0, s - margin), min(dur, e + margin))
            for (s, e) in groups]

    parts, new_words, t = [], [], 0.0
    for i, (s, e) in enumerate(cuts):
        part = os.path.join(work, f"ph_{i:02d}.wav")
        _run(["ffmpeg", "-y", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", src,
              "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", part])
        parts.append(part)
        if i < len(cuts) - 1:
            parts.append(_silence(os.path.join(work, "g.wav"), gap, work))
        t += (e - s) + (gap if i < len(cuts) - 1 else 0.0)
    dest = os.path.join(work, "tight.wav")
    lst = dest + ".txt"
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
          "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", dest])

    # so'z vaqtlarini yangi timeline'ga ko'chirish (midpoint bo'yicha)
    new_t = 0.0
    bounds = []
    for i, (s, e) in enumerate(cuts):
        end = new_t + (e - s)
        bounds.append((new_t, end))
        new_t = end + (gap if i < len(cuts) - 1 else 0.0)
    out_words = []
    for (w, ws, we) in (words or []):
        mid = (ws + we) / 2.0
        for i, (s, e) in enumerate(cuts):
            if s - 0.02 <= mid <= e + 0.02:
                delta = bounds[i][0] - s
                out_words.append((w, max(0.0, ws + delta),
                                  max(0.01, we + delta)))
                break
        else:  # jimlik ichida qolgan so'z -> keyingi guruh boshiga
            nxt = next(((i2, s2) for i2, (s2, e2) in enumerate(cuts)
                        if s2 > mid), None)
            if nxt is not None:
                i2, s2 = nxt
                delta = bounds[i2][0] - s2
                out_words.append((w, max(0.0, ws + delta),
                                  max(0.01, we + delta)))
            elif out_words:
                lw, ls, le = out_words[-1]
                out_words[-1] = (lw, ls, max(le, bounds[-1][1]))
    return dest, out_words, _probe(dest)


def speed(path, tempo, dest):
    """Pitch buzmagan tezlashtirish (atempo)."""
    _run(["ffmpeg", "-y", "-i", path, "-filter:a", f"atempo={tempo:.4f}",
          "-ar", "48000", "-ac", "2", dest])
    return dest


def scale_words(words, k):
    return [(w, s * k, e * k) for (w, s, e) in words]
