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
    ev_fill = [e for e in evs if str(e.get("type")) == "flag_fill"]
    for iso2, png in (ctx.get("fills") or {}).items():
        if any(str(e.get("target", "")).lower() == iso2.lower()
               for e in ev_fill):
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
            if png:
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
            if ev.get("lat") is not None and ev.get("lon") is not None:
                try:
                    pos = ctx["to_px"](float(ev["lon"]), float(ev["lat"]))
                except Exception:
                    pos = None
            if pos is None:
                want = set(geo.resolve(target))
                for iso2, c in (ctx.get("centroids") or {}).items():
                    if set(geo.resolve(iso2)) & want:
                        pos = c
                        break
            if pos is None:
                pos = (W_CENTER, 0.35 * 2560)
            png = geo.pin_png(work)
            layers.append({"path": png, "t": t, "full": False, "pos": pos,
                           "sfx": "drop", "kind": "pin", "word_t": t})
        elif k == "arrow":
            png = icons.get_icon(
                {"emoji": f"arrow_{str(ev.get('dir', 'right')).lower()}"}, work)
            if png:
                layers.append({"path": png, "t": t, "full": False,
                               "pos": ev.get("pos") or (0.5, 0.42),
                               "sfx": "swish", "kind": "arrow", "word_t": t})
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
        ep = max(0.4, dur - 0.35)
        end_mark = [ep]
        punches.append(max(2, int(ep * 30)))   # cut oldidan zoom-kick
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
    return layers, punches
