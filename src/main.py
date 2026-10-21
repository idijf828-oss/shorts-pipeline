"""V3 orkestrator — "Info Hub" 9M-views formati (18-30s tez pacing):

  trend -> Gemini v3 skript (segmentlar + xarita kameralari + bayroqlar +
  ikonkalar + SFC triggerlar) -> har segmentga TTS -> sukunat siqish +
  1.15x turbo + davomiylik nazorati -> xarita/broll vizual + ikonkalar ->
  montaj (zoompan kamera + pop-in subtitr + SFX + musiqa -18dB) ->
  Telegram tasdig'i -> YouTube yuklash.
"""
import argparse
import os
import subprocess
import traceback

from src.config import load
from src import (trends, history, script_gen, tts, audio, sfx, geo, icons,
                 media, maps, render, telegram, upload)

# SFX trigger balandliklari (musiqa -18dB, ovoz -15 LUFS ustida)
SFX_VOL = {"pop": 0.42, "whoosh": 0.30, "ding": 0.40,
           "boom": 0.55, "alarm": 0.35, "riser": 0.38}


def build_description(cfg, script):
    desc = (script.get("description") or "").strip()
    if not desc:
        segs = script.get("segments") or script.get("scenes") or []
        hook = segs[0]["voice"] if segs else ""
        facts = " ".join(s["voice"] for s in segs[1:6])
        pc = script.get("pinned_comment") or "Which place should I cover next? 👇"
        desc = f"{hook}\n{facts}\n\n{pc}\nNew geography fact every day.\n"
    hashtags = script.get("hashtags") or ["shorts", "geography", "facts"]
    tagline = " ".join("#" + h.lstrip("#") for h in hashtags[:3])
    if tagline and tagline not in desc:
        desc = desc.rstrip() + "\n\n" + tagline
    return desc[:4800]


def build_tags(cfg, script):
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


def _word_time(words, target, default=0.40):
    """at_word -> segment ichidagi aniq vaqt (topilmasa default)."""
    t = str(target or "").lower().strip(".,!?\"'")
    if t:
        for (w, s, e) in words:
            if t in str(w).lower().strip(".,!?\"'"):
                return max(0.15, s - 0.03)
    return default


def _probe_dur(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
    return float(r.stdout.strip())


def run(cfg):
    work = cfg["_paths"]["work"]
    os.makedirs(work, exist_ok=True)

    print("== 1/7: YouTube trend tahlili (US, 30 kun) ==")
    try:
        tr = trends.fetch_trending(cfg)
    except Exception as e:
        print(f"   [OGOX] trend olinmadi ({e}); davom etamiz")
        telegram.send_message(cfg, "⚠️ Trend olinmadi (YouTube API), "
                                   "lekin video baribir yaratiladi: "
                                   + str(e)[:200])
        tr = {"summary": {"top_titles": [], "top_words": [], "hashtags": [],
                          "formats_seen": [], "avg_views_top10": 0,
                          "avg_title_len": 0}, "items": []}

    print("== 2/7: Gemini v3 skript (hook + xarita segmentlari + loop) ==")
    hist = history.load()
    script = script_gen.write_script(cfg, tr, history.keywords(hist))
    if history.too_similar(script["title"], script["keywords"], hist):
        print("   mavzu tarix bilan o'xshash -> qayta generatsiya")
        script = script_gen.write_script(
            cfg, tr, history.keywords(hist), avoid_title=script["title"])
    segs = script.get("segments") or script.get("scenes")
    print(f"   sarlavha: {script['title']} ({len(segs)} segment)")

    out, dur, used_ids = produce(cfg, script)

    print("== 7/7: Telegram tasdig'i va yuklash ==")
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

    vid = upload.upload(cfg, out, script["title"],
                        build_description(cfg, script),
                        build_tags(cfg, script))
    history.add(script["title"], script["keywords"], vid,
                clips=sorted(used_ids))
    pc = script.get("pinned_comment") or ""
    telegram.send_message(
        cfg, f"✅ Yuklandi: {script['title']}\nhttps://youtu.be/{vid}\n"
             + (f"\n📌 Pinned comment (qo'lda qo'ying):\n{pc}" if pc else ""))
    print("TAYYOR:", f"https://youtu.be/{vid}")


def produce(cfg, script):
    """Skript -> tayyor video (TTS, audio post, vizual, montaj).
    (out, davomiylik, ishlatilgan klip id'lari) qaytaradi."""
    work = cfg["_paths"]["work"]
    os.makedirs(work, exist_ok=True)
    segs = script.get("segments") or script.get("scenes")

    print("== 3/7: Har segmentga TTS (aniq so'z vaqtlari) ==")
    items = tts.synth(cfg, segs)

    print("== 4/7: Audio post (sukunat siqish + turbo + SFX) ==")
    gap = float(cfg.get("audio", {}).get("silence_gap", 0.11))
    turbo = float(cfg.get("audio", {}).get("turbo", 1.15))
    for i, it in enumerate(items):
        sd = os.path.join(work, f"as_{i:02d}")
        os.makedirs(sd, exist_ok=True)
        it["audio"], it["words"], it["dur"] = audio.strip_dead_air(
            it["words"], it["audio"], sd, gap=gap)

    # --- davomiylik nazorati: 18-30s qattiy, maqsad 18-25s ---
    mn, mx = cfg["video"]["min_duration"], cfg["video"]["max_duration"]
    base = sum(it["dur"] for it in items)
    tempo = turbo
    if base / tempo > mx - 5.0:                       # 25s dan uzun -> tezroq
        tempo = min(1.30, base / (mx - 6.5))
        print(f"   qo'shimcha tempo: {tempo:.3f}x")
    if tempo != 1.0:
        for i, it in enumerate(items):
            fast = os.path.join(work, f"turbo_{i:02d}.wav")
            it["audio"] = audio.speed(it["audio"], tempo, fast)
            it["words"] = audio.scale_words(it["words"], 1.0 / tempo)
            it["dur"] /= tempo

    pads = [0.14] * len(items)
    total = sum(it["dur"] for it in items) + sum(pads)
    if total + 0.3 < mn:                              # juda qisqa -> pauzalar
        extra = (mn + 0.5 - total) / len(items)
        pads = [min(0.70, p + extra) for p in pads]
        print(f"   pauzalar kengaytirildi (+{extra:.2f}s/seg)")
    elif total > mx - 1.0:                            # hali uzun -> pauza siqish
        pads = [max(0.06, p * 0.4) for p in pads]
    for i, it in enumerate(items):
        it["dur"] += pads[i]
        it["scene"] = segs[i]
    print(f"   jami timeline: {sum(it['dur'] for it in items) + 0.3:.1f}s")

    # --- SFX triggerlar: kamera whoosh + LLM trigger + ikonka pop ---
    for i, it in enumerate(items):
        trig = []
        if i > 0:
            trig.append(("whoosh", 0.02, SFX_VOL["whoosh"]))
        for name in (segs[i].get("sfx_trigger") or [])[:2]:
            trig.append((name, 0.05, SFX_VOL.get(name, 0.4)))
        for ic in (segs[i].get("overlay_icons") or [])[:2]:
            t = _word_time(it["words"], ic.get("at_word"))
            trig.append(("pop", max(0.25, t), SFX_VOL["pop"]))
        if trig:
            it["audio"] = sfx.add_triggers(cfg, it["audio"], trig, work, i)

    print("== 5/7: Vizual: xarita kameralari + bayroqlar + ikonkalar ==")
    used_ids = set(history.clip_ids())
    for i, it in enumerate(items):
        sc = segs[i]
        vis = None
        bq = sc.get("fallback_broll_query") or []
        if bq:  # faqat insoniy reaksiya kerak bo'lsa stock b-roll
            try:
                clips = media.fetch_scene_media(
                    cfg, {"visual_query": bq, "must_contain": [],
                          "fallback": "", "on_screen": ""},
                    used_ids, os.path.join(work, f"b_{i:02d}"), n_want=1)
                if clips and not str(clips[0]["id"]).startswith(("map:", "card:")):
                    vis = {"type": "clip", "path": clips[0]["path"]}
                    used_ids.add(clips[0]["id"])
                    print(f"   seg{i + 1}: b-roll ({clips[0]['id']})")
            except Exception as e:
                print(f"   seg{i + 1}: b-roll xatosi ({e}) -> xarita")
        if vis is None:
            try:
                png, zs, ze = geo.compose_map(
                    sc["map_camera"], sc.get("country_iso_codes"), work)
                vis = {"type": "map", "path": png, "zs": zs, "ze": ze,
                       "label": sc["map_camera"].get("label", "")}
            except Exception as e:
                img = os.path.join(work, f"m_{i:02d}.png")
                maps.map_image(sc["map_camera"].get("label") or "world", img)
                vis = {"type": "map", "path": img, "zs": 1.05, "ze": 1.30,
                       "label": sc["map_camera"].get("label", "")}
                print(f"   seg{i + 1}: Esri yiqildi ({e}) -> vektor xarita")
        it["visual"] = vis
        ics = []
        for ic in (sc.get("overlay_icons") or [])[:2]:
            try:
                p = icons.get_icon(ic, work)
            except Exception as e:
                print(f"   ikonka xatosi: {e}")
                p = None
            if p:
                ics.append({"path": p,
                            "t": _word_time(it["words"], ic.get("at_word")),
                            "pos": ic.get("pos", [0.5, 0.3])})
        it["icons"] = ics

    print("== 6/7: Montaj (zoompan + subtitr + SFX + musiqa) ==")
    out = render.render(cfg, script, items, work)
    dur = _probe_dur(out)
    print(f"   final: {out} ({dur:.1f}s)")
    return out, dur, sorted(used_ids)


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
