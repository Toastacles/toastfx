#!/usr/bin/env python3
"""One baguette for the whole ToastFX design.

Draws the master baguette sprite (supersampled, so it is crisp at any size), swaps every old,
different baguette in ui/assets/skin.png for it, and writes:
  ui/assets/bread.png            the small icon the "+ Add sound" tile uses
  ui/assets/app_icon.png         the 256 px launcher icon (menu / taskbar)
  packaging/extras/toastfx.png   the same icon, for the .deb

Run from the repo root:  python3 tools/baguette.py
Needs: pillow, numpy, opencv-python (cv2).
"""
import math, pathlib, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import cv2

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "ui" / "assets"
TILT = 28            # degrees, long axis rises to the right (like the old ones)

OUTLINE = (78, 42, 22)
TOP, BOT = np.array((246, 205, 128)), np.array((209, 134, 64))
SLASH = (252, 232, 182)


def master(w=1200, h=520, ss=1):
    """Baguette, un-rotated, RGBA, w x h px."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h / 2
    a, b, n = w / 2 - 14, h / 2 - 14, 2.7                     # superellipse: long, round-ended loaf
    inside = (np.abs((xx - cx) / a) ** n + np.abs((yy - cy) / b) ** n) <= 1.0
    edge_in = (np.abs((xx - cx) / (a - 26)) ** n + np.abs((yy - cy) / (b - 26)) ** n) <= 1.0

    t = np.clip((yy - (cy - b)) / (2 * b), 0, 1)[..., None]    # light on top, toasty underneath
    body = TOP * (1 - t) + BOT * t
    body = body + (np.abs((xx - cx) / a) ** 2)[..., None] * -14   # slightly darker at the ends
    rgb = np.where(edge_in[..., None], body, np.array(OUTLINE, np.float32))
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    img.putalpha(Image.fromarray((inside * 255).astype(np.uint8)))

    d = ImageDraw.Draw(img)
    # soft highlight along the top
    hl = Image.new("L", (w, h), 0)
    ImageDraw.Draw(hl).ellipse((cx - a * 0.72, cy - b * 0.78, cx + a * 0.62, cy - b * 0.34), fill=70)
    hl = hl.filter(ImageFilter.GaussianBlur(14))
    img = Image.composite(Image.new("RGBA", (w, h), (255, 244, 214, 255)), img,
                          ImageChops.multiply(hl, img.getchannel("A")))
    # three scoring slashes
    d = ImageDraw.Draw(img)
    for k in (-0.40, 0.0, 0.40):
        px, py = cx + k * a, cy - b * 0.06
        L, W, ang = b * 1.00, b * 0.27, math.radians(42)
        pts = []
        for s in np.linspace(-1, 1, 24):                       # leaf-shaped cut
            hw = W * 0.5 * (1 - s * s) ** 0.8
            pts.append((s * L * 0.5, -hw))
        pts += [(p[0], -p[1]) for p in reversed(pts)]
        rot = [(px + x * math.cos(ang) - y * math.sin(ang),
                py - (x * math.sin(ang) + y * math.cos(ang))) for x, y in pts]
        d.polygon(rot, fill=SLASH, outline=OUTLINE)
        d.line(rot + [rot[0]], fill=OUTLINE, width=max(4, int(b * 0.05)), joint="curve")
    return img


def rotated(img, target_w):
    r = img.rotate(TILT, resample=Image.BICUBIC, expand=True)
    r = r.crop(r.getbbox())
    h = round(r.height * target_w / r.width)
    return r.resize((target_w, h), Image.LANCZOS)


def with_shadow(sprite, soft=3, strength=0.38, dy=2):
    pad = soft * 3
    out = Image.new("RGBA", (sprite.width + pad * 2, sprite.height + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (20, 8, 0, 0))
    sh.putalpha(Image.new("L", out.size, 0))
    a = Image.new("L", out.size, 0)
    a.paste(sprite.getchannel("A"), (pad, pad + dy))
    a = a.filter(ImageFilter.GaussianBlur(soft)).point(lambda v: int(v * strength))
    sh.putalpha(a)
    out.alpha_composite(sh)
    out.alpha_composite(sprite, (pad, pad))
    return out


# where the old baguettes were (centre x, y, drawn width, old half-axes), in skin.png pixels
SPOTS = {
    "header":     (825, 126, 58, (33, 24)),
    "voice tag":  (58, 211, 46, (27, 20)),
    "soundboard": (53, 540, 44, (25, 19)),
    "tweaks":     (1237, 197, 46, (27, 20)),
    "stop":       (91, 935, 74, (45, 33)),
}


def swap_in_skin(sprite):
    skin = Image.open(ASSETS / "skin.png").convert("RGB")
    bgr = cv2.cvtColor(np.array(skin), cv2.COLOR_RGB2BGR)
    mask = np.zeros(bgr.shape[:2], np.uint8)
    for cx, cy, _w, (ea, eb) in SPOTS.values():
        cv2.ellipse(mask, (cx, cy), (ea, eb), -TILT, 0, 360, 255, -1)
    bgr = cv2.inpaint(bgr, mask, 4, cv2.INPAINT_TELEA)
    skin = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")
    for cx, cy, w, _ in SPOTS.values():
        s = with_shadow(rotated(sprite, w))
        skin.alpha_composite(s, (round(cx - s.width / 2), round(cy - s.height / 2)))
    skin.convert("RGB").save(ASSETS / "skin.png", optimize=True)


def app_icon(sprite, size=256):
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    m = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), size * 4 // 5 // 2 * 1, fill=255)
    m = m.resize((size, size), Image.LANCZOS)
    yy = np.linspace(0, 1, size)[:, None, None]
    top, bot = np.array((58, 36, 24)), np.array((28, 18, 12))
    grad = (top * (1 - yy) + bot * yy) * np.ones((1, size, 1))
    card = Image.fromarray(grad.astype(np.uint8), "RGB").convert("RGBA")
    card.putalpha(m)
    bg.alpha_composite(card)
    ImageDraw.Draw(bg)
    s = with_shadow(rotated(sprite, int(size * 0.80)), soft=6, strength=0.5, dy=5)
    bg.alpha_composite(s, ((size - s.width) // 2, (size - s.height) // 2 + 2))
    return bg


def main():
    sp = master()
    swap_in_skin(sp)
    small = rotated(sp, 160)
    small.save(ASSETS / "bread.png", optimize=True)
    icon = app_icon(sp)
    icon.save(ASSETS / "app_icon.png", optimize=True)
    (ROOT / "packaging" / "extras").mkdir(parents=True, exist_ok=True)
    icon.save(ROOT / "packaging" / "extras" / "toastfx.png", optimize=True)
    print("done")


if __name__ == "__main__":
    main()
