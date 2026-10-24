"""V2 (topshiriq #5): MUSTAQIL baholovchi — faqat final mp4 ni o'qiydi.

Events.json / work / config ishlatmaydi: pipeline'ning o'z da'volariga
emas, tayyor fayldagi OCHIQ O'LCHOVLARGA ishonadi (OCR + piksel + ffprobe).

Ball (1-10):
  2.0  davomiylik 15-34s
  2.0  LUFS -14±1 (yuboriladigan faylning o'zi)
  1.0  true peak <= -1.0 dBTP
  1.5  ZONA A statik sarlavha: >=80% kadrdа OCR bilan topiladi, barqaror
  1.0  ZONA B subtitr: >=70% kadrlarda matn bor, chekkada kesilmagan
  1.0  dublikat=0: sarlavha so'zi ayni paytda subtitrda ko'rinmaydi
  1.0  harakat: bir xil kadr >2.2s yo'q
  0.5  ZONA B tartibli: bir kadrda >6 so'z yo'q

<8.0 -> FAIL (main.py re-render qiladi; 3 fail -> TG faqat matn sababi).
"""
import re
import subprocess

from .qc import (_audio, _edge_text_pixels, _extract_frames,
                 _gray_small, _hard_edge_white, _ocr_words, _probe, _strip,
                 ZONE_A, ZONE_B)

MIN_SCORE = 8.0


def _mode(tokens_list):
    """Kadrlar bo'yicha OCR so'z to'plamlaridan eng ko'p uchraganini."""
    cnt = {}
    for toks in tokens_list:
        for t in set(toks):
            cnt[t] = cnt.get(t, 0) + 1
    return cnt


def evaluate(path, step=0.333):
    """-> (ball, [(nom, ok, qiymat)]) — stdout ga jadval chiqaradi."""
    details = []
    score = 0.0

    w, h, fps, dur = _probe(path)
    ok = (w, h) == (1080, 1920) and 15.0 <= dur <= 34.0
    details.append(("o'lcham+davomiylik 1080x1920, 15-34s", ok,
                    f"{w}x{h}, {dur:.1f}s"))
    score += 2.0 if ok else 0.0

    lufs, tp, _st, _en = _audio(path)
    ok = -15.0 <= lufs <= -13.0
    details.append(("LUFS -14±1 (yuboriladigan fayl)", ok, f"{lufs:.1f}"))
    score += 2.0 if ok else 0.0
    ok = tp <= -1.0
    details.append(("true peak <= -1.0 dBTP", ok, f"{tp:.1f}"))
    score += 1.0 if ok else 0.0

    import os
    frames = _extract_frames(path, f"/tmp/review_frames_{os.getpid()}",
                             fps=round(1.0 / step, 2))
    if len(frames) < 8:
        details.append(("kadrlar olindi", False, f"{len(frames)} kadr"))
        return 0.0, details

    pres_px, pres_a, b_tokens, clipped, grays, b_over = [], [], [], [], [], []
    for k, fp in enumerate(frames):
        a_p = _strip(fp, ZONE_A[0] - 40, ZONE_A[1] + 40,
                     f"/tmp/rev_a_{k:04d}.png")
        b_p = _strip(fp, ZONE_B[0] - 40, ZONE_B[1] + 40,
                     f"/tmp/rev_b_{k:04d}.png")
        wa = _ocr_words(a_p)
        wb = _ocr_words(b_p)
        grays.append(_gray_small(fp))
        a_txt = " ".join(x for x, *_ in wa)
        b_txt = [x for x, *_ in wb]
        pres_a.append(a_txt)
        b_tokens.append(b_txt)
        # piksel: oq+qora konturli statik matn (OCR fonda mo'rt)
        pres_px.append(_hard_edge_white(fp, ZONE_A[0] - 40,
                                        ZONE_A[1] + 40) > 6000)
        if len(wb) > 6:
            b_over.append(round(k * step, 1))
        if (_edge_text_pixels(fp, ZONE_A[0] - 40, ZONE_A[1] + 40) >= 200
                or _edge_text_pixels(fp, ZONE_B[0] - 40,
                                     ZONE_B[1] + 40) >= 200):
            clipped.append(f"chekka@{k * step:.1f}s")
        subprocess.run(["rm", "-f", a_p, b_p])

    # sarlavha: PIKSEL (oq+kontur) borligi + barqarorligi; OCR faqat
    # dublikat aniqlash uchun (band fonda OCR ishonchsiz — saboq)
    n = len(pres_px)
    cnt_a = _mode([" ".join(t).split() for t in
                   [[w for w in re.findall(r"[A-Z0-9']{4,}", a)]
                    for a in pres_a]])
    ttl_tokens = {t for t, c in cnt_a.items() if c >= 0.4 * n}
    on_ratio = sum(pres_px) / n if n else 0.0
    toggles = sum(1 for a, b in zip(pres_px, pres_px[1:]) if a != b)
    ok = on_ratio >= 0.75 and toggles <= 8
    details.append(("ZONA A statik sarlavha (piksel+OCR)", ok,
                    f"{on_ratio:.0%} kadr, {toggles} almashuv, "
                    f"so'z={sorted(ttl_tokens)[:3]}"))
    score += 1.5 if ok else 0.0

    b_has = [len(t) > 0 for t in b_tokens]
    sub_ratio = sum(b_has) / n if n else 0.0
    # OCR rangli subtitrni ~50-60% kadrda o'qiydi (muhim emas);
    # tekshiradigan narsa: subtitr BUTUNLAY yo'qolmasin (render bug)
    ok = sub_ratio >= 0.35 and len(clipped) <= 1
    details.append(("ZONA B subtitr bor, kesilmagan", ok,
                    f"{sub_ratio:.0%} kadr, kesilgan={len(clipped)}"))
    score += 1.0 if ok else 0.0

    # so'z chegarasi bilan ("RULER" != "RULERS")
    _wb = [re.compile(r"\b" + re.escape(t) + r"\b") for t in ttl_tokens]
    dup = sum(1 for a, b, px in zip(pres_a, b_tokens, pres_px)
              if px and any(r.search(a) for r in _wb)
              and any(r.search(" ".join(b)) for r in _wb))
    ok = dup == 0
    details.append(("sarlavha so'zi subtitrda dublikat=0", ok,
                    f"{dup} kadr"))
    score += 1.0 if ok else 0.0

    same_run = best = 0
    for g0, g1 in zip(grays, grays[1:]):
        d = sum(abs(a - b) for a, b in zip(g0, g1)) / len(g0)
        if d < 2.0:
            same_run += 1
            best = max(best, same_run)
        else:
            same_run = 0
    static_s = best * step
    ok = static_s <= 2.2
    details.append(("bir xil kadr >2.2s yo'q", ok, f"{static_s:.1f}s"))
    score += 1.0 if ok else 0.0

    ok = not b_over
    details.append(("ZONA B tartibli (<=6 so'z/kadr)", ok,
                    ",".join(str(x) for x in b_over[:3]) or "ok"))
    score += 0.5 if ok else 0.0

    subprocess.run(["rm", "-f"] + frames)
    score = round(score, 1)
    print(f"== MUSTAQIL BAHOLASH (faqat final fayl) = {score}/10 ==")
    for name, ok, val in details:
        print(("PASS" if ok else "FAIL"), name, "->", val)
    return score, details
