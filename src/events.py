"""Events: so'z vaqtida chiqadigan vizual hodisalar (doc B3).

Turlari:
  flag_fill — davlat poligoni bayroq bilan to'ladi (geo qatlami, reveal)
  highlight — davlat cyan glow bilan yoritiladi
  line      — davlat chegarasi qalin sariq chiziq
  pin       — joy belgilash pin (target davlat centroid yoki lat/lon)
  arrow     — sariq strelka (dir: left/right/up/down)
  icon      — emoji sticker (icons.py)
  zoom      — kamera "punch" (zoompan +gauss)

Har event aniq so'z vaqtidan (edge WordBoundary) vaqt oladi va
SFX bilan birga chiqadi: pop (pin/flag), whoosh (arrow/zoom), tick (line),
ding (highlight). SFX ovozdan -12dB past.
"""
import os

from . import captions as _cap
from . import geo, icons

SFX_FOR = {"pin": "drop", "flag_fill": "flagpop", "arrow": "swish",
           "zoom": "whoosh", "line": "zip", "highlight": "ding",
           "icon": "pop"}          # doc P2 SFX xaritasi

W_CENTER = 720  # geo canvas kengligi markazi (1440)


def _word_time(words, target, default=0.35):
    t = str(target or "").lower().strip(".,!?\"'")
    if t:
        for (w, s, _e) in words:
            if t in str(w).lower().strip(".,!?\"'"):
                return max(0.15, s - 0.03)
    return default


def _first_highlight_time(scene, words, default=0.2):
    hl = [h.get("word") for h in (scene.get("highlights") or [])
          if h.get("word")]
    for w in hl:
        if not w:
            continue
        for (wd, s, _e) in words:
            if str(w).lower().strip(".,!?\"'") in str(wd).lower().strip(".,!?\"'"):
                return max(0.15, s - 0.03)
    return default


def build(cfg, scene, ctx, words, work, seg_i, dur=None):
    """scene events + country_iso fills -> ([layer], [punch_frame]).

    layer = {"path": png, "t": sek, "full": bool, "pos": (x, y) | None,
             "sfx": nom, "kind": tur}
    """
    layers, punches = [], []
    evs = list(scene.get("events") or [])[:4]

    # bayroq-fill: events da aniq vaqt berilmasa, birinchi highlight
    # so'zida (yoki 0.2s da) reveal qilinadi
    def _visible(iso2):
        """Bayroq-fill faqat davlat xarita oynasida KO'RINSA (run 23:
        Shveytsariya kadriga Janubiy Afrika bayrog'i tushgan).
        Centroid oynada YOKI davlat poligoni oyna bilan kesishsa."""
        c = (ctx.get("centroids") or {}).get(iso2)
        if c:
            x, y = float(c[0]), float(c[1])
            if -80 <= x <= W_CENTER * 2 + 80 and -80 <= y <= 2560 + 80:
                return True
        win = ctx.get("win")
        iso3s = set(geo.resolve(iso2))
        if not win or not iso3s:
            return True                      # bilmaymiz -> qoldiramiz
        w0, n0, wd, hd = win
        m = 0.15                             # 15% chegara
        exp = (w0 - wd * m, n0 + hd * m, wd * (1 + 2 * m), hd * (1 + 2 * m))
        for (iso3, _nm, rings, _c) in geo._countries():
            if iso3 in iso3s and geo._in_window(rings, exp):
                return True
        return False

    ev_fill = [e for e in evs if str(e.get("type")) == "flag_fill"]
    for iso2, png in (ctx.get("fills") or {}).items():
        if any(str(e.get("target", "")).lower() == iso2.lower()
               for e in ev_fill):
            continue
        if not _visible(iso2):
            continue
        t = _first_highlight_time(scene, words)
        layers.append({"path": png, "t": t, "full": True, "pos": None,
                       "sfx": "flagpop", "kind": "flag_fill", "iso": iso2,
                       "word_t": t})

    for ev in evs:
        k = str(ev.get("type", "")).strip()
        t = _word_time(words, ev.get("at_word"))
        target = ev.get("target", "")
        if k == "flag_fill":
            iso2 = str(target).upper()[:2]
            png = (ctx.get("fills") or {}).get(iso2) or \
                     (ctx.get("fills") or {}).get(iso2.upper())
            if png and _visible(iso2):
                layers.append({"path": png, "t": t, "full": True,
                               "pos": None, "sfx": SFX_FOR.get(k, "flagpop"),
                               "kind": k, "iso": iso2, "word_t": t})
        elif k in ("highlight", "line"):
            png = geo.country_layer(target, k, work, ctx, tag=f"s{seg_i}")
            if png:
                layers.append({"path": png, "t": t, "full": True,
                               "pos": None, "sfx": SFX_FOR[k], "kind": k,
                               "word_t": t})
        elif k == "pin":
            pos = None
            iso_t = str(target or "").strip()
            want = set(geo.resolve(iso_t))
            if not want:                    # target ISO emas -> sahna davlati
                for c in (scene.get("country_iso_codes") or []):
                    if geo.resolve(str(c)[:2]):
                        iso_t = str(c)[:2].upper()
                        want = set(geo.resolve(iso_t))
                        break
            if ev.get("lat") is not None and ev.get("lon") is not None:
                try:
                    lo, la = float(ev["lon"]), float(ev["lat"])
                    pos = ctx["to_px"](lo, la)
                    # run 23: pin OKEANGA tushgan. Zanjir (v10.2):
                    # 1) eng yaqin quruqlikka snap (~3km, NE mayda
                    #    yarimorollarni yo'qotadi — Point Roberts kabi);
                    # 2) snap topmasa va kamera yaqin (z>=8) — joyida
                    #    qoladi (centroid'ga uchish undan ham yomon);
                    # 3) faqat keng kadrdagi aniq suv -> centroid.
                    if geo.point_on_land(lo, la) is False:
                        sn = geo.snap_to_land(lo, la)
                        if sn:
                            lo, la = sn
                            pos = ctx["to_px"](lo, la)
                            print(f"[events] pin {iso_t}: suv -> snap "
                                  f"({la:.4f},{lo:.4f})")
                        elif int((scene.get("map") or {}).get("zoom_level", 5)) >= 8:
                            print(f"[events] pin {iso_t}: quruqlik "
                                  f"poligoni topilmadi (z>=8) — joyida "
                                  f"qoldi ({la:.4f},{lo:.4f})")
                        else:
                            print(f"[events] pin {iso_t}: ({la:.2f},"
                                  f"{lo:.2f}) suvda -> centroid")
                            pos = None
                except Exception:
                    pos = None
            if pos is None:
                for iso2, c in (ctx.get("centroids") or {}).items():
                    if set(geo.resolve(iso2)) & want:
                        pos = c
                        break
            if pos is None:
                pos = (W_CENTER, 0.35 * 2560)
            # shahar nomi label ("Canberra"): target ISO bo'lmasa focus'dan
            t_label = str(target or "").strip()
            if len(t_label) <= 3 or not t_label:
                t_label = str(scene.get("map", {}).get("focus") or "")
            png = geo.pin_png(work, label=t_label[:18])
            layers.append({"path": png, "t": t, "full": False, "pos": pos,
                           "sfx": "drop", "kind": "pin", "word_t": t})
        elif k == "label":
            # v10: davlat nomi yorlig'i (kichik qora lavha, oq matn)
            pos = None
            want = set(geo.resolve(target))
            for iso2, c in (ctx.get("centroids") or {}).items():
                if set(geo.resolve(iso2)) & want:
                    pos = c
                    break
            if pos is None and ev.get("lat") is not None:
                try:
                    pos = ctx["to_px"](float(ev["lon"]), float(ev["lat"]))
                except Exception:
                    pos = None
            if pos is None:
                pos = (W_CENTER, 0.30 * 2560)
            png = geo.label_png(target, work)
            if png:
                layers.append({"path": png, "t": t, "full": False, "pos": pos,
                               "sfx": None, "kind": "label", "word_t": t,
                               "text": str(target)[:22]})
        elif k == "arrow":
            # v10.2 (user #3): strelka FAQAT haqiqiy manzilga. Pozitsiya va
            # yo'nalish koordinatadan: ko'rinish markazi -> manzil vektori.
            # Manzil yo'q -> strelka tashlanadi (tasodifiy yo'nalish YO'Q).
            apos = None
            if ev.get("lat") is not None and ev.get("lon") is not None:
                try:
                    apos = ctx["to_px"](float(ev["lon"]), float(ev["lat"]))
                except Exception:
                    apos = None
            if apos is None:
                t_iso = str(target or "").strip()[:2].upper()
                if geo.resolve(t_iso):
                    c = (ctx.get("centroids") or {}).get(t_iso)
                    if c:
                        apos = c
            if apos is None:
                print(f"[events] arrow '{target}': manzil topilmadi "
                      "-> olib tashlandi")
                continue
            import math
            dx = apos[0] - W_CENTER
            dy = apos[1] - 1280.0
            if abs(dx) < 1 and abs(dy) < 1:
                continue
            ang = math.atan2(dy, dx)
            off = 340.0                      # manzil oldida turadi
            pos = (apos[0] - math.cos(ang) * off,
                   apos[1] - math.sin(ang) * off)
            d = "right" if abs(dx) >= abs(dy) and dx > 0 else \
                "left" if abs(dx) >= abs(dy) else \
                "down" if dy > 0 else "up"
            png = icons.get_icon({"emoji": f"arrow_{d}"}, work)
            if png:
                layers.append({"path": png, "t": t, "full": False,
                               "pos": pos, "sfx": "swish", "kind": "arrow",
                               "word_t": t})
        elif k == "icon":
            png = icons.get_icon({"emoji": ev.get("emoji", "")}, work)
            if png:
                layers.append({"path": png, "t": t, "full": False,
                               "pos": ev.get("pos") or (0.5, 0.3),
                               "sfx": "pop", "kind": "icon", "word_t": t})
        elif k == "zoom":
            punches.append(max(2, int(t * 30)))

    # overlay_icons (v3 sxemasidan saqlangan) — icon eventlari kabi
    for ic in (scene.get("overlay_icons") or [])[:2]:
        png = icons.get_icon(ic, work)
        if png:
            wt = _word_time(words, ic.get("at_word"))
            layers.append({"path": png, "t": wt, "full": False,
                           "pos": ic.get("pos") or (0.5, 0.3),
                           "sfx": "pop", "kind": "icon", "word_t": wt})

    layers.sort(key=lambda l: l["t"])

    # doc P3: har <=1.2s da vizual hodisa — katta bo'shliqlarga
    # mikro zoom-punch qo'shamiz (real vizual o'zgarish, yumshoq gauss).
    # Belgilar: cut(0) + qatlamlar + punchlar + SUBTITR almashinuvi
    # (chunk onsetlari ham katta vizal o'zgarish) + sahna oxiri.
    cap_marks = []
    try:
        if words:
            cap_marks = [max(0.0, c[0][1]) for c in _cap.chunk(words)]
    except Exception:
        cap_marks = []
    end_mark = []
    if dur:
        ep = max(0.4, min(dur - 0.5, dur - 0.35))
        # pad (>=0.35s) dan TASHQARIDA: oxirgi so'z ostida kick,
        # pad oynasi toza musiqa uchun qoladi (doc P2/P4e)
        ep = max(0.4, dur - 0.55)
        end_mark = [ep]
        punches.append(max(2, int(ep * 30)))
    marks = sorted({0.0}
                   | {l["t"] for l in layers}
                   | {p / 30.0 for p in punches}
                   | set(cap_marks)
                   | set(end_mark))
    changed = True
    guard = 0
    while changed and guard < 8:
        changed, guard = False, guard + 1
        for a, b in zip(marks, marks[1:]):
            if b - a > 1.15:
                mid = round(a + (b - a) / 2.0, 2)
                marks = sorted(marks + [mid])
                punches.append(max(2, int(mid * 30)))
                changed = True
                break
    # v10.2 (user #3): bayroq doimiyligi — oldingi sahna flaglari yangi
    # sahnada t=0 da ham chizilsin (kadrda ko'rinsa). Miltillash yo'q.
    if (ctx.get("sticky_fills") or []) and (ctx.get("fills") or {}):
        have = {str(l.get("iso")) for l in layers if l.get("kind") == "flag_fill"}
        for iso2 in ctx["sticky_fills"]:
            png = ctx["fills"].get(iso2)
            if png and iso2 not in have and _visible(iso2):
                layers.append({"path": png, "t": 0.0, "full": True,
                               "pos": None, "sfx": None, "kind": "flag_fill",
                               "iso": iso2, "word_t": 0.0, "sticky": True})
    # v13.5 (user #3): ERTA pin — skript darajasidagi pin (o'z sahnasida
    # faqat video oxirida chiqardi) endi boshidan ko'rinadi: birinchi
    # xarita sahnada ~2-3s (ob'ekt haqida gap boshlanishi), keyingi
    # sahnalarda kesishdan keyin darhol. Pin o'z sahnasida so'z vaqtida
    # alohida (drop SFX bilan) chiqaveradi — bu yerda faqat BOSHQA
    # sahnalar uchun qo'shamiz. Kadrdan tashqaridagi sahnalarda chiqmaydi.
    sp = ctx.get("script_pin")
    if sp and not any(l.get("kind") == "pin" for l in layers):
        pos = None
        try:
            pos = ctx["to_px"](float(sp["lon"]), float(sp["lat"]))
        except Exception:
            pos = None
        # v13.5: sahna labeli pin nuqtasining atrofida bo'lsa (~260px
        # canvas) — erta pin CHIQMAYDI: label allaqachon joyni
        # belgilaydi, ikkalasi bir-birining ustiga tushib qolmaydi
        # (Moynaq S0: KZ label + early pin; Canada test S4).
        near_lbl = False
        if pos is not None:
            for l in layers:
                if l.get("kind") == "label" and l.get("pos"):
                    dx = abs(float(l["pos"][0]) - float(pos[0]))
                    dy = abs(float(l["pos"][1]) - float(pos[1]))
                    if (dx * dx + dy * dy) ** 0.5 < 260:
                        near_lbl = True
                        break
        png = geo.pin_png(work, label=str(sp.get("label") or "")[:18]) \
            if (pos is not None and not near_lbl) else None
        # v13.5: quti TO'LIQ sig'masa (chetga clamp -> pin noto'g'ri
        # joyda ko'rinadi) yoki kadrdan tashqarida bo'lsa — chiqarmaymiz.
        # _screen_fc: tx=pos_x*0.75, X=tx-256*k, Sw=max(340, iw*k),
        # k=340/512; Y=ty-480*k, balandlik 340. ZONA_A (sarlavha
        # [120,320]) bilan kesishmasin: box tepasi >= 332.
        ok_pos = False
        if pos is not None and png:
            try:
                from PIL import Image as _Im
                iw, _ih = _Im.open(png).size
                _k = 340.0 / 512.0
                _sw = max(340, int(iw * _k))
                tx = pos[0] * 1080.0 / 1440.0
                ty = pos[1] * 1920.0 / 2560.0
                ok_pos = (170 + 6 <= tx <= 1080 - _sw + 170 - 6
                          and ty - 319 >= 332 and ty <= 1890)
            except Exception:
                ok_pos = False
        if ok_pos:
            first = not sp.get("shown_once")
            t = max(2.0, min(3.0, _first_highlight_time(scene, words, 2.2))) \
                if first else 0.15
            if png:
                layers.append({"path": png, "t": t, "full": False,
                               "pos": pos, "sfx": "drop" if first else None,
                               "kind": "pin", "word_t": t, "early": True})
                sp["shown_once"] = True
    return layers, punches
