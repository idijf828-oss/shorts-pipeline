"""Asosiy orkestrator (retention formati):
  trend tahlili -> skript (hook+5fakt+loop) -> ovoz + so'z vaqtlari ->
  SFX -> B-roll (must_contain + xarita fallback) -> montaj (kesishlar +
  subtitr + musiqa + loudnorm) -> Telegram tasdig'i -> YouTube yuklash.
"""
import argparse
import datetime
import os
import traceback

from src.config import load
from src import trends, history, script_gen, tts, sfx, media, render, telegram, upload


def build_description(cfg, script):
    """Professional description (shablon: hook -> faktlar -> CTA -> hashtag)."""
    desc = (script.get("description") or "").strip()
    if not desc:
        scenes = script.get("scenes", [])
        hook = scenes[0]["voice"] if scenes else ""
        facts = " ".join(sc["voice"] for sc in scenes[1:6])
        pc = script.get("pinned_comment") or "Which one should I cover next? 👇"
        desc = (f"{hook}\n{facts}\n\n{pc}\nNew geography fact every day.\n")
    hashtags = script.get("hashtags") or ["shorts", "geography", "facts"]
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

    print("== 2/8: Gemini skript (hook + 5 fakt + infinite loop) ==")
    hist = history.load()
    script = script_gen.write_script(cfg, tr, history.keywords(hist))
    if history.too_similar(script["title"], script["keywords"], hist):
        print("   mavzu tarix bilan o'xshash -> qayta generatsiya")
        script = script_gen.write_script(
            cfg, tr, history.keywords(hist), avoid_title=script["title"])
    print(f"   sarlavha: {script['title']}")

    print("== 3/8: Professional ovoz + so'z vaqtlari ==")
    items = tts.synth(cfg, script["scenes"])   # [{audio, dur, words}]

    # Timeline: pauzalar + 35-40s ga sig'dirish
    mn, mx = cfg["video"]["min_duration"], cfg["video"]["max_duration"]
    pads = [0.20 if sc.get("type") == "hook" else 0.35 for sc in script["scenes"]]
    pads[-1] = 0.20   # oxirgi sukunat <= 0.2s (loop uchun)
    total = sum(it["dur"] for it in items) + sum(pads)
    if total < mn + 0.5:
        extra = (mn + 0.5 - total) / len(items)
        pads = [min(0.80, p + extra) for p in pads]
    elif total > mx - 1.0:
        # konteyner yaxitlashi (~0.5s) uchun margin bilan tezlashtirish
        tempo = min(1.25, total / (mx - 1.5))
        print(f"   audio {tempo:.3f}x tezlashtiriladi "
              f"({total:.1f}s -> ~{total / tempo:.1f}s)")
        for k, it in enumerate(items):
            fast = os.path.join(cfg["_paths"]["work"], f"fast_{k:02d}.wav")
            it["audio"] = tts.speed_audio(it["audio"], tempo, fast)
            it["dur"] = it["dur"] / tempo
            it["words"] = [(w, s / tempo, e / tempo) for (w, s, e) in it["words"]]
        # hali ham uzun bo'lsa — pauzalarni qisqartirish
        if sum(it["dur"] for it in items) + sum(pads) > mx - 0.8:
            pads = [max(0.12, p * 0.5) for p in pads]
    for i, it in enumerate(items):
        it["dur"] = it["dur"] + pads[i]
        it["scene"] = script["scenes"][i]
    print(f"   jami timeline: {sum(it['dur'] for it in items):.1f}s")

    print("== 4/8: Ovoz effektlari (riser/impact/whoosh) ==")
    plans = [render.plan_scene_subs(cfg, it["scene"], it["dur"]) for it in items]
    items = sfx.add_scene_sfx(cfg, script["scenes"], items, plans)

    print("== 5/8: B-roll (must_contain + xarita fallback) ==")
    media_lists, used_clip_ids = media.fetch_all(
        cfg, script["scenes"], history.clip_ids())
    for i, it in enumerate(items):
        it["media"] = media_lists[i]

    print("== 6/8: Montaj (kesishlar + subtitr + musiqa + loudnorm) ==")
    out = os.path.join(cfg["_paths"]["output"], "short.mp4")
    out, dur = render.render(cfg, script, items)

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
    history.add(title, script["keywords"], vid, clips=sorted(used_clip_ids))
    pc = script.get("pinned_comment") or ""
    telegram.send_message(
        cfg, f"✅ Yuklandi: {title}\nhttps://youtu.be/{vid}\n"
             + (f"\n📌 Pinned comment (qo'lda qo'ying):\n{pc}" if pc else ""))
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
