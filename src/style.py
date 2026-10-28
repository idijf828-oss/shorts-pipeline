"""V2 PRO design tokens (doc P1) — bitta manbadan hamma modul o'qiydi.

Rang = ma'no: oq matn, cyan ob'ekt/mamlakat, qizil xavf, sariq raqam/strelka.
Fon navy; aksentlar cheklangan. Shrift: BITTA oila (Montserrat ExtraBold),
subtitr 96px doimiy (2 qatorga bo'linadi, 96->80 faqat kam holatda).
Motion: ease-out, kirish 0.25-0.35s, pop 1.0->1.08->1.0.
Grade: hamma kadrga bir xil (eq + yengil vinyet); stock navy-teal tomonga.
"""

# --- palitra (doc P1) ---
NAVY = "#0B1F33"            # fon (okean)
WHITE = "#FFFFFF"           # matn
CYAN = "#00E5FF"            # aksent 1: ob'ekt/mamlakat
RED = "#FF2D2D"             # aksent 2: xavf/muhim
YELLOW = "#FFD400"          # aksent 3: raqam/strelka/aktiv so'z

PALETTE = {"cyan": CYAN, "red": RED, "yellow": YELLOW, "white": WHITE}

# --- shrift ---
FONT_FAMILY = "Montserrat ExtraBold"
FONT_FILE = "/usr/share/fonts/truetype/montserrat/Montserrat-ExtraBold.ttf"
CAPTION_SIZE = 100          # v10.1 (user): doim bir xil 100px; 2 qator -> \N
CAPTION_FIT_MIN = 72        # v10.2 (user): yagona so'z narvoni pastki
ONSCREEN_SIZE = 84          # tepa yorliq: yo'q yoki >=72px (doc P1/P4b)
ONSCREEN_MAX_DUR = 2.6      # v7 immersive: yorliq ~2.6s ko'rinadi (referens)
MID_SIZE = 132              # v7: o'rtadagi katta "reveal" so'zi (IN FRANCE)
MID_Y = 1080                # (eski - v11'da MID ishlatilmaydi)
# --- v11 (V2): qat'iy layout zonalalari (1080x1920) ---
ZONE_A = (120, 320)          # statik sarlavha
ZONE_B = (984, 1244)         # v13.5 (user #4): subtitr 0.58H=1114 atrofida
ZONE_C = (1420, 1750)        # ikonka / sticker / strelka
TITLE_MAX_W = 920            # sarlavha kenglik budjeti                # ~56% balandlikda (referens: 625/1080)
MID_DUR = 1.5               # ~1.5s ko'rinadi

# --- subtitr joyi (v13.5: pastki-o'rta 58%) ---
CAP_Y_MAP = 1114
CAP_Y_STOCK = 1114
SAFE_W = 860                # x: 110..970

# --- motion ---
EASE_IN_DUR = 0.15          # screen-qatlam fade
SLIDE_PX = 80
POP_SCALE = 1.08            # 1.0 -> 1.08 -> 1.0 (doc P1)

# --- color grade (doc P1: hamma kadrga bir xil) ---
GRADE_ALL = "eq=contrast=1.06:saturation=1.12,vignette=a=PI/6.5"  # v10: quyuq qirralar (qo'llanma)
GRADE_STOCK = ("colorbalance=rs=-0.08:gs=0.01:bs=0.12:"
               "rm=-0.05:gm=0.0:bm=0.07,eq=saturation=1.06:contrast=1.03")

# --- stock klip cheklovi (doc P3) ---
CLIP_MAX_S = 2.5            # bitta klip <= 2.5s
STATIC_MAX_S = 1.2          # statik kadr <= 1.2s (events.json bilan tekshiriladi)

# --- SFX darajalar (doc P2 jadvali; ovozga nisbatan dB -> amplituda) ---
# riser -8dB, impact -9, whoosh -12, flagpop -11, drop -12, swish -12,
# zip -13, ding -12, pop -12, tick -12, boom -9, alarm -10
# v11 (V2-3): HAMMA SFX ovozdan 10-14dB past ([-14, -10] oralig'ida)
SFX_DB = {"riser": -11, "impact": -12, "boom": -12, "alarm": -11,
          "whoosh": -12, "drop": -12, "swish": -12, "ding": -12,
          "pop": -12, "tick": -12, "flagpop": -11, "zip": -13}
# v7 immersive (referens: musiqasiz, juda toza): faqat yumshoq whoosh
MINIMAL_SFX_DB = {"whoosh": -18}   # v9: ovozni bosmasin
EXPLAINER_SFX_DB = {"whoosh": -20, "pop": -18, "drop": -18,
                    "flagpop": -18, "swish": -18, "impact": -17}  # v10: nozik


def sfx_vol(name):
    """Nom bo'yicha amplituda (ovozdan ~SFX_DB past, +2dB envelop uchun)."""
    import math
    db = SFX_DB.get(name, -12) + 2
    return round(10 ** (db / 20), 3)
