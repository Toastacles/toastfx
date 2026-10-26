"""Draws the 'selected' voice icons (thick black outline, filled colours) like the helmet. Output: ui/assets/v_*_sel.png"""
from PIL import Image, ImageDraw
import math, sys
from pathlib import Path
OUT = str(Path(__file__).resolve().parent.parent / "ui" / "assets") + "/"
S, FINAL = 800, 200
K = (24, 18, 14, 255)          # outline black
W = 40                          # outline width at S

def new(): 
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); return im, ImageDraw.Draw(im)
def rr(d, box, r, fill, w=W): d.rounded_rectangle(box, r, fill=fill, outline=K, width=w)
def el(d, box, fill, w=W): d.ellipse(box, fill=fill, outline=K, width=w)
def shine(im, box, a=150):
    l = Image.new("RGBA", (S, S), (0, 0, 0, 0)); ImageDraw.Draw(l).ellipse(box, fill=(255, 255, 255, a)); im.alpha_composite(l)
def save(im, name):
    bb = im.getbbox(); im = im.crop(bb)
    side = max(im.size); sq = Image.new("RGBA", (side, side), (0, 0, 0, 0)); sq.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
    sq.resize((FINAL, FINAL), Image.LANCZOS).save(OUT + name)

# ---- microphone -------------------------------------------------------------
im, d = new()
rr(d, (330, 430, 470, 740), 60, (255, 190, 70, 255))                     # handle
rr(d, (300, 380, 500, 470), 30, (90, 80, 76, 255))                       # collar
el(d, (210, 60, 590, 440), (236, 238, 244, 255))                         # head
for i in range(1, 4):                                                    # grille
    y = 60 + i * 95
    d.line([(235, y), (565, y)], fill=K, width=14)
    d.line([(400 - i * 0, 70), (400, 430)], fill=K, width=0)
d.line([(400, 80), (400, 420)], fill=K, width=14)
el(d, (210, 60, 590, 440), None)
shine(im, (250, 90, 350, 200))
d.line([(400, 600), (400, 690)], fill=K, width=16)
im = im.rotate(24, resample=Image.BICUBIC, expand=True)
save(im, "v_mic_sel.png")

# ---- radio ------------------------------------------------------------------
im, d = new()
d.line([(560, 200), (700, 40)], fill=K, width=34)                         # antenna
el(d, (680, 20, 740, 80), (255, 120, 60, 255), 20)
rr(d, (60, 190, 740, 650), 70, (255, 244, 222, 255))                      # body
el(d, (120, 270, 400, 550), (60, 54, 56, 255), 30)                        # speaker
for r in (45, 90):
    d.ellipse((260 - r, 410 - r, 260 + r, 410 + r), outline=(190, 180, 170, 255), width=12)
rr(d, (440, 260, 690, 380), 28, (255, 205, 100, 255), 30)                 # dial window
d.line([(530, 275), (530, 365)], fill=(215, 60, 40, 255), width=14)       # needle
el(d, (450, 440, 540, 530), (255, 150, 60, 255), 28)                      # knobs
el(d, (580, 440, 670, 530), (255, 150, 60, 255), 28)
shine(im, (90, 215, 240, 285), 120)
save(im, "v_radio_sel.png")

# ---- robot ------------------------------------------------------------------
im, d = new()
d.line([(400, 150), (400, 60)], fill=K, width=34)                         # antenna
el(d, (350, 10, 450, 110), (255, 120, 60, 255), 26)
rr(d, (20, 360, 110, 540), 30, (150, 160, 175, 255), 30)                  # ears
rr(d, (690, 360, 780, 540), 30, (150, 160, 175, 255), 30)
rr(d, (90, 150, 710, 700), 110, (118, 190, 244, 255))                     # head
rr(d, (170, 280, 630, 520), 70, (30, 36, 52, 255), 30)                    # visor
el(d, (250, 355, 340, 445), (110, 235, 255, 255), 0)                      # eyes
el(d, (460, 355, 550, 445), (110, 235, 255, 255), 0)
d.line([(330, 600), (470, 600)], fill=K, width=26)                        # mouth
shine(im, (150, 185, 330, 250), 130)
save(im, "v_robot_sel.png")
print("ok")

# ---- helmet (redrawn crisp, same style) --------------------------------------
im, d = new()
rr(d, (20, 360, 110, 540), 30, (255, 170, 60, 255), 30)                   # ear pieces
rr(d, (690, 360, 780, 540), 30, (255, 170, 60, 255), 30)
d.rounded_rectangle((260, 20, 540, 110), 40, fill=(255, 200, 90, 255), outline=K, width=30)   # top ridge
el(d, (90, 70, 710, 740), (255, 205, 100, 255))                           # shell
rr(d, (170, 270, 630, 600), 130, (28, 28, 34, 255), 30)                   # visor
shine(im, (215, 300, 420, 380), 90)
d.arc((215, 300, 330, 410), 200, 280, fill=(255, 255, 255, 200), width=14)
shine(im, (230, 100, 430, 190), 140)
save(im, "v_helmet_sel.png")
