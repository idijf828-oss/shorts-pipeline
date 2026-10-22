"""V4 orkestrator — "map-explainer" (doc ARENA_MASTER):

  trend -> Gemini v4 skript (scenes: mode/map/highlights/events/queries)
  -> TTS (edge +15% / gTTS) -> audio post (gap<=0.12s, 1.15x, tail 0.5)
  -> vizual: xarita (Natural Earth, bayroq-fill qatlamlar, events) yoki
     validatsiyalangan stock (slug must/reject + OCR + vision)
  -> montaj (zoompan + punch, rangli subtitr, SFX, musiqa sidechain)
  -> Telegram tasdig'i -> YouTube.
"""
import argparse
import os
import subprocess
import traceback

from src.config import load
from src import (trends, history, script_gen, tts, audio, sfx, geo, events,
                 icons, media, render, telegram, upload)

SFX_VOL = {"pop": 0.42, "whoosh": 0.30, "ding": 0.40, "boom": 0.55,
           "alarm": 0.35, "riser": 0.38, "tick": 0.45}


def build_description(cfg, script):
    desc = (script.get("description") or "").strip()
    if not desc:
        segs = script.get("scenes") or script.get("segments") or []
        hook = segs[0]["voice"] if segs else ""
        facts = " ".join(s["voice"] for s in segs[1:7])
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

    print("== 2/7: Gemini v4 skript (map-explainer sxemasi) ==")
    hist = history.load()
    script = script_gen.write_script(cfg, tr, history.keywords(hist))
    if history.too_similar(script["title"], script["keywords"], hist):
        print("   mavzu tarix bilan o'xshash -> qayta generatsiya")
        script = script_gen.write_script(
            cfg, tr, history.keywords(hist), avoid_title=script["title"])
    segs = script.get("scenes") or script.get("segments")
    print(f"   sarlavha: {script['title']} "
          f"({len(segs)} sahna, {len(script['script'].split())} so'z, "
          f"{sum(1 for s in segs if s['mode'] == 'stock')} stock)")

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
    """Skript -> tayyor video. (out, davomiylik, klip id'lari)."""
    work = cfg["_paths"]["work"]
    os.makedirs(work, exist_ok=True)
    segs = script.get("scenes") or script.get("segments")

    print("== 3/7: TTS (edge / gTTS zaxira) ==")
    items = tts.synth(cfg, segs)
    gtts = any(it.get("engine") == "gtts" for it in items)

    print("== 4/7: Audio post (gap<=0.12s + 1.15x + tail) ==")
    gap = float(cfg.get("audio", {}).get("silence_gap", 0.12))
    turbo = float(cfg.get("audio", {}).get("turbo", 1.15))
    for i, it in enumerate(items):
        sd = os.path.join(work, f"as_{i:02d}")
        os.makedirs(sd, exist_ok=True)
        it["audio"], it["words"], it["dur"] = audio.strip_dead_air(
            it["words"], it["audio"], sd, gap=gap)

    mn, mx = cfg["video"]["min_duration"], cfg["video"]["max_duration"]
    base = sum(it["dur"] for it in items)
    tempo = turbo if gtts else 1.0     # doc C2: atempo faqat gTTS zaxira
    if base / tempo > mx - 1.0:                    # 39s dan uzun -> tezroq
        tempo = min(1.30, base / (mx - 2.5))
        print(f"   qo'shimcha tempo: {tempo:.3f}x")
    if tempo != 1.0:
        for i, it in enumerate(items):
            fast = os.path.join(work, f"turbo_{i:02d}.wav")
            it["audio"] = audio.speed(it["audio"], tempo, fast)
            it["words"] = audio.scale_words(it["words"], 1.0 / tempo)
            it["dur"] /= tempo

    pads = [0.18] * len(items)
    total = sum(it["dur"] for it in items) + sum(pads) + render.TAIL
    if total < mn + 1.0:                            # juda qisqa -> pauzalar
        extra = (mn + 1.2 - total) / len(items)
        pads = [min(1.00, p + extra) for p in pads]
        print(f"   pauzalar kengaytirildi (+{extra:.2f}s/seg)")
    elif total > mx - 0.5:
        pads = [max(0.08, p * 0.45) for p in pads]
    for i, it in enumerate(items):
        it["dur"] += pads[i]
        it["scene"] = segs[i]
    print(f"   jami timeline: {sum(it['dur'] for it in items) + render.TAIL:.1f}s"
          f" (tempo {tempo:.2f}x)")

    print("== 5/7: Vizual: xarita + bayroq-fill + events / stock ==")
    used_ids = set(history.clip_ids())
    shift = 0.15 if gtts else 0.0                   # doc B3: gTTS -> -0.15s
    for i, it in enumerate(items):
        sc = segs[i]
        layers, punches, vis = [], [], None
        if sc["mode"] == "stock" and sc.get("visual_query"):
            try:
                clips = media.fetch_scene_media(
                    cfg, sc, used_ids, os.path.join(work, f"b_{i:02d}"),
                    n_want=1)
                if clips and not str(clips[0]["id"]).startswith(("map:", "card:")):
                    vis = {"type": "clip", "path": clips[0]["path"]}
                    used_ids.add(clips[0]["id"])
                    print(f"   sahna {i + 1}: STOCK ({clips[0]['id']})")
            except Exception as e:
                print(f"   sahna {i + 1}: stock xatosi ({e}) -> xarita")
        if vis is None:
            try:
                ctx = geo.compose_map(sc["map"], sc.get("country_iso_codes"),
                                      work)
            except Exception as e:
                from src import maps
                img = os.path.join(work, f"m_{i:02d}.png")
                maps.map_image(sc["map"].get("focus") or "world", img)
                ctx = {"base": img, "fills": {}, "zs": 1.05, "ze": 1.30,
                       "to_px": lambda lo, la: (720, 1280), "centroids": {}}
                print(f"   sahna {i + 1}: geo yiqildi ({e}) -> vektor zaxira")
            layers, punches = events.build(cfg, sc, ctx, it["words"],
                                           work, i)
            if shift:
                for ly in layers:
                    ly["t"] = max(0.05, ly["t"] - shift)
                punches = [max(2, p - int(shift * 30)) for p in punches]
            vis = {"type": "map", "base": ctx["base"],
                   "zs": ctx["zs"], "ze": ctx["ze"]}
        it["visual"] = vis
        it["layers"] = layers
        it["punches"] = punches if vis["type"] == "map" else []

        # --- SFX: segment whoosh + LLM trigger + event SFX ---
        trig = []
        if i > 0:
            trig.append(("whoosh", 0.02, SFX_VOL["whoosh"]))
        for name in (sc.get("sfx_trigger") or [])[:2]:
            trig.append((name, 0.05, SFX_VOL.get(name, 0.4)))
        for ly in layers:
            trig.append((ly["sfx"], max(0.25, ly["t"]),
                         SFX_VOL.get(ly["sfx"], 0.35)))
        for p in it["punches"]:
            trig.append(("whoosh", p / 30.0, SFX_VOL["whoosh"]))
        if trig:
            it["audio"] = sfx.add_triggers(cfg, it["audio"], trig, work, i)

    print("== 6/7: Montaj (zoompan + punch + rangli subtitr + musiqa) ==")
    try:                       # NE2 raster cache (~175MB) — endi kerak emas
        geo._raster.cache_clear()
    except Exception:
        pass
    import gc
    gc.collect()
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
