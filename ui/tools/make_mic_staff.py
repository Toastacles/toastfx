#!/usr/bin/env python3
"""Turn the wizard cutout's wooden staff into a microphone staff (draws a cartoon mic head over the stick).

Usage: python3 tools/make_mic_staff.py wizard_cutout.png out.png
The carved wooden top is erased and a mesh microphone with a gold band and a short neck is drawn on the stick,
outlined in the same dark line as the rest of the picture.
"""
import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SS = 4
src, dst = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGBA")
a = np.array(im)
ERASE_BELOW, ERASE_X = 392, 205            # erase the carved top: rows above this, left of the hat
a[:ERASE_BELOW, :ERASE_X, 3] = 0
im = Image.fromarray(a)

CX, CY, R = 106, 258, 64                   # mic head centre / radius (picture pixels)
W, H = im.size
L = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
d = ImageDraw.Draw(L)
s = lambda v: int(round(v * SS))
INK = (26, 16, 14, 255)

# neck: a short dark cone from the stick up to the head
neck = [(CX - 15, 396), (CX + 15, 396), (CX + 24, CY + R - 8), (CX - 24, CY + R - 8)]
d.polygon([(s(x), s(y)) for x, y in neck], fill=INK)
inner = [(CX - 11, 392), (CX + 11, 392), (CX + 19, CY + R - 6), (CX - 19, CY + R - 6)]
d.polygon([(s(x), s(y)) for x, y in inner], fill=(58, 60, 70, 255))

# head: outlined sphere with a light-to-dark gradient
d.ellipse([s(CX - R - 5), s(CY - R - 5), s(CX + R + 5), s(CY + R + 5)], fill=INK)
sph = Image.new("RGBA", L.size, (0, 0, 0, 0))
px = sph.load()
for y in range(s(CY - R), s(CY + R) + 1):
    for x in range(s(CX - R), s(CX + R) + 1):
        dx, dy = (x / SS - CX) / R, (y / SS - CY) / R
        r2 = dx * dx + dy * dy
        if r2 <= 1.0:
            lit = max(0.0, 1 - math.hypot(dx + 0.38, dy + 0.42) / 1.35)       # light from the upper left
            c = [int(95 + 140 * lit * k) for k in (1.0, 1.02, 1.08)]
            px[x, y] = (min(255, c[0]), min(255, c[1]), min(255, c[2]), 255)
L.alpha_composite(sph)
d = ImageDraw.Draw(L)

# mesh: diagonal grid clipped to the sphere
mesh = Image.new("RGBA", L.size, (0, 0, 0, 0))
md = ImageDraw.Draw(mesh)
step = 15
for k in range(-12, 13):
    off = k * step
    md.line([(s(CX - R + off), s(CY - R)), (s(CX + R + off), s(CY + R))], fill=(40, 42, 54, 170), width=s(2.2))
    md.line([(s(CX + R + off), s(CY - R)), (s(CX - R + off), s(CY + R))], fill=(40, 42, 54, 170), width=s(2.2))
clip = Image.new("L", L.size, 0)
ImageDraw.Draw(clip).ellipse([s(CX - R), s(CY - R), s(CX + R), s(CY + R)], fill=255)
mesh.putalpha(Image.composite(mesh.getchannel("A"), Image.new("L", L.size, 0), clip))
L.alpha_composite(mesh)
d = ImageDraw.Draw(L)

# gold band around the middle of the head
by0, by1 = CY + 18, CY + 38
d.rounded_rectangle([s(CX - R - 8), s(by0 - 3), s(CX + R + 8), s(by1 + 3)], radius=s(8), fill=INK)
d.rounded_rectangle([s(CX - R - 4), s(by0), s(CX + R + 4), s(by1)], radius=s(6), fill=(243, 176, 44, 255))
d.rounded_rectangle([s(CX - R - 4), s(by0 + 3), s(CX + R + 4), s(by0 + 8)], radius=s(3), fill=(255, 222, 130, 255))

# shine
d.ellipse([s(CX - 40), s(CY - 48), s(CX - 14), s(CY - 28)], fill=(255, 255, 255, 190))

# a little steam-free glint, like the original highlight on the wood
L = L.resize((W, H), Image.LANCZOS)
im.alpha_composite(L)
im.save(dst)
print("wrote", dst)
