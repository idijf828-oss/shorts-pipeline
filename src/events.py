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

from . import geo, icons

SFX_FOR = {"pin": "pop", "flag_fill": "pop", "arrow": "whoosh",
           "zoom": "whoosh", "line": "tick", "highlight": "ding",
           "icon": "pop"}

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


def build(cfg, scene, ctx, words, work, seg_i):
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
                       "sfx": "pop", "kind": "flag_fill", "iso": iso2})

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
                               "pos": None, "sfx": "pop", "kind": k,
                               "iso": iso2})
        elif k in ("highlight", "line"):
            png = geo.country_layer(target, k, work, ctx, tag=f"s{seg_i}")
            if png:
                layers.append({"path": png, "t": t, "full": True,
                               "pos": None, "sfx": SFX_FOR[k], "kind": k})
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
                           "sfx": "pop", "kind": "pin"})
        elif k == "arrow":
            png = icons.get_icon(
                {"emoji": f"arrow_{str(ev.get('dir', 'right')).lower()}"}, work)
            if png:
                layers.append({"path": png, "t": t, "full": False,
                               "pos": ev.get("pos") or (0.5, 0.42),
                               "sfx": "whoosh", "kind": "arrow"})
        elif k == "icon":
            png = icons.get_icon({"emoji": ev.get("emoji", "")}, work)
            if png:
                layers.append({"path": png, "t": t, "full": False,
                               "pos": ev.get("pos") or (0.5, 0.3),
                               "sfx": "pop", "kind": "icon"})
        elif k == "zoom":
            punches.append(max(2, int(t * 30)))

    # overlay_icons (v3 sxemasidan saqlangan) — icon eventlari kabi
    for ic in (scene.get("overlay_icons") or [])[:2]:
        png = icons.get_icon(ic, work)
        if png:
            layers.append({"path": png,
                           "t": _word_time(words, ic.get("at_word")),
                           "full": False, "pos": ic.get("pos") or (0.5, 0.3),
                           "sfx": "pop", "kind": "icon"})

    layers.sort(key=lambda l: l["t"])
    return layers, punches
