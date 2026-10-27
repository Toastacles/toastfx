"""Build the skin (the user's design with the live controls cleared) and icon cutouts.

Run:  python3 build_assets.py [path/to/design.png]
Usage: python3 tools/build_assets.py path/to/design.png   (writes into ui/assets/)
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SRC = sys.argv[1] if len(sys.argv) > 1 else "design.png"
OUT = Path(__file__).resolve().parent.parent / "ui" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

im = Image.open(SRC).convert("RGB")
A = np.asarray(im).astype(np.float32)
RNG = np.random.default_rng(3)


def _blend(img, X0, Y0, X1, Y1, P, pad):
    h, w = Y1 - Y0, X1 - X0
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rectangle([pad, pad, w - pad - 1, h - pad - 1], fill=255)
    if pad:
        m = m.filter(ImageFilter.GaussianBlur(pad / 2.5))
    m = (np.asarray(m, np.float32) / 255)[:, :, None]
    img[Y0:Y1, X0:X1] = np.clip(img[Y0:Y1, X0:X1] * (1 - m) + P * m, 0, 255)


def flat(img, x0, y0, x1, y1, color, noise=1.2, pad=3):
    X0, Y0, X1, Y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    P = np.broadcast_to(np.array(color, np.float32), (Y1 - Y0, X1 - X0, 3)).copy()
    P += RNG.normal(0, noise, P.shape)
    _blend(img, X0, Y0, X1, Y1, P, pad)


def rowfill(img, x0, y0, x1, y1, sx0, sx1, noise=1.2, pad=3):
    """Fill with the panel's own vertical gradient, sampled from a clean column (sx0:sx1)."""
    X0, Y0, X1, Y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    rows = np.array([np.median(A[min(max(y, 0), 1023), sx0:sx1].reshape(-1, 3), 0) for y in range(Y0, Y1)])
    k = 11
    rows = np.stack([np.convolve(np.pad(rows[:, c], (k // 2, k // 2), mode="edge"), np.ones(k) / k, mode="valid")
                     for c in range(3)], 1)
    P = np.broadcast_to(rows[:, None, :], (Y1 - Y0, X1 - X0, 3)).copy()
    P += RNG.normal(0, noise, P.shape)
    _blend(img, X0, Y0, X1, Y1, P, pad)


S = A.copy()
flat(S, 868, 32, 1182, 150, (22, 21, 23), pad=10)                 # engine pill
flat(S, 1172, 46, 1428, 142, (17, 17, 19), pad=10)                # stop engine button
rowfill(S, 640, 186, 1010, 246, 1180, 1184)                       # sparks above the lit card
rowfill(S, 22, 244, 1178, 432, 1180, 1184)                        # voice cards
flat(S, 226, 455, 1010, 492, (17, 17, 19), noise=0.8)             # output meter bar
rowfill(S, 36, 552, 1176, 836, 1180, 1184)                        # sound tiles
flat(S, 1216, 505, 1504, 734, (23, 20, 22))                       # hotkey list
flat(S, 432, 902, 700, 966, (16, 16, 19))                         # volume slider + %
flat(S, 890, 902, 978, 956, (15, 15, 17))                         # toggle
flat(S, 1074, 903, 1216, 964, (15, 16, 19))                       # hint text
# Quick Tweaks: clear the three slider tracks + percentages so they can be drawn live
for cy in (271, 342, 412):
    rowfill(S, 1278, cy - 15, 1510, cy + 15, 1270, 1274)

# --- wording changes: wipe the old text, new text is drawn below ---
rowfill(S, 100, 456, 228, 492, 94, 98)                     # "OUTPUT"
flat(S, 1012, 455, 1170, 492, (17, 17, 19), noise=0.8)      # "ToastFX Mic" + dropdown arrow
rowfill(S, 134, 912, 258, 962, 126, 130)                   # "Stop all"
rowfill(S, 1280, 232, 1480, 258, 1270, 1274)               # "Radio Filter"
rowfill(S, 1280, 303, 1480, 329, 1270, 1274)               # "Helmet Filter"
skin = Image.fromarray(S.astype(np.uint8)).convert("RGBA")


def overlay(draw_fn, box):
    """Draw new text with the UI's own font code (design pixels, 1:1) onto the skin."""
    import sys as _s
    for cand in (Path(__file__).resolve().parent / "pkg", Path(__file__).resolve().parent.parent / "ui"):
        if (cand / "toastfx_ui.py").exists():
            _s.path.insert(0, str(cand))
    import toastfx_ui as U
    U.set_scale(1.0)
    cv = U.Cv(box[2] - box[0], box[3] - box[1])
    draw_fn(cv)
    skin.alpha_composite(cv.done(), dest=(box[0], box[1]))


def spaced(cv, x, y, text, size, color, gap):
    for ch in text:
        cv.text((x, y), ch, size, color, anchor="lm")
        x += cv.tw(ch, size) + gap


overlay(lambda cv: spaced(cv, 5, 18, "MIC LEVEL", 18, (255, 214, 150, 255), 1.2), (104, 457, 230, 493))
overlay(lambda cv: cv.text((12, 18), "ToastFX Mic", 21, (232, 224, 214, 255), bold=False, anchor="lm"), (1012, 457, 1170, 493))
overlay(lambda cv: (cv.text((63, 25), "Stop sounds", 28, (150, 52, 8, 110), maxw=124, anchor="mm"),
                    cv.text((62, 24), "Stop sounds", 28, (255, 255, 255, 255), maxw=124, anchor="mm")), (134, 912, 258, 962))
overlay(lambda cv: cv.text((3, 12), "Radio Strength", 17, (240, 232, 222, 255), bold=False, anchor="lm"), (1280, 232, 1480, 258))
overlay(lambda cv: cv.text((3, 12), "Helmet Strength", 17, (240, 232, 222, 255), bold=False, anchor="lm"), (1280, 303, 1480, 329))
skin = skin.convert("RGB")
skin.save(OUT / "skin.png")


def cutout(box, name, thr0=14, thr1=46, post=None):
    c = im.crop(box)
    a = np.asarray(c).astype(np.float32)
    edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(edge, 0)
    d = np.sqrt(((a - bg) ** 2).sum(2))
    al = np.clip((d - thr0) / (thr1 - thr0), 0, 1)
    if post:
        al = post(al)
    out = Image.fromarray(np.dstack([a, al * 255]).astype(np.uint8), "RGBA")
    bb = out.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    out = out.crop(bb) if bb else out
    return out


def helmet_mask(al):
    hh, ww = al.shape
    yy, xx = np.mgrid[0:hh, 0:ww]
    r = np.sqrt((xx - 52) ** 2 + (yy - 48) ** 2)
    return al * np.clip((43 - r) / 3, 0, 1)


ICONS = {"burst": (68, 588, 148, 656), "note": (362, 588, 430, 650), "chick": (655, 588, 728, 652),
         "flame": (935, 590, 995, 655), "cat": (70, 732, 140, 790), "pizza": (368, 728, 440, 792),
         "beer": (665, 728, 730, 795), "bread": (1015, 715, 1075, 755),
         "v_mic": (150, 262, 232, 345), "v_radio": (455, 258, 540, 345),
         "v_helmet": (745, 248, 850, 342), "v_robot": (1010, 258, 1105, 340)}
for name, box in ICONS.items():
    out = cutout(box, name, post=helmet_mask if name == "v_helmet" else None)
    if name == "v_radio":                       # drop the stray speck under the radio
        out.putalpha(out.getchannel("A").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3)))
        arr = np.asarray(out.getchannel("A"))
        rows = (arr > 60).sum(1)
        last = max(i for i, v in enumerate(rows) if v >= 6)
        out = out.crop((0, 0, out.width, last + 1))
    out.save(OUT / f"{name}.png")


def line_helmet(path, size=480):
    """Line-art helmet in the same rounded-stroke style as the mic / radio / robot icons.
    White on transparent; the UI tints it."""
    k = 4
    W = size * k
    img = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(img)
    sw = int(W * 0.036)

    def rr(box, r, width=sw):
        d.rounded_rectangle([v * W for v in box], int(r * W), outline=255, width=width)

    def cap(x0, y0, x1, y1):
        for (x, y) in ((x0, y0), (x1, y1)):
            d.ellipse([x * W - sw // 2, y * W - sw // 2, x * W + sw // 2, y * W + sw // 2], fill=255)

    # shell
    d.arc([0.20 * W, 0.12 * W, 0.80 * W, 0.78 * W], 180, 360, fill=255, width=sw)
    d.line([0.20 * W, 0.45 * W, 0.20 * W, 0.62 * W], fill=255, width=sw)
    d.line([0.80 * W, 0.45 * W, 0.80 * W, 0.62 * W], fill=255, width=sw)
    d.arc([0.20 * W, 0.46 * W, 0.80 * W, 0.90 * W], 0, 180, fill=255, width=sw)
    # top arch (the little handle)
    d.arc([0.36 * W, 0.04 * W, 0.64 * W, 0.34 * W], 180, 360, fill=255, width=sw)
    # ear caps
    rr((0.09, 0.42, 0.20, 0.66), 0.05)
    rr((0.80, 0.42, 0.91, 0.66), 0.05)
    # visor
    rr((0.27, 0.34, 0.73, 0.70), 0.13)
    # highlights
    d.arc([0.32 * W, 0.40 * W, 0.46 * W, 0.58 * W], 200, 300, fill=255, width=int(sw * .75))
    d.arc([0.58 * W, 0.50 * W, 0.68 * W, 0.64 * W], 20, 80, fill=255, width=int(sw * .75))
    for (x, y) in ((0.20, 0.45), (0.20, 0.62), (0.80, 0.45), (0.80, 0.62)):
        d.ellipse([x * W - sw // 2, y * W - sw // 2, x * W + sw // 2, y * W + sw // 2], fill=255)
    img = img.filter(ImageFilter.GaussianBlur(1.2)).resize((size, size), Image.LANCZOS)
    rgba = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    rgba.putalpha(img)
    bb = img.point(lambda v: 255 if v > 40 else 0).getbbox()
    rgba.crop(bb).save(path)


line_helmet(OUT / "v_helmet_line.png")

# contact sheet for eyeballing
names = list(ICONS) + ["v_helmet_line"]
sheet = Image.new("RGB", (len(names) * 130, 130), (38, 40, 50))
for i, n in enumerate(names):
    ic = Image.open(OUT / f"{n}.png")
    ic.thumbnail((110, 110))
    sheet.paste(ic, (i * 130 + 10, 10), ic)
sheet.save(Path(__file__).resolve().parent / "icons_check.png")
skin.resize((1152, 768)).save(Path(__file__).resolve().parent / "skin_check.png")
print("assets ok:", len(list(OUT.glob("*.png"))), "files")
