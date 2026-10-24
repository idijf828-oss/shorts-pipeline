"""3-qadam: professional ovoz + SO'Z VAQTLARI (subtitr uchun).

edge-tts: WordBoundary xossalari aniq so'z vaqtlarini beradi.
gTTS fallback: vaqt taxminan (belgi ulushi) taqsimlanadi.
Qaytaradi: [{"audio": path, "dur": s, "words": [(word, start, end)]}, ...]
"""
import asyncio
import os
import subprocess
import time

import edge_tts
from gtts import gTTS


def _ffprobe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _edge_words(text, voice, rate, path):
    """edge-tts: audio fayl + aniq so'z vaqtlari (100ns -> sekund).

    edge-tts 7.x default 'SentenceBoundary' beradi -> 'WordBoundary' majburlaymiz.
    """
    try:
        com = edge_tts.Communicate(text, voice, rate=rate,
                                   boundary="WordBoundary")
    except TypeError:                       # eski edge-tts (<7): default Word
        com = edge_tts.Communicate(text, voice, rate=rate)
    words = []

    async def _go():
        with open(path, "wb") as f:
            async for c in com.stream():
                if c["type"] == "audio":
                    f.write(c["data"])
                elif c["type"] == "WordBoundary":
                    s = c["offset"] / 1e7
                    words.append((c["text"], s, s + c["duration"] / 1e7))

    asyncio.run(_go())
    return words


def _gtts(text, path):
    gTTS(text, lang="en", tld="com").save(path)


def fallback_words(text, total_sec):
    """gTTS vaqt bermaydi: umumiy davomiylikni belgilar ulushiga bo'lish."""
    ws = text.split()
    tot = sum(len(w) + 1 for w in ws)
    t, out = 0.0, []
    for w in ws:
        d = total_sec * (len(w) + 1) / tot
        out.append((w, t, t + d))
        t += d
    return out


def speed_audio(path, tempo, dest):
    """Audioni tempo barobar tezlashtirish (timeline sig'dirish uchun)."""
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", path, "-filter:a", f"atempo={tempo:.4f}",
         "-ar", "48000", "-ac", "2", dest],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError("atempo xatosi: " + r.stderr[-300:])
    return dest


# v9: TTS fonetik lug'at — murakkab joy nomlari to'g'ri talaffuz qilinadi
# (Llívia -> "Libya" deb o'qilardi; Canberra -> "Camber").
# FAQAT so'zma-so'z almashtirish — so'z soni va chegaralari saqlanadi.
PHONETIC = {
    "llívia": "Livia", "llivia": "Livia", "lívia": "Livia",
    "canberra": "Canburra", "canburra": "Canburra",
    "baarle": "Barleh", "hertog": "Hertok", "nassau": "Nassaw",
    "baarle-hertog": "Barleh-Hertok", "baarle-nassau": "Barleh-Nassaw",
    "küçük": "Kuchuk", "kucuk": "Kuchuk",
    "québec": "Kaybek", "quebec": "Kaybek",
    "montréal": "Monreal", "türkiye": "Turkiya",
    "ceuta": "Sayuta", "melilla": "Melilya", "djibouti": "Jibuti",
}


def _phonetic_word(w):
    """Bitta so'z: belgilarni olib tashla + lug'at. Tinish belgilari saqlanadi."""
    import unicodedata
    lead = ""
    core = w
    trail = ""
    while core and not core[0].isalnum():
        lead += core[0]
        core = core[1:]
    while core and not core[-1].isalnum():
        trail = core[-1] + trail
        core = core[:-1]
    # de-aksent: Llívia -> Llivia (katta-kichik saqlanadi)
    de = "".join(ch for ch in unicodedata.normalize("NFD", core)
                 if not unicodedata.combining(ch))
    rep = PHONETIC.get(de.lower())
    if rep and de.isupper():
        rep = rep.upper()
    elif rep and de[:1].isupper():
        rep = rep[:1].upper() + rep[1:]
    return lead + (rep if rep else de) + trail


def _phonetic(text):
    return " ".join(_phonetic_word(w) for w in str(text).split())


def synth(cfg, scenes):
    """Har sahna uchun ovoz + so'z vaqtlari."""
    tmp = cfg["_paths"]["work"]
    os.makedirs(tmp, exist_ok=True)
    voice = cfg["channel"]["voice"]
    rate = cfg["channel"].get("voice_rate", "+0%")
    engine = "edge"
    out = []
    for i, sc in enumerate(scenes):
        orig_words = str(sc["voice"]).split()
        text = _phonetic(sc["voice"])          # talaffuz uchun nom
        p = os.path.join(tmp, f"scene_{i:02d}.mp3")
        words, ok = [], False
        if engine == "edge":
            try:
                words = _edge_words(text, voice, rate, p)
                if _ffprobe_duration(p) < 0.3 or not words:
                    raise RuntimeError("bo'sh audio/so'zlar")
                # fonetik nusxani asl so'zlarga qaytaramiz (1:1)
                if len(words) == len(orig_words):
                    words = [(w0, ws, we)
                             for (_wp, ws, we), w0
                             in zip(words, orig_words)]
                ok = True
            except Exception as e:
                print(f"[tts] edge-tts ishlamadi ({type(e).__name__}); gTTS'ga o'tamiz")
                engine = "gtts"
        if not ok:
            for attempt in range(3):
                try:
                    _gtts(text, p)
                    ok = True
                    break
                except Exception as e:
                    print(f"[tts] gTTS urinish {attempt + 1}: {e}")
                    if attempt == 2:
                        raise RuntimeError("TTS umuman ishlamayapti")
                    time.sleep(2)
        d = _ffprobe_duration(p)
        if not words:
            words = fallback_words(text, d)
        out.append({"audio": p, "dur": d, "words": words, "engine": engine})
    total = sum(o["dur"] for o in out)
    print(f"[tts] ovoz: {total:.1f}s ({engine}, so'z vaqtlari: "
          f"{'aniq' if engine == 'edge' else 'taxminiy'})")
    return out
