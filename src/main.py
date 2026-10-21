"""Asosiy orkestrator:
  trend tahlili -> skript -> TTS -> SFX -> media -> montaj (+fon musiqasi)
  -> Telegram tasdig'i -> YouTube yuklash -> tarix saqlash.
"""
import argparse
import datetime
import os
import traceback

from src.config import load
from src import trends, history, script_gen, tts, sfx, media, render, telegram, upload


def build_description(cfg, script):
    """Professional YouTube description (Gemini yozgani yoki strukturali)."""
    desc = (script.get("description") or "").strip()
    if not desc:
        facts = "\n".join(f"{i + 1}. {sc['narration']}"
                          for i, sc in enumerate(script["scenes"]))
        desc = (
            f"{script['title']}\n\n{facts}\n\n"
            "Which fact surprised you the most? Tell us in the comments! 👇\n"
            "Like & subscribe for daily geography facts. 🌍\n\n"
            "All facts are researched and verified. Footage: Pexels/Pixabay "
            "(royalty-free). Voice-over and script created with AI, "
            "human-approved.\n"
        )
    hashtags = script.get("hashtags") or ["geography", "facts", "shorts"]
    tagline = " ".join("#" + h.lstrip("#") for h in hashtags[:3])
    if tagline and tagline not in desc:
        desc = desc.rstrip() + "\n\n" + tagline
    return desc[:4800]  # YouTube cheklovi: 5000 belgi


def build_tags(cfg, script):
    """YouTube teglar: Gemini + config, deduplikatsiya, 480 belgiga cheklash."""
    merged = []
    for t in (script.get("tags") or []) + list(cfg["video"]["tags"]):
        t = str(t).strip().lower().lstrip("#")
        if t and t not in merged:
            merged.append(t)
    out, total = [], 0
    for t in merged:
        if len(out) >= 15 or total + len(t) + 1 > 470:
            break
        out.append(t)
        total += len(t) + 1
    return out


def run(cfg):
    t0 = datetime.datetime.now(datetime.UTC).isoformat()

    print("== 1/8: YouTube trend tahlili (US, 30 kun) ==")
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

    print("== 2/8: Gemini bilan asl skript (geografiya faktlari) ==")
    hist = history.load()
    script = script_gen.write_script(cfg, tr, history.keywords(hist))
    if history.too_similar(script["title"], script["keywords"], hist):
        print("   mavzu tarix bilan o'xshash -> qayta generatsiya")
        script = script_gen.write_script(
            cfg, tr, history.keywords(hist), avoid_title=script["title"])
    print(f"   sarlavha: {script['title']}")

    print("== 3/8: Professional ovoz (edge-tts -> gTTS fallback) ==")
    timeline = tts.prepare(cfg, script["scenes"])
    audio_files = [p for p, _ in timeline]

    print("== 4/8: Ovoz effektlari (riser/whoosh/ding/impact) ==")
    timeline = sfx.add_scene_sfx(cfg, script["scenes"], timeline)
    audio_files = [p for p, _ in timeline]

    print("== 5/8: B-roll kliplar (Pexels -> Pixabay -> kart) ==")
    media_files = media.fetch_all(cfg, script["scenes"])

    print("== 6/8: ffmpeg montaj (1080x1920 + fon musiqasi) ==")
    out = os.path.join(cfg["_paths"]["output"], "short.mp4")
    out, dur = render.render(cfg, script["scenes"],
                             [d for _, d in timeline],
                             media_files, audio_files, out)

    print("== 7/8: Telegram tasdig'i ==")
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

    print("== 8/8: YouTube'ga yuklash (professional metadata) ==")
    title = script["title"]
    vid = upload.upload(cfg, out, title,
                        build_description(cfg, script),
                        build_tags(cfg, script))
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
