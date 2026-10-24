"""V6 orkestrator — "5 FACTS ABOUT {country}" listicle:

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
                 icons, media, render, telegram, upload, qc, style)


def build_description(cfg, script):
    desc = (script.get("description") or "").strip()
    if not desc:
        segs = script.get("scenes") or script.get("segments") or []
        hook = segs[0]["voice"] if segs else ""
        facts = " ".join(s["voice"] for s in segs[1:7])
        pc = script.get("pinned_comment") or "Which place should I cover next? 👇"
        desc = f"{hook}\n{facts}\n\n{pc}\nNew geography fact every day.\n"
    hashtags = script.get("hashtags") or ["shorts", "geography", "facts"]
    import re as _re
    clean = []
    for h in hashtags:
        hh = _re.sub(r"[^A-Za-z0-9_]", "", str(h))
        if hh and hh.lower() not in [c.lower() for c in clean]:
            clean.append(hh)
    tagline = " ".join("#" + c for c in clean[:3])
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

    print("== 2/7: LLM skript: 5-fakt listicle (Claude Opus 5.5 -> Gemini zaxira) ==")
    hist = history.load()
    script = script_gen.write_script(cfg, tr, history.keywords(hist))
    if history.too_similar(script["title"], script["keywords"], hist):
        print("   mavzu tarix bilan o'xshash -> qayta generatsiya")
        script = script_gen.write_script(
            cfg, tr, history.keywords(hist), avoid_title=script["title"])
    segs = script.get("scenes") or script.get("segments")
    print(f"   joy: {script.get('place', '?')} | sarlavha: {script['title']} "
          f"({len(segs)} sahna, {len(script['script'].split())} so'z, "
          f"{sum(1 for s in segs if s['mode'] == 'stock')} stock)")

    out, dur, used_ids, qc_tbl, qc_ok = produce_with_qc(cfg, script)
    if not qc_ok:
        fails = "\n".join(f"❌ {n}: {v}" for n, o, v in qc_tbl if not o)
        telegram.send_message(cfg, "⛔ QC 3 urinishda o'tmadi — video "
                                   "yuklanmadi.\n" + fails[:800])
        raise RuntimeError("QC darvozasi o'tmadi (3 urinish)")

    print("== 7/7: Telegram tasdig'i va yuklash ==")
    cap = telegram.caption(cfg, tr, script, dur)
    # Telegram chegarasi: caption <= 1024 belgi (run 19: 400 xatosi)
    qc_lines = [f"{'✅' if o else '❌'} {n}: {v}" for n, o, v in qc_tbl]
    budget = 1000 - len(cap)
    qc_txt, used_len = "", 0
    for ln in qc_lines:
        add = (1 if qc_txt else 0) + len(ln)
        if used_len + add > budget:
            break
        qc_txt = (qc_txt + "\n" + ln) if qc_txt else ln
        used_len += add
    cap = (cap + "\n\nQC:\n" + qc_txt) if qc_txt else cap
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


def produce(cfg, script, no_stock=False, tts_cache=None):
    """Skript -> tayyor video. (out, davomiylik, klip id'lari).
    no_stock: barcha stock sahnalar xaritaga (QC retry).
    tts_cache: TTS/audio natijalari keyingi urinishda qayta ishlatiladi."""
    work = cfg["_paths"]["work"]
    os.makedirs(work, exist_ok=True)
    segs = script.get("scenes") or script.get("segments")

    if tts_cache and tts_cache.get("raw"):
        import copy
        items = copy.deepcopy(tts_cache["raw"])       # XOM TTS natijasi
        gtts = any(it.get("engine") == "gtts" for it in items)
        print("   TTS cache'dan (urinish) — audio post qayta hisoblanadi")
    else:
        print("== 3/7: TTS (edge / gTTS zaxira) ==")
        items = tts.synth(cfg, segs)
        gtts = any(it.get("engine") == "gtts" for it in items)
        if tts_cache is not None:
            import copy
            tts_cache["raw"] = copy.deepcopy(items)

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
    # v7 immersive: pad'lar kengroq (referens pauzalari 0.6-1.5s)
    pad_s = float(cfg.get("audio", {}).get("pad_s", 0.7))
    overhead = pad_s * (len(items) - 1) + render.TAIL
    tempo = turbo if gtts else 1.0     # doc C2: atempo faqat gTTS zaxira
    if base + overhead > mx - 0.3:                # uzun -> tezroq
        tempo = min(1.35, base / (mx - 0.3 - overhead))
        print(f"   qo'shimcha tempo: {tempo:.3f}x "
              f"(overhead {overhead:.2f}s hisobga olinib)")
    if tempo != 1.0:
        for i, it in enumerate(items):
            fast = os.path.join(work, f"turbo_{i:02d}.wav")
            it["audio"] = audio.speed(it["audio"], tempo, fast)
            it["words"] = audio.scale_words(it["words"], 1.0 / tempo)
            it["dur"] /= tempo

    # pad = sahna OROASIDAGI tanaffus; oxirgi sahnaga pad YO'Q —
    # tail (0.5s)gina (doc P4: tail = dur - voice_end in 0.2..0.7)
    # min 0.35s: musiqa to'liq eshitiladigan pauza (doc P2) + nafas
    pads = [pad_s] * (len(items) - 1) + [0.0]
    total = sum(it["dur"] for it in items) + sum(pads) + render.TAIL
    if total < mn + 1.0:                            # juda qisqa -> pauzalar
        extra = (mn + 1.2 - total) / max(1, len(items) - 1)
        pads = [min(1.30, p + extra) for p in pads[:-1]] + [0.0]
        print(f"   pauzalar kengaytirildi (+{extra:.2f}s/seg)")
    elif total > mx - 0.5:
        pads = [max(0.40, p * 0.55) for p in pads[:-1]] + [0.0]
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
        # doc P3: bitta klip <=2.5s -> sahna uzunligiga qarab 2-3 klip
        n_want = min(3, max(1, int(-(-it["dur"] // style.CLIP_MAX_S))))
        if (not no_stock) and sc["mode"] == "stock" and sc.get("visual_query"):
            try:
                clips = media.fetch_scene_media(
                    cfg, sc, used_ids, os.path.join(work, f"b_{i:02d}"),
                    n_want=n_want)
                clips = [c for c in clips
                         if not str(c["id"]).startswith(("map:", "card:"))]
                if clips:
                    vis = {"type": "clip",
                           "paths": [c["path"] for c in clips]}
                    for c in clips:
                        used_ids.add(c["id"])
                    print(f"   sahna {i + 1}: STOCK ({len(clips)} klip: "
                          + ", ".join(str(c["id"]) for c in clips) + ")")
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
                                           work, i, dur=it["dur"])
            if shift:
                for ly in layers:
                    ly["t"] = max(0.05, ly["t"] - shift)
                punches = [max(2, p - int(shift * 30)) for p in punches]
            vis = {"type": "map", "base": ctx["base"],
                   "zs": ctx["zs"], "ze": ctx["ze"]}
        it["visual"] = vis
        it["layers"] = layers
        it["punches"] = punches if vis["type"] == "map" else []

        # --- SFX: v7 minimal (faqat kesish whoosh) yoki to'liq P2 ---
        minimal = str((cfg.get("sfx") or {}).get("mode", "")) == "minimal"
        trig = []
        # v9: kesish whoosh'i JORIY segment oxiridagi pauzada — keyingi
        # sahnaning birinchi so'zini bosmaydi (run 23: whoosh ovozni yopgan)
        last_end = max((w[2] for w in (it.get("words") or [("", 0, 0)])),
                       default=0.0)
        out_t = max(last_end + 0.04, it["dur"] - 0.30)
        if minimal:
            if i < len(items) - 1 and out_t < it["dur"] - 0.05:
                trig.append(("whoosh", out_t, None))
            if vis and vis["type"] == "clip":
                n_slots = max(1, int(-(-it["dur"] // style.CLIP_MAX_S)))
                for k in range(1, n_slots):
                    trig.append(("whoosh", k * style.CLIP_MAX_S, None))
        if not minimal:
            if i == 0:                 # hook: riser + 3.0s da impact
                trig.append(("riser", 0.0, None))
                trig.append(("impact", min(3.0, max(0.8, it["dur"] - 0.6)),
                             None))
            if i < len(items) - 1 and out_t < it["dur"] - 0.05:
                trig.append(("whoosh", out_t, None))
            if vis and vis["type"] == "clip":    # stock slot kesishlari
                n_slots = max(1, int(-(-it["dur"] // style.CLIP_MAX_S)))
                for k in range(1, n_slots):
                    trig.append(("whoosh", k * style.CLIP_MAX_S, None))
            for name in (sc.get("sfx_trigger") or [])[:2]:
                trig.append((name, 0.05, None))
            for ly in layers:                    # har eventda tovush
                trig.append((ly["sfx"], max(0.25, ly["t"]), None))
            for p in it["punches"]:
                trig.append(("whoosh", p / 30.0, None))
            if i == len(items) - 1:              # oxirgi "twist": impact
                twist = layers[-1]["t"] if layers else it["dur"] * 0.4
                trig.append(("impact", max(0.3, min(twist, it["dur"] - 0.4)),
                             None))
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


def produce_with_qc(cfg, script):
    """Doc P4: render -> qc.py gate -> FAIL bo'lsa max 3 urinish.
    1) musiqa darajasi xato -> faqat remiks (tezkor)
    2) boshqa -> stock o'chirilib qayta render (klip almashtirish)
    -> (out, dur, used_ids, qc_table, ok)"""
    work = cfg["_paths"]["work"]
    cache = {}
    out, dur, used_ids = produce(cfg, script, tts_cache=cache)
    ok, tbl = qc.run_checks(out, cfg, work)
    for attempt in (2, 3):
        if ok:
            break
        fails = [n for n, o, _ in tbl if not o]
        music_only = fails and all("musiqa" in f for f in fails)
        print(f"   QC urinish {attempt}: {fails}")
        if music_only:                           # faqat musiqa -> remiks
            cur = float(cfg.get("sfx", {}).get("music_volume", 0.125))
            val = next(v for n, o, v in tbl if not o and "musiqa" in n)
            try:
                mv = float(str(val).split("dB")[0].strip())
            except ValueError:
                mv = -40.0
            factor = 10 ** ((-27.0 - mv) / 20.0)      # -27 dB target
            if attempt == 3:                      # ikkinchi remiks: yumshat
                factor = 1.0 + (factor - 1.0) * 0.7
            cfg["sfx"]["music_volume"] = max(0.03, min(0.40, cur * factor))
            print(f"   musiqa remiks (urinish {attempt}): vol {cur:.3f} -> "
                  f"{cfg['sfx']['music_volume']:.3f}")
            out = render.remix(cfg, work, out)
        else:                                    # to'liq qayta (stock'siz)
            out, dur, used_ids = produce(cfg, script, no_stock=True,
                                         tts_cache=cache)
        ok, tbl = qc.run_checks(out, cfg, work)
    return out, dur, used_ids, tbl, ok


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
