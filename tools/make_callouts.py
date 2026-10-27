#!/usr/bin/env python3
"""Generates the four shipped callout sounds from scratch (original, no samples, public domain / MIT with the project).
Output: ui/assets/callouts/*.wav  (48 kHz, stereo, 16-bit, peak about -9 dBFS so mixing with a voice has headroom)
Usage: python3 tools/make_callouts.py [output_dir]
"""
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000
PEAK = 0.35
rng = np.random.default_rng(7)                      # fixed seed: same files every run


def env(n, attack=0.004, release=0.03):
    e = np.ones(n)
    a, r = max(1, int(attack * SR)), max(1, int(release * SR))
    e[:a] = np.linspace(0, 1, a)
    e[-r:] *= np.linspace(1, 0, r)
    return e


def tone(f0, secs, f1=None, harm=(1.0, 0.0, 0.18), attack=0.004, release=0.03):
    """Sine (+ odd harmonics for an electronic edge), optionally gliding from f0 to f1."""
    n = int(secs * SR)
    f = np.linspace(f0, f1 if f1 else f0, n)
    ph = 2 * np.pi * np.cumsum(f) / SR
    y = sum(h * np.sin((k + 1) * ph) for k, h in enumerate(harm))
    return y * env(n, attack, release)


def silence(secs):
    return np.zeros(int(secs * SR))


def band(x, lo, hi):
    return sosfilt(butter(4, [lo, hi], btype="band", fs=SR, output="sos"), x)


def finish(x):
    x = x / (np.abs(x).max() + 1e-9) * PEAK
    x[:48] *= np.linspace(0, 1, 48)
    x[-96:] *= np.linspace(1, 0, 96)
    return x


def comms_check():
    y = np.concatenate([tone(1200, 0.09), silence(0.06), tone(1800, 0.15, release=0.06)])
    return finish(band(y, 500, 4500))


def acknowledgement():
    y = np.concatenate([tone(900, 0.09, 1900, harm=(1, 0.1, 0.1)), silence(0.03),
                        tone(1300, 0.12, 2400, harm=(1, 0.1, 0.1), release=0.05)])
    return finish(band(y, 500, 5000))


def incoming():
    pulses = []
    for _ in range(2):
        pulses += [tone(988, 0.11, harm=(1, 0, 0.3, 0, 0.1)), silence(0.015),
                   tone(1319, 0.13, harm=(1, 0, 0.3, 0, 0.1)), silence(0.09)]
    y = np.concatenate(pulses)
    trem = 1 - 0.18 * (0.5 + 0.5 * np.sin(2 * np.pi * 14 * np.arange(len(y)) / SR))
    return finish(band(y * trem, 500, 4000))


def disconnect():
    n = int(0.22 * SR)
    noise = band(rng.standard_normal(n), 1500, 4200) * np.exp(-np.linspace(0, 1, n) * 9)
    fall = np.zeros(n)
    m = int(0.09 * SR)
    fall[:m] = tone(1400, 0.09, 600, harm=(1, 0, 0), release=0.04)[:m] * 0.5
    thump = np.zeros(n)
    k = int(0.03 * SR)
    thump[:k] = np.sin(2 * np.pi * 120 * np.arange(k) / SR) * np.linspace(1, 0, k) * 0.6
    return finish(noise + fall + thump)


def write(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "ui" / "assets" / "callouts"
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in (("comms_check", comms_check), ("ack", acknowledgement), ("incoming", incoming), ("disconnect", disconnect)):
        x = fn()
        write(out / f"{name}.wav", x)
        print(f"{name}.wav  {len(x) / SR * 1000:.0f} ms  peak {20 * np.log10(np.abs(x).max()):.1f} dBFS")
