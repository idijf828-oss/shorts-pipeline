"""Asosiy orkestrator:
  trend tahlili -> skript -> TTS -> media -> montaj
  -> Telegram tasdig'i -> YouTube yuklash -> tarix saqlash.
"""
import argparse
import datetime
import os
import traceback

from src.config import load
from src import trends, history, script_gen, tts, media, render, telegram, upload


def build_description(cfg, script):
    return (
        f"{script['title']}\n\n"
        + "\n".join(f"{i + 1}. {sc['narration']}"
                    for i, sc in enumerate(script["scenes"]))
        + "\n\n"
        + "Barcha vaziyatlar original va ixtiroiy. "
          "Kliplar: Pexels/Pixabay (royalty-free). "
          "Ovoz va skript AI yordamida yaratilgan, inson tomonidan "
          "tasdiqlangan.\n"
          f"#{' #'.join(tag for tag in cfg['video']['tags'][:8])}"
    )


def run(cfg):
    t0 = datetime.datetime.now(datetime.UTC).isoformat()

    print("== 1/7: YouTube trend tahlili (US, 30 kun) ==")
    try:
        tr = trends.fetch_trending(cfg)
    except Exception as e:
        # Trend — boyituvchi ma'lumot. API xatosi butun kunlik videoni
        # o'ldirmasligi kerak: bo'sh trend bilan davom etamiz.
        print(f"   [OGOX] trend olinmadi ({e}); pipeline davom etadi")
        telegram.send_message(cfg, "⚠️ Trend olinmadi (YouTube API), "
                                   "lekin video baribir yaratiladi: "
                                   + str(e)[:200])
        tr = {"summary": {"top_titles": [], "top_words": [], "hashtags": [],
                          "formats_seen": [], "avg_views_top10": 0,
                          "avg_title_len": 0}, "items": []}
    if tr.get("summary", {}).get("top_titles"):
        print(f"   top: {tr['summary']['top_titles'][0]['title'][:70]}")

    print("== 2/7: Gemini bilan asl skript ==")
    hist = history.load()
    script = script_gen.write_script(cfg, tr, history.keywords(hist))
    if history.too_similar(script["title"], script["keywords"], hist):
        print("   mavzu tarix bilan o'xshash -> qayta generatsiya")
        script = script_gen.write_script(
            cfg, tr, history.keywords(hist), avoid_title=script["title"])
    print(f"   sarlavha: {script['title']}")

    print("== 3/7: Ovoz (edge-tts -> gTTS fallback) ==")
    timeline = tts.prepare(cfg, script["scenes"])
    audio_files = [p for p, _ in timeline]

    print("== 4/7: Kliplar (Pexels -> Pixabay -> kart) ==")
    media_files = media.fetch_all(cfg, script["scenes"])

    print("== 5/7: ffmpeg montaj (1080x1920) ==")
    out = os.path.join(cfg["_paths"]["output"], "short.mp4")
    out, dur = render.render(cfg, script["scenes"],
                             [d for _, d in timeline],
                             media_files, audio_files, out)

    print("== 6/7: Telegram tasdig'i ==")
    cap = telegram.caption(cfg, tr, script, dur)
    approved = telegram.send_video_and_wait(
        cfg, out, cap, cfg["behavior"]["telegram_approval_timeout_min"])
    if not approved:
        telegram.send_message(cfg, "⛔ Video bekor qilindi yoki vaqt "
                                   "tugadi. Hech narsa yuklanmadi.")
        print("Tasdiq berilmadi — yuklanmadi.")
        return

    if cfg["behavior"]["dry_run"]:
        print("dry_run=ON: yuklash o'chirilgan. Tayyor:", out)
        return

    print("== 7/7: YouTube'ga yuklash ==")
    title = script["title"]
    vid = upload.upload(cfg, out, title,
                        build_description(cfg, script),
                        cfg["video"]["tags"])
    history.add(title, script["keywords"], vid)
    telegram.send_message(
        cfg, f"✅ Yuklandi: {title}\nhttps://youtu.be/{vid}")
    print("TAYYOR:", f"https://youtu.be/{vid}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    cfg = load(args.config)
    try:
        run(cfg)
    except Exception as e:
        print("XATO:", e)
        traceback.print_exc()
        try:
            telegram.send_message(cfg, f"🚨 Pipeline xatosi:\n{str(e)[:900]}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
