"""3-qadam: matnni ovozga aylantirish.

Muhim (2026-10 holati): edge-tts Microsoft'ning WSS endpoint'i
o'zgargani sababli 403 beradi (github.com/rany2/edge-tts/issues/490).
Shuning uchun mantiq: edge-tts'ni sinab ko'ramiz -> ishlamasa
avtomatik gTTS (Google Translate TTS) ga o'tamiz. Video hech qachon
ovozsiz qolmaydi.
"""
import asyncio
import os
import subprocess

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


def _edge(text, voice, rate, path):
    c = edge_tts.Communicate(text, voice, rate=rate)
    asyncio.run(c.save(path))


def _gtts(text, path):
    gTTS(text, lang="en", tld="com").save(path)  # tld=com -> US accent


def prepare(cfg, scenes):
    """Har bir sahnani ovozlashtiradi + umumiy timeline (40-50s) hisoblaydi.

    Qaytaradi: [(audio_path, scene_duration), ...]
    """
    tmp = cfg["_paths"]["work"]
    os.makedirs(tmp, exist_ok=True)
    voice = cfg["channel"]["voice"]
    rate = cfg["channel"].get("voice_rate", "+0%")
    engine = "edge"

    paths, durs = [], []
    for i, sc in enumerate(scenes):
        p = os.path.join(tmp, f"scene_{i:02d}.mp3")
        ok = False
        if engine == "edge":
            try:
                _edge(sc["narration"], voice, rate, p)
                ok = True
            except Exception as e:
                print(f"[tts] edge-tts ishlamadi ({type(e).__name__}); "
                      f"qolgan sahnalar gTTS orqali")
                engine = "gtts"
        if not ok:
            for attempt in range(3):
                try:
                    _gtts(sc["narration"], p)
                    ok = True
                    break
                except Exception as e:
                    print(f"[tts] gTTS urinish {attempt + 1}: {e}")
                    if attempt == 2:
                        raise RuntimeError("TTS umuman ishlamayapti")
        paths.append(p)
        durs.append(_ffprobe_duration(p))

    n = len(scenes)
    mn, mx = cfg["video"]["min_duration"], cfg["video"]["max_duration"]
    speech = sum(durs)

    # Pauzalar: jami 40-50 sekundga sig'dirish
    pause = 0.5
    if speech + pause * n > mx:
        pause = max(0.1, (mx - speech) / n)
    elif speech + pause * n < mn:
        pause = min(1.6, (mn - speech) / n)
    timeline = [d + pause for d in durs]

    total = sum(timeline)
    if total < mn:
        timeline[-1] += mn - total
    elif total > mx:
        k = mx / total
        timeline = [d * k for d in timeline]  # render'da atempo siqadi

    print(f"[tts] ovoz: {speech:.1f}s, jami timeline: {sum(timeline):.1f}s")
    return list(zip(paths, timeline))
