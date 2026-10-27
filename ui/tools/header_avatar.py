#!/usr/bin/env python3
"""Replace the header mascot in ui/assets/skin.png with a round avatar badge (mirrored so it faces the title).

Usage: python3 tools/header_avatar.py AVATAR.png [--cutout] [--no-flip] [skin.png]
  --cutout  the picture is a transparent character (not a square photo): no circle or ring, soft shadow only
Needs: pillow, numpy, opencv-python (pip install --user opencv-python-headless).
The old mascot is painted out with inpainting (the header background is nearly flat), the avatar is cut to a circle,
given a warm ring and soft shadow, and two small sparkles are redrawn. Safe to run again with another picture.
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

args = [a for a in sys.argv[1:] if not a.startswith("--")]
FLIP = "--no-flip" not in sys.argv
CUTOUT = "--cutout" in sys.argv          # a transparent full-body picture: stand it in the header, no ring
avatar_path = Path(args[0])
skin_path = Path(args[1]) if len(args) > 1 else Path(__file__).resolve().parent.parent / "ui" / "assets" / "skin.png"

CLEAR = (34, 22, 226, 178)                 # box that held the old mascot and its sparkles (design pixels)
CX, CY, R = 128, 99, 74                    # badge centre and radius
SS = 4

skin = Image.open(skin_path).convert("RGB")
a = np.array(skin)
mask = np.zeros(a.shape[:2], np.uint8)
mask[CLEAR[1]:CLEAR[3], CLEAR[0]:CLEAR[2]] = 255
a = cv2.inpaint(a, mask, 9, cv2.INPAINT_TELEA)
skin = Image.fromarray(a).convert("RGBA")

av = Image.open(avatar_path).convert("RGBA")
if CUTOUT:
    av = av.crop(av.getchannel("A").getbbox())            # trim the empty margin
    if FLIP:
        av = ImageOps.mirror(av)
    box_w, box_h = CLEAR[2] - CLEAR[0] - 10, CLEAR[3] - CLEAR[1] - 6
    sc = min(box_w / av.width, box_h / av.height)
    w2, h2 = max(1, round(av.width * sc)), max(1, round(av.height * sc))
    big = av.resize((w2 * SS, h2 * SS), Image.LANCZOS)
    canvas = Image.new("RGBA", (w2 * SS + 40 * SS, h2 * SS + 40 * SS), (0, 0, 0, 0))
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 150), (20 * SS, 20 * SS + 4 * SS), big.getchannel("A"))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4 * SS)))
    canvas.alpha_composite(big, dest=(20 * SS, 20 * SS))
    pic = canvas.resize((canvas.width // SS, canvas.height // SS), Image.LANCZOS)
    x0 = (CLEAR[0] + CLEAR[2]) // 2 - pic.width // 2
    y0 = CLEAR[3] - 4 - pic.height + 20
    skin.alpha_composite(pic, dest=(x0, y0))
    sparkle_a, sparkle_b = (CLEAR[2] - 10, CLEAR[1] + 12), (CLEAR[0] + 6, CLEAR[3] - 18)
else:
    w, h = av.size
    s = min(w, h)
    av = av.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    if FLIP:
        av = ImageOps.mirror(av)

    D = 2 * R
    big = Image.new("RGBA", ((D + 40) * SS, (D + 40) * SS), (0, 0, 0, 0))
    c = (D + 40) * SS // 2
    # shadow
    sh = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([c - R * SS, c - R * SS + 6 * SS, c + R * SS, c + R * SS + 6 * SS], fill=(0, 0, 0, 170))
    big.alpha_composite(sh.filter(ImageFilter.GaussianBlur(5 * SS)))
    # picture, circular
    pic = av.resize((2 * R * SS, 2 * R * SS), Image.LANCZOS)
    m = Image.new("L", pic.size, 0)
    ImageDraw.Draw(m).ellipse([0, 0, pic.width - 1, pic.height - 1], fill=255)
    pic.putalpha(Image.composite(pic.getchannel("A"), Image.new("L", pic.size, 0), m))
    big.alpha_composite(pic, dest=(c - R * SS, c - R * SS))
    # warm ring
    ring = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([c - R * SS, c - R * SS, c + R * SS, c + R * SS], outline=(243, 150, 40, 255), width=5 * SS)
    big.alpha_composite(ring)
    badge = big.resize((D + 40, D + 40), Image.LANCZOS)
    skin.alpha_composite(badge, dest=(CX - (D + 40) // 2, CY - (D + 40) // 2))



    sparkle_a, sparkle_b = (CX + 82, CY - 58), (CX - 84, CY + 54)


def sparkle(cx, cy, r, color):
    layer = Image.new("RGBA", (int(r * 2 + 6) * SS, int(r * 2 + 6) * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    k = layer.width // 2
    pts = []
    for i in range(8):
        ang = math.pi / 4 * i - math.pi / 2
        rad = r * SS if i % 2 == 0 else r * SS * 0.28
        pts.append((k + rad * math.cos(ang), k + rad * math.sin(ang)))
    d.polygon(pts, fill=color)
    layer = layer.resize((layer.width // SS, layer.height // SS), Image.LANCZOS)
    skin.alpha_composite(layer, dest=(int(cx - layer.width / 2), int(cy - layer.height / 2)))


sparkle(*sparkle_a, 13, (255, 199, 102, 255))
sparkle(*sparkle_b, 9, (243, 150, 40, 255))
skin.convert("RGB").save(skin_path)
print("wrote", skin_path, "(flipped)" if FLIP else "")
