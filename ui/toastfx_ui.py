"""Drawing code for the ToastFX control window. Pillow only; no Tk.

Static artwork (header, labels, frames, mascot) comes from assets/skin.png: the user's design with the
live controls cleared out. Everything interactive is drawn here, per state, so a voice card or a sound
tile only glows while it is active/playing and otherwise looks like its neighbours.
Coordinates are design pixels (1536x1024); set_scale() picks the on-screen size.
"""
import base64
import io
import math
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ASSETS = Path(__file__).resolve().parent / "assets"
SS = 2                      # supersampling
DESIGN_W, DESIGN_H = 1536, 1024

CREAM = (241, 228, 207)
DIM = (205, 192, 172)
ORANGE_L = (255, 199, 102)
DARK = (43, 26, 8)
GREEN = (126, 224, 82)
WARN = (255, 168, 72)

# ---- layout (design pixels) -----------------------------------------------------
CARD_W, CARD_H, CARD_Y, CARD_X0, CARD_STEP = 272, 165, 252, 35, 287
TILE_W, TILE_H, TILE_X0, TILE_Y0, TILE_SX, TILE_SY = 265, 110, 47, 565, 283, 128
PAGE_SLOTS = 8              # sounds plus the "Add sound" tile share these
PILL = (882, 42, 1168, 137)
STOPBTN = (1182, 55, 1413, 130)
METER = (232, 465, 1003, 483)
HOTKEYS = (1216, 505, 1504, 734)
VOL_X0, VOL_X1, VOL_Y = 441, 633, 933
VOL_TEXT = (649, 933)
TOGGLE = (897, 906, 970, 950)
HINT = (1078, 905, 1216, 964)
PAGER = (1020, 524, 1160, 556)
STOPALL = (33, 893, 268, 975)
SOON_AT = (1440, 184)
TW_X0, TW_X1, TW_PCT_X = 1282, 1460, 1474
TW_Y = (271, 342, 412)          # centre line of the Radio / Helmet / Mix rows

# id, title, subtitle, icon, (gradient top, bottom) when idle, icon tint when idle (None = keep colours)
VOICES = [
    ("dry", "Dry Mic", "(clean voice)", "v_mic", ((66, 60, 56), (44, 40, 38)), (236, 214, 190)),
    ("radio", "Radio", "(classic filter)", "v_radio", ((60, 65, 86), (42, 46, 64)), (236, 212, 190)),
    ("helmet", "Helmet Comms", "(crisp & bassy)", "v_helmet_line", ((74, 60, 46), (48, 40, 32)), (236, 214, 190)),
    ("robot", "Robot", "(beep boop)", "v_robot", ((54, 86, 120), (38, 62, 90)), (126, 190, 235)),
]
SOUND_ICONS = ["burst", "note", "chick", "flame", "cat", "pizza", "beer"]


def card_pos(i):
    return CARD_X0 + i * CARD_STEP, CARD_Y


def tile_pos(slot):
    return TILE_X0 + (slot % 4) * TILE_SX, TILE_Y0 + (slot // 4) * TILE_SY


# ---- fonts & icons ----------------------------------------------------------------
_FONT_PATH, _FONTS, _ICONS, _SCALE = {}, {}, {}, [1.0]


def set_scale(s):
    _SCALE[0] = float(s)


def _font_path(bold):
    if bold in _FONT_PATH:
        return _FONT_PATH[bold]
    forced = os.environ.get("TOASTFX_FONT_BOLD" if bold else "TOASTFX_FONT_REGULAR")
    found = forced if forced and Path(forced).exists() else None
    for fam in ("Nunito", "Quicksand", "Fira Sans", "Noto Sans", "Ubuntu", "Cantarell", "DejaVu Sans"):
        if found:
            break
        try:
            out = subprocess.run(["fc-match", "-f", "%{family}|%{file}", f"{fam}:{'bold' if bold else 'regular'}"],
                                 capture_output=True, text=True, timeout=3).stdout
            fam_out, _, path = out.partition("|")
            if fam_out.split(",")[0].strip().lower() == fam.lower() and Path(path).exists() \
                    and Path(path).suffix.lower() in (".ttf", ".otf"):
                found = path
        except Exception:
            pass
    _FONT_PATH[bold] = found
    return found


def font(size, bold=True):
    key = (int(size), bool(bold))
    if key not in _FONTS:
        p = _font_path(bold)
        try:
            _FONTS[key] = ImageFont.truetype(p, max(6, int(size))) if p else ImageFont.load_default(max(6, int(size)))
        except Exception:
            _FONTS[key] = ImageFont.load_default(max(6, int(size)))
    return _FONTS[key]


def icon(name):
    if name not in _ICONS:
        _ICONS[name] = Image.open(ASSETS / (name + ".png")).convert("RGBA")
    return _ICONS[name]


def tinted(img, color):
    out = Image.new("RGBA", img.size, tuple(color) + (255,))
    out.putalpha(img.getchannel("A"))
    return out


def grad(w, h, c1, c2, horizontal=False):
    g = Image.linear_gradient("L")
    if horizontal:
        g = g.rotate(90)
    g = g.resize((max(1, w), max(1, h)), Image.BILINEAR)
    return ImageOps.colorize(g, tuple(c1[:3]), tuple(c2[:3])).convert("RGBA")


def mix(c1, c2, t):
    return tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3))


def png_b64(img):
    """PNG bytes (base64) for tk.PhotoImage(data=...), so no ImageTk / python3-pil.imagetk is needed."""
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue())


class Cv:
    def __init__(self, w, h):
        self.k, self.w, self.h = _SCALE[0] * SS, w, h
        self.img = Image.new("RGBA", (self.s(w), self.s(h)), (0, 0, 0, 0))

    def s(self, v):
        return int(round(v * self.k))

    def box(self, b):
        return [self.s(b[0]), self.s(b[1]), self.s(b[2]) - 1, self.s(b[3]) - 1]

    def layer(self):
        im = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        return im, ImageDraw.Draw(im)

    def fill_rr(self, b, r, c1, c2=None, horizontal=False):
        x0, y0, x1, y1 = self.box(b)
        w, h = x1 - x0 + 1, y1 - y0 + 1
        g = grad(w, h, c1, c2 or c1, horizontal)
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], self.s(r), fill=255)
        g.putalpha(m)
        self.img.alpha_composite(g, dest=(x0, y0))

    def stroke_rr(self, b, r, color, width):
        im, d = self.layer()
        d.rounded_rectangle(self.box(b), self.s(r), outline=tuple(color), width=max(1, self.s(width)))
        self.img.alpha_composite(im)

    def glow_rr(self, b, r, color, blur, grow=0):
        im, d = self.layer()
        bb = (b[0] - grow, b[1] - grow, b[2] + grow, b[3] + grow)
        d.rounded_rectangle(self.box(bb), self.s(r + grow), fill=tuple(color))
        self.img.alpha_composite(im.filter(ImageFilter.GaussianBlur(self.s(blur))))

    def tw(self, s, size, bold=True):
        return font(self.s(size), bold).getlength(s) / self.k

    def text(self, xy, s, size, color, bold=True, anchor="mm", maxw=None, minsize=11):
        if maxw:
            while size > minsize and self.tw(s, size, bold) > maxw:
                size -= 1
        im, d = self.layer()
        d.text((self.s(xy[0]), self.s(xy[1])), s, font=font(self.s(size), bold), fill=tuple(color), anchor=anchor)
        self.img.alpha_composite(im)

    def paste(self, im, center, height, color=None):
        ic = tinted(im, color) if color else im
        hh = self.s(height)
        ww = max(1, int(ic.width * hh / ic.height))
        ic = ic.resize((ww, hh), Image.LANCZOS)
        self.img.alpha_composite(ic, dest=(self.s(center[0]) - ww // 2, self.s(center[1]) - hh // 2))

    def poly(self, pts, color):
        im, d = self.layer()
        d.polygon([(self.s(x), self.s(y)) for x, y in pts], fill=tuple(color))
        self.img.alpha_composite(im)

    def dashed_rr(self, b, r, color, width, dash=12, gap=9):
        x0, y0, x1, y1 = b
        pts = []
        for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
            for i in range(9):
                a = math.radians(a0 + 90 * i / 8)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        pts.append(pts[0])
        im, d = self.layer()
        on, left = True, dash
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            seg = math.hypot(bx - ax, by - ay)
            pos = 0.0
            while pos < seg:
                step = min(left, seg - pos)
                if on:
                    p0 = (ax + (bx - ax) * pos / seg, ay + (by - ay) * pos / seg)
                    p1 = (ax + (bx - ax) * (pos + step) / seg, ay + (by - ay) * (pos + step) / seg)
                    d.line([(self.s(p0[0]), self.s(p0[1])), (self.s(p1[0]), self.s(p1[1]))],
                           fill=tuple(color), width=max(1, self.s(width)))
                pos += step
                left -= step
                if left <= 1e-6:
                    on = not on
                    left = dash if on else gap
        self.img.alpha_composite(im)

    def done(self):
        sc = _SCALE[0]
        return self.img.resize((max(1, round(self.w * sc)), max(1, round(self.h * sc))), Image.LANCZOS)


def badge(cv, right, top, text, kind, lit=False):
    """kind: 'set' | 'empty' | 'listen'. Returns the badge rect in the canvas' local design px."""
    size = 15 if len(text) <= 7 else 13
    bw = cv.tw(text, size) + 22
    b = (right - bw, top, right, top + 26)
    if kind == "listen":
        cv.fill_rr(b, 9, (60, 165, 245), (38, 140, 235))
        col = (255, 255, 255)
    elif kind == "empty":
        cv.fill_rr(b, 9, (46, 48, 58), (38, 40, 49))
        cv.stroke_rr(b, 9, (125, 130, 146, 255), 1.5)
        col = (214, 217, 228)
    else:
        fill = (95, 48, 12) if lit else (14, 13, 15)
        cv.fill_rr(b, 9, fill, fill)
        cv.stroke_rr(b, 9, (255, 255, 255, 46), 1.2)
        col = (255, 240, 214) if lit else (232, 220, 200)
    cv.text(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2 + 1), text, size, col)
    return b


# ---- components ---------------------------------------------------------------------
def voice_card(index, active=False, hover=False, key_text="+ KEY", key_kind="empty"):
    """Returns (image, (x, y), badge_rect_in_design_px). Lit only when `active`."""
    _id, name, sub, ic, (c1, c2), tint = VOICES[index]
    pad = 26
    cv = Cv(CARD_W + 2 * pad, CARD_H + 2 * pad)
    b = (pad, pad, pad + CARD_W, pad + CARD_H)
    if active:
        cv.glow_rr(b, 24, (255, 150, 30, 230), 16, grow=3)
        cv.fill_rr(b, 24, (255, 205, 108), (243, 156, 44))
        cv.stroke_rr(b, 24, (255, 226, 160, 255), 3.5)
        fg, fg2, icol = DARK, (88, 52, 16), DARK
        ic = {"dry": "v_mic_sel", "radio": "v_radio_sel", "helmet": "v_helmet_sel", "robot": "v_robot_sel"}[_id]
        icol = None                                          # coloured, black-outlined art only on the lit card
    else:
        cv.glow_rr((b[0], b[1] + 7, b[2], b[3] + 7), 24, (0, 0, 0, 150), 8)
        if hover:
            c1, c2 = mix(c1, (255, 255, 255), .08), mix(c2, (255, 255, 255), .08)
        cv.fill_rr(b, 24, c1, c2)
        cv.stroke_rr(b, 24, (255, 255, 255, 40), 2)
        fg, fg2, icol = CREAM, DIM, tint
    big = 64 if active else 54      # clear of the key badge in the corner
    cv.paste(icon(ic), (pad + CARD_W / 2, pad + (62 if active else 72)), big, icol)
    cv.text((pad + CARD_W / 2, pad + 120), name, 32, fg, maxw=CARD_W - 34)
    cv.text((pad + CARD_W / 2, pad + 146), sub, 20, fg2, bold=False, maxw=CARD_W - 40)
    bd = badge(cv, pad + CARD_W - 12, pad + 12, key_text, key_kind, lit=active)
    if active:                                              # little sparks above the lit card
        im, d = cv.layer()
        spark = [(CARD_W - 62, 4, CARD_W - 58, 17), (CARD_W - 46, 8, CARD_W - 36, 20)]
        if index > 0:                                       # the first card sits under the section label
            spark += [(46, 8, 36, 20), (62, 4, 58, 17)]
        for dx, dy, ex, ey in spark:
            d.line([(cv.s(pad + dx), cv.s(dy)), (cv.s(pad + ex), cv.s(ey))], fill=(255, 168, 48, 255), width=cv.s(3))
        cv.img.alpha_composite(im)
    x, y = card_pos(index)
    return cv.done(), (x - pad, y - pad), (x - pad + bd[0], y - pad + bd[1], x - pad + bd[2], y - pad + bd[3])


def sound_tile(slot, name, icon_name, key_text, key_kind, playing=False, hover=False):
    pad = 20
    cv = Cv(TILE_W + 2 * pad, TILE_H + 2 * pad)
    b = (pad, pad, pad + TILE_W, pad + TILE_H)
    if playing:
        cv.glow_rr(b, 20, (255, 140, 30, 220), 12, grow=2)
        cv.fill_rr(b, 20, (46, 38, 32), (34, 29, 27))
        cv.stroke_rr(b, 20, (255, 178, 64, 255), 4)
    else:
        cv.glow_rr((b[0], b[1] + 6, b[2], b[3] + 6), 20, (0, 0, 0, 140), 7)
        top, bot = ((50, 54, 68), (38, 41, 53)) if hover else ((43, 46, 58), (34, 37, 47))
        cv.fill_rr(b, 20, top, bot)
        cv.stroke_rr(b, 20, (255, 255, 255, 34), 2)
    cv.paste(icon(icon_name), (pad + 54, pad + TILE_H / 2), 58)
    size, label = 27, name
    while cv.tw(label, size) > 148 and size > 17:
        size -= 1
    while cv.tw(label, size) > 148 and len(label) > 3:
        label = label[:-2]
    if label != name:
        label += "…"
    ny = pad + TILE_H / 2 + (0 if playing else 6)
    cv.text((pad + 104, ny), label, size, (233, 233, 242), anchor="lm")
    if playing:
        cv.text((pad + 104, ny + 28), "PLAYING", 16, (255, 122, 48), anchor="lm")
    bd = badge(cv, pad + TILE_W - 12, pad + 12, key_text, key_kind)
    x, y = tile_pos(slot)
    return cv.done(), (x - pad, y - pad), (x - pad + bd[0], y - pad + bd[1], x - pad + bd[2], y - pad + bd[3])


def add_tile(slot, hover=False):
    pad = 12
    cv = Cv(TILE_W + 2 * pad, TILE_H + 2 * pad)
    b = (pad, pad, pad + TILE_W, pad + TILE_H)
    if hover:
        cv.fill_rr(b, 20, (38, 36, 40), (32, 30, 34))
    cv.dashed_rr(b, 20, (150, 130, 104, 255), 2.2)
    cv.paste(icon("bread"), (pad + TILE_W / 2, pad + 36), 36)
    cv.text((pad + TILE_W / 2, pad + 78), "+  Add sound", 24, (225, 214, 198), bold=False)
    x, y = tile_pos(slot)
    return cv.done(), (x - pad, y - pad)


def empty_slot_clear(slot):
    """Not needed (the skin already has these cleared); kept for symmetry in callers."""
    return None


def pager(page, pages, hover=None):
    cv = Cv(PAGER[2] - PAGER[0], PAGER[3] - PAGER[1])
    w, h = cv.w, cv.h
    for x0, left in ((0, True), (w - 36, False)):
        lit = hover == ("prev" if left else "next")
        cv.fill_rr((x0, 0, x0 + 36, h), 10, (56, 58, 70) if lit else (46, 48, 58), (46, 48, 58) if lit else (38, 40, 49))
        cx, cy = x0 + 18, h / 2
        d = -1 if left else 1
        cv.poly([(cx - 6 * d, cy - 8), (cx - 6 * d, cy + 8), (cx + 6 * d, cy)], CREAM)
    cv.text((w / 2, h / 2), f"{page + 1} / {pages}", 17, DIM)
    return cv.done(), (PAGER[0], PAGER[1])


def engine_pill(running, detail):
    w, h = PILL[2] - PILL[0], PILL[3] - PILL[1]
    pad = 14
    cv = Cv(w + 2 * pad, h + 2 * pad)
    b = (pad, pad, pad + w, pad + h)
    edge, led, txt = ((138, 190, 52), (112, 236, 60), GREEN) if running else ((150, 96, 70), (200, 90, 70), (232, 140, 110))
    cv.glow_rr(b, 44, edge + (140,), 9, grow=1)
    cv.fill_rr(b, 44, (34, 48, 28) if running else (46, 32, 28), (24, 34, 22) if running else (34, 24, 22))
    cv.stroke_rr(b, 44, edge + (255,), 4)
    cv.fill_rr((pad + 24, pad + 18, pad + w - 24, pad + 54), 16, (20, 30, 17) if running else (30, 20, 18))
    cv.glow_rr((pad + 33, pad + 28, pad + 51, pad + 46), 9, led + (200,), 5)
    cv.fill_rr((pad + 33, pad + 28, pad + 51, pad + 46), 9, led)
    cv.text((pad + 64, pad + 37), "ENGINE RUNNING" if running else "ENGINE STOPPED", 24, txt, anchor="lm", maxw=w - 94)
    cv.text((pad + w / 2, pad + 72), detail, 17, CREAM, bold=False, maxw=w - 40)
    return cv.done(), (PILL[0] - pad, PILL[1] - pad)


def engine_button(running, hover=False):
    w, h = STOPBTN[2] - STOPBTN[0], STOPBTN[3] - STOPBTN[1]
    pad = 12
    cv = Cv(w + 2 * pad, h + 2 * pad)
    b = (pad, pad, pad + w, pad + h)
    top, bot = ((118, 68, 40), (86, 48, 28)) if hover else ((104, 58, 34), (72, 40, 24))
    cv.glow_rr((b[0], b[1] + 5, b[2], b[3] + 5), 26, (0, 0, 0, 150), 6)
    cv.fill_rr(b, 26, top, bot)
    cv.stroke_rr(b, 26, (196, 104, 52, 255), 3.5)
    if running:
        cv.fill_rr((pad + 24, pad + 24, pad + 52, pad + 52), 6, (255, 84, 52), (236, 60, 36))
    else:
        cv.poly([(pad + 26, pad + 22), (pad + 26, pad + 54), (pad + 54, pad + 38)], GREEN)
    cv.text((pad + 70, pad + h / 2), "Stop Engine" if running else "Start Engine", 28, CREAM, anchor="lm", maxw=w - 96)
    return cv.done(), (STOPBTN[0] - pad, STOPBTN[1] - pad)


def meter(level):
    w, h = METER[2] - METER[0], METER[3] - METER[1]
    cv = Cv(w, h)
    cv.fill_rr((0, 0, w, h), 9, (36, 36, 42), (46, 46, 52))
    fw = int(w * max(0.0, min(1.0, level)))
    if fw > 4:
        cv.fill_rr((0, 0, fw, h), 9, (255, 188, 80), (240, 128, 30), horizontal=True)
        cv.fill_rr((6, 2, max(8, fw - 6), 6), 3, (255, 226, 160), (255, 226, 160))
    return cv.done(), (METER[0], METER[1])


def hotkey_list(rows):
    """rows: up to six (key_text, label)."""
    w, h = HOTKEYS[2] - HOTKEYS[0], HOTKEYS[3] - HOTKEYS[1]
    cv = Cv(w, h)
    for (key, label), y in zip(rows, [27, 61, 93, 127, 165, 201]):
        kw = max(54, cv.tw(key, 16) + 26)
        cv.fill_rr((16, y - 15, 16 + kw, y + 15), 10, (44, 40, 42), (36, 33, 35))
        cv.stroke_rr((16, y - 15, 16 + kw, y + 15), 10, (255, 255, 255, 30), 1.2)
        cv.text((16 + kw / 2, y), key, 16, CREAM, maxw=kw - 10)
        lx = 16 + max(kw, 112) + 14
        cv.text((lx, y), label, 18, (228, 216, 198), bold=False, anchor="lm", maxw=w - lx - 8)
    return cv.done(), (HOTKEYS[0], HOTKEYS[1])


def volume(value):
    pad = 18
    w = VOL_X1 - VOL_X0
    cv = Cv(w + 2 * pad, 2 * pad + 16)
    cy = pad + 8
    cv.fill_rr((pad, cy - 6, pad + w, cy + 6), 6, (50, 48, 52), (60, 58, 62))
    fx = pad + w * max(0.0, min(1.0, value))
    cv.fill_rr((pad, cy - 6, fx, cy + 6), 6, (255, 190, 84), (243, 140, 36), horizontal=True)
    cv.glow_rr((fx - 15, cy - 15, fx + 15, cy + 15), 15, (0, 0, 0, 150), 3)
    cv.fill_rr((fx - 15, cy - 15, fx + 15, cy + 15), 15, (255, 250, 240), (232, 226, 214))
    cv.stroke_rr((fx - 15, cy - 15, fx + 15, cy + 15), 15, (243, 150, 40, 255), 3)
    return cv.done(), (VOL_X0 - pad, VOL_Y - cy)


def percent(value):
    cv = Cv(60, 30)
    cv.text((0, 15), f"{int(round(value * 100))}%", 19, DIM, bold=False, anchor="lm")
    return cv.done(), (VOL_TEXT[0], VOL_TEXT[1] - 15)


def toggle(on):
    w, h = TOGGLE[2] - TOGGLE[0], TOGGLE[3] - TOGGLE[1]
    pad = 8
    cv = Cv(w + 2 * pad, h + 2 * pad)
    b = (pad, pad, pad + w, pad + h)
    if on:
        cv.glow_rr(b, h / 2, (255, 150, 30, 150), 6)
        cv.fill_rr(b, h / 2, (255, 178, 70), (240, 128, 30))
        kx = pad + w - h / 2
    else:
        cv.fill_rr(b, h / 2, (84, 82, 88), (66, 64, 70))
        kx = pad + h / 2
    cv.fill_rr((kx - 17, pad + h / 2 - 17, kx + 17, pad + h / 2 + 17), 17, (255, 252, 246), (236, 230, 220))
    return cv.done(), (TOGGLE[0] - pad, TOGGLE[1] - pad)


def hint(lines, color=DIM):
    w, h = HINT[2] - HINT[0], HINT[3] - HINT[1]
    cv = Cv(w, h)
    n = len(lines)
    for i, ln in enumerate(lines):
        cv.text((0, h / 2 + (i - (n - 1) / 2) * 25), ln, 18, color, bold=False, anchor="lm", maxw=w)
    return cv.done(), (HINT[0], HINT[1])


def tweak_row(i, value, active=False):
    """One Quick Tweaks row: slider track, thumb and percentage. value 0..1."""
    pad = 18
    w = TW_X1 - TW_X0
    total = w + 2 * pad + 80
    cv = Cv(total, 2 * pad + 16)
    cy = pad + 8
    cv.fill_rr((pad, cy - 6, pad + w, cy + 6), 6, (50, 48, 52), (60, 58, 62))
    fx = pad + w * max(0.0, min(1.0, value))
    cv.fill_rr((pad, cy - 6, fx, cy + 6), 6, (255, 190, 84), (243, 140, 36), horizontal=True)
    r = 12
    cv.glow_rr((fx - r, cy - r, fx + r, cy + r), r, (0, 0, 0, 150), 3)
    cv.fill_rr((fx - r, cy - r, fx + r, cy + r), r, (255, 220, 120) if active else (255, 205, 100), (246, 160, 44))
    cv.stroke_rr((fx - r, cy - r, fx + r, cy + r), r, (255, 232, 170, 255), 2.5)
    cv.text((pad + w + (TW_PCT_X - TW_X1), cy), f"{int(round(value * 100))}%", 21, CREAM, bold=False, anchor="lm")
    return cv.done(), (TW_X0 - pad, TW_Y[i] - cy)


def soon_chip():
    cv = Cv(66, 28)
    cv.fill_rr((0, 0, 66, 28), 10, (60, 38, 20), (50, 32, 18))
    cv.stroke_rr((0, 0, 66, 28), 10, (245, 154, 42, 200), 1.5)
    cv.text((33, 15), "SOON", 14, ORANGE_L, maxw=58)
    return cv.done(), SOON_AT


def load_skin():
    im = Image.open(ASSETS / "skin.png").convert("RGBA")
    sc = _SCALE[0]
    if abs(sc - 1) > 1e-6:
        im = im.resize((round(DESIGN_W * sc), round(DESIGN_H * sc)), Image.LANCZOS)
    return im
