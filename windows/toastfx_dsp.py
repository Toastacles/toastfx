"""ToastFX voice effects in Python (same filters as the Linux engine). Mono, 48 kHz, float32 blocks."""
import math
import numpy as np
from scipy.signal import lfilter

SR = 48000


def _bq(kind, hz, q, db=0.0):
    """RBJ biquad -> (b, a), a0 normalised."""
    w = 2 * math.pi * hz / SR
    cw, sw = math.cos(w), math.sin(w)
    al = sw / (2 * q)
    A = 10 ** (db / 40)
    if kind == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]; a = [1 + al, -2 * cw, 1 - al]
    elif kind == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]; a = [1 + al, -2 * cw, 1 - al]
    else:
        b = [1 + al * A, -2 * cw, 1 - al * A]; a = [1 + al / A, -2 * cw, 1 - al / A]
    return np.array(b) / a[0], np.array(a) / a[0]


class Chain:
    """Cascade of biquads that keeps its state between blocks."""
    def __init__(self, sections):
        self.sec = sections
        self.zi = [np.zeros(2) for _ in sections]

    def run(self, x):
        for i, (b, a) in enumerate(self.sec):
            x, self.zi[i] = lfilter(b, a, x, zi=self.zi[i])
        return x


class Compressor:
    def __init__(self, thresh_db, ratio, attack_ms, release_ms, makeup_db):
        self.t, self.r = thresh_db, ratio
        self.att = 1 - math.exp(-1 / (attack_ms * 0.001 * SR))
        self.rel = 1 - math.exp(-1 / (release_ms * 0.001 * SR))
        self.mk = 10 ** (makeup_db / 20)
        self.env = 0.0

    def run(self, y):
        lvl = 20 * np.log10(np.abs(y) + 1e-6)
        out = np.empty_like(y)
        env, att, rel, t, k = self.env, self.att, self.rel, self.t, 1 - 1 / self.r
        for i in range(len(y)):
            l = lvl[i]
            env += (att if l > env else rel) * (l - env)
            over = env - t
            g = -over * k if over > 0 else 0.0
            out[i] = y[i] * 10 ** (g / 20)
        self.env = env
        return out * self.mk


def _limit(y, lim=0.9):
    return lim * np.tanh(y / lim)


class Dry:
    def process(self, x): return x


class Helmet:
    def __init__(self, p=1.0):
        hp = 150 * (280 / 150) ** p; lp = 7000 * (3800 / 7000) ** p
        self.f = Chain([_bq("hp", hp, .7071), _bq("lp", lp, .7071), _bq("pk", 1100, 1.2, 3 * p), _bq("pk", 2600, 1.5, 5 * p)])
        self.c = Compressor(-24, 4, 5, 80, 4)
        self.g1, self.g2 = 0.22 * p, 0.12 * p
        self.buf = np.zeros(1024 + 4096, dtype=np.float64); self.pos = 1024  # history for the two echo taps

    def process(self, x):
        y = self.c.run(self.f.run(x.astype(np.float64)))
        n = len(y); h = 1024
        hist = np.concatenate([self.buf[-h:], y])
        d1 = hist[h - 432: h - 432 + n]; d2 = hist[h - 816: h - 816 + n]
        self.buf = hist
        y = (y * 0.9 + d1 * self.g1 + d2 * self.g2) * 1.5
        return _limit(y).astype(np.float32)


class Radio:
    def __init__(self, p=1.0):
        hp = 150 * (650 / 150) ** p; lp = 6000 * (2300 / 6000) ** p
        self.f = Chain([_bq("hp", hp, .7071), _bq("hp", hp, .7071), _bq("lp", lp, .7071), _bq("lp", lp, .7071), _bq("pk", 1400, .8, 7 * p)])
        self.c = Compressor(-20, 6, 3, 70, 4)
        self.grit = 0.2 * p

    def process(self, x):
        y = self.c.run(self.f.run(x.astype(np.float64)))
        q = np.round(y * 512) / 512
        y = (y * (1 - self.grit) + q * self.grit) * 3.6
        return _limit(y).astype(np.float32)


def make(mode, p=1.0):
    return {"dry": Dry, "helmet": Helmet, "radio": Radio}[mode]() if mode == "dry" else {"helmet": Helmet, "radio": Radio}[mode](p)
