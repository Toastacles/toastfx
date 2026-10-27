#!/usr/bin/env python3
"""Generates the four shipped callout sounds from scratch (original, no samples, public domain / MIT with the project).
Output: ui/assets/callouts/*.wav  (48 kHz, stereo, 16-bit, peak about -9 dBFS so mixing with a voice has headroom)
Usage: python3 tools/make_callouts.py [output_dir]   |   --audition  plays the four Incoming options
"""
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000
PEAK = 0.35


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


def _noise(n, lo, hi, seed):
    return band(np.random.default_rng(seed).standard_normal(n), lo, hi)


def _crackle(secs, seed, fade_in=True):
    n = int(secs * SR)
    amp = (np.linspace(0.2, 1, n) ** 2) if fade_in else np.exp(-np.linspace(0, 1, n) * 2.5)
    return _noise(n, 1200, 3800, seed) * amp * env(n, 0.01, 0.01)


def _muffled(freqs, on, off, cutoff, attack=0.008):
    """Clean electronic beeps (the original comms-check voice), softened by a low-pass so they sound behind a helmet."""
    p = []
    for f in freqs:
        p += [tone(f, on, harm=(1, 0, 0.18), attack=attack, release=0.04), silence(off)]
    y = np.concatenate(p[:-1])
    y = sosfilt(butter(4, cutoff, btype="low", fs=SR, output="sos"), y)
    return finish(band(y, 300, cutoff * 1.2))


def comms_a():
    """Four even beeps, muffled (low-pass 1500 Hz)."""
    return _muffled([1200] * 4, 0.07, 0.06, 1500)


def comms_b():
    """Three beeps, more muffled (low-pass 1100 Hz), a little longer."""
    return _muffled([1200] * 3, 0.10, 0.07, 1100)


def comms_c():
    """Four beeps, the last one longer, muffled (low-pass 1300 Hz)."""
    return finish(np.concatenate([_muffled([1200] * 3, 0.07, 0.06, 1300), silence(0.06),
                                  _muffled([1200], 0.16, 0.0, 1300)]))


COMMS_VARIANTS = {"a": comms_a, "b": comms_b, "c": comms_c}
comms_check = comms_c


def _sweeps(pairs, cutoff, lead=False):
    """Two quick rising sweeps (the Acknowledge shape), low-passed so they sound muffled like the other cues."""
    p = [_crackle(0.07, 41), silence(0.02)] if lead else []
    for i, (f0, f1, secs) in enumerate(pairs):
        p += [tone(f0, secs, f1, harm=(1, 0, 0.18), attack=0.008, release=0.04), silence(0.04)]
    y = np.concatenate(p[:-1])
    y = sosfilt(butter(4, cutoff, btype="low", fs=SR, output="sos"), y)
    return finish(band(y, 300, cutoff * 1.2))


def ack_a():
    """The original two rising sweeps, muffled (low-pass 1500 Hz)."""
    return _sweeps([(900, 1500, 0.09), (1100, 1700, 0.12)], 1500)


def ack_b():
    """Same, with the short static crackle in front like Incoming."""
    return _sweeps([(900, 1500, 0.09), (1100, 1700, 0.12)], 1500, lead=True)


def ack_c():
    """Lower and duller: sweeps start lower, low-pass 1200 Hz."""
    return _sweeps([(700, 1200, 0.10), (850, 1400, 0.13)], 1200)


ACK_VARIANTS = {"a": ack_a, "b": ack_b, "c": ack_c}
acknowledgement = ack_c


def incoming_a():
    """Squelch opening: a short burst of radio static, then two flat low "breaks" (no melody)."""
    n = int(0.16 * SR)
    st = _noise(n, 900, 3600, 11) * np.exp(-np.linspace(0, 1, n) * 3.2) * env(n, 0.002, 0.05)
    y = np.concatenate([st, silence(0.03), tone(760, 0.07, harm=(1, 0, 0.25)), silence(0.07),
                        tone(760, 0.07, harm=(1, 0, 0.25))])
    return finish(band(y, 500, 4200))


def incoming_b():
    """Data burst: six very short chirps at scattered pitches, like a digital radio handshake."""
    rng = np.random.default_rng(5)
    parts = []
    for f in (2100, 1500, 2600, 1750, 2300, 1300):
        parts += [tone(f, 0.028, f * 1.12, harm=(1, 0, 0.4), attack=0.002, release=0.01), silence(0.012)]
    return finish(band(np.concatenate(parts), 800, 4500))


def incoming_c():
    """Alert pulse: three flat 700 Hz pulses with a slight buzz, like a field-radio call light."""
    p = []
    for _ in range(3):
        t = tone(700, 0.09, harm=(1, 0.3, 0.35, 0.2), attack=0.003, release=0.02)
        t *= 1 - 0.35 * (0.5 + 0.5 * np.sin(2 * np.pi * 90 * np.arange(len(t)) / SR))
        p += [t, silence(0.07)]
    return finish(band(np.concatenate(p[:-1]), 400, 3500))


def incoming_d():
    """Key-up: static crackle that fades in, then one clean mid beep."""
    n = int(0.14 * SR)
    st = _noise(n, 1200, 3800, 21) * np.linspace(0.2, 1, n) ** 2 * env(n, 0.01, 0.01)
    return finish(band(np.concatenate([st, silence(0.02), tone(1000, 0.16, harm=(1, 0, 0.2), release=0.05)]), 500, 4200))


VARIANTS = {"a": incoming_a, "b": incoming_b, "c": incoming_c, "d": incoming_d}
incoming = incoming_d                                   # the shipped one


def _drop(parts, cutoff, tail_secs, tail_seed, tail_gain=0.7):
    """Falling muffled tones that end in a static tail (the signal dropping out)."""
    y = np.concatenate(parts)
    y = sosfilt(butter(4, cutoff, btype="low", fs=SR, output="sos"), y)
    k = int(0.035 * SR)                                  # soft start: ease in over 35 ms
    y[:k] *= np.sin(np.linspace(0, np.pi / 2, k)) ** 2
    tail = _crackle(tail_secs, tail_seed, fade_in=False) * tail_gain * np.abs(y).max()
    return finish(band(np.concatenate([y, tail]), 300, cutoff * 1.2))


def disc_a():
    """Two falling sweeps (the reverse of Acknowledge), then a fading static tail."""
    return _drop([tone(1000, 0.10, 550, harm=(1, 0, 0.18), attack=0.03, release=0.04), silence(0.04),
                  tone(800, 0.12, 400, harm=(1, 0, 0.18), release=0.05)], 1200, 0.12, 51)


def disc_b():
    """One long low tone that sags and dies into static, like a dead carrier."""
    return _drop([tone(520, 0.26, 300, harm=(1, 0, 0.2), attack=0.04, release=0.12)], 1000, 0.14, 52, 0.9)


def disc_c():
    """Three stepped-down flat beeps (900, 650, 450 Hz) and a short static tail."""
    return _drop([np.concatenate([tone(f, 0.07, harm=(1, 0, 0.18), attack=0.02, release=0.03), silence(0.05)])
                  for f in (900, 650, 450)], 1200, 0.10, 53)


DISC_VARIANTS = {"a": disc_a, "b": disc_b, "c": disc_c}
disconnect = disc_c


def write(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.repeat(pcm[:, None], 2, axis=1).tobytes())


if __name__ == "__main__":
    if "--audition" in sys.argv:                        # write the four Incoming Transmission options and play them
        import shutil, subprocess, time
        for k, fn in VARIANTS.items():
            p = Path(f"/tmp/toastfx-incoming-{k}.wav")
            write(p, fn())
            print(f"option {k}: {p}")
            if shutil.which("pw-play"):
                subprocess.run(["pw-play", "--volume", "0.6", str(p)])
                time.sleep(0.8)
        sys.exit(0)
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "ui" / "assets" / "callouts"
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in (("comms_check", comms_check), ("ack", acknowledgement), ("incoming", incoming), ("disconnect", disconnect)):
        x = fn()
        write(out / f"{name}.wav", x)
        print(f"{name}.wav  {len(x) / SR * 1000:.0f} ms  peak {20 * np.log10(np.abs(x).max()):.1f} dBFS")
