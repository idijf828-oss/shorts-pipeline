# -*- coding: utf-8 -*-
# v10.1: ovoz zichligi + esri mode
r = open("src/render.py", encoding="utf-8").read()

old = (
    'f"[0:a]highpass=f=80,"\n'
    '                f"acompressor=threshold=0.125:ratio=3:attack=5:release=80,"\n'
    '                f"equalizer=f=3500:t=q:w=1:g=2,alimiter=limit=0.95,"'
)
n = r.count(old)
assert n == 1, f"n={n}"
new = (
    'f"[0:a]highpass=f=80,"\n'
    '                f"acompressor=threshold=0.10:ratio=4:attack=4:release=70,"\n'
    '                f"equalizer=f=3500:t=q:w=1:g=3,alimiter=limit=0.95,"'
)
r = r.replace(old, new, 1)

old2 = (
    'fc = (\n'
    '                f"[0:a]highpass=f=80,"\n'
    '                f"acompressor=threshold=0.125:ratio=3:attack=5:release=80,"\n'
    '                f"equalizer=f=3500:t=q:w=1:g=2,alimiter=limit=0.95,"'
)
assert old2 in r, "o2"
new2 = (
    'fc = (\n'
    '                f"[0:a]highpass=f=80,"\n'
    '                f"acompressor=threshold=0.10:ratio=4:attack=4:release=70,"\n'
    '                f"equalizer=f=3500:t=q:w=1:g=3,alimiter=limit=0.95,"'
)
r = r.replace(old2, new2, 1)
open("src/render.py", "w", encoding="utf-8").write(r)
print("ovoz zichligi OK (2 shox)")

g = open("src/geo.py", encoding="utf-8").read()
old = """    esri = _esri_base(lon, lat, wd, hd)
    if esri is not None:
        base, to_px = esri
        use_raster = True
        print(f"[geo] xarita z={z} (esri satellite)")"""
new = """    esri = _esri_base(lon, lat, wd, hd)
    mode = "esri" if esri is not None else None
    if esri is not None:
        base, to_px = esri
        use_raster = True
        print(f"[geo] xarita z={z} (esri satellite)")"""
assert old in g, "g2"
g = g.replace(old, new, 1)

old = """    return {"base": out_base, "fills": fills, "zs": zs, "ze": ze,
            "to_px": to_px, "centroids": centroids, "win": win,
            "mode": "raster" if use_raster else "vector"}"""
new = """    return {"base": out_base, "fills": fills, "zs": zs, "ze": ze,
            "to_px": to_px, "centroids": centroids, "win": win,
            "mode": mode or ("raster" if use_raster else "vector")}"""
assert old in g, "g3"
g = g.replace(old, new, 1)
open("src/geo.py", "w", encoding="utf-8").write(g)
print("geo mode OK")
