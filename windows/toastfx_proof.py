#!/usr/bin/env python3
"""ToastFX Windows proof: mic -> voice effect -> VB-Cable ("CABLE Input"), so Discord can use "CABLE Output" as its mic.

  python toastfx_proof.py --list                 show audio devices
  python toastfx_proof.py                        start (default mic -> CABLE Input, Helmet)
  python toastfx_proof.py --mic "Headset" --out "CABLE Input" --mode radio --block 256

Keys while running:  d = dry   r = radio   h = helmet   [ ] = effect strength -/+   q = quit
"""
import argparse
import sys
import time

import numpy as np
import sounddevice as sd

import toastfx_dsp as dsp


def devices():
    apis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        out.append((i, d["name"], apis[d["hostapi"]]["name"], d["max_input_channels"], d["max_output_channels"]))
    return out


def find(name, want_input, prefer="Windows WASAPI"):
    matches = [d for d in devices() if name.lower() in d[1].lower() and (d[3] if want_input else d[4]) > 0]
    if not matches:
        return None
    matches.sort(key=lambda d: d[2] != prefer)          # WASAPI first
    return matches[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--mic", help="part of the microphone's name (default: Windows default mic)")
    ap.add_argument("--out", default="CABLE Input", help="part of the output device's name")
    ap.add_argument("--mode", default="helmet", choices=["dry", "radio", "helmet"])
    ap.add_argument("--block", type=int, default=256, help="frames per block (256 = 5 ms)")
    a = ap.parse_args()

    if a.list:
        for i, name, api, ins, outs in devices():
            print(f"{i:3d}  {api:22s} in={ins} out={outs}  {name}")
        return 0

    if a.mic:
        mic = find(a.mic, True)
    else:
        di = sd.default.device[0]
        mic = next((d for d in devices() if d[0] == di), None)
    out = find(a.out, False)
    if not mic:
        print("Microphone not found. Run with --list and pass part of its name with --mic."); return 1
    if not out:
        print(f"Output '{a.out}' not found. Is VB-Cable installed (and the PC restarted)? Run with --list."); return 1
    print(f"Mic    : [{mic[0]}] {mic[1]}  ({mic[2]})")
    print(f"Output : [{out[0]}] {out[1]}  ({out[2]})")

    state = {"mode": a.mode, "p": 1.0, "xr": 0, "load": 0.0, "peak": 0.0}
    engines = {}

    def engine():
        key = (state["mode"], round(state["p"], 1))
        if key not in engines:
            engines.clear()
            engines[key] = dsp.make(state["mode"], state["p"])
        return engines[key]

    def callback(indata, outdata, frames, tinfo, status):
        t0 = time.perf_counter()
        if status:
            state["xr"] += 1
        y = engine().process(indata[:, 0].astype(np.float32))
        outdata[:] = y[:, None]                         # same signal on every output channel
        state["peak"] = max(state["peak"] * 0.95, float(np.abs(y).max()))
        state["load"] = max(state["load"] * 0.9, (time.perf_counter() - t0) / (frames / dsp.SR))

    extra = None
    if hasattr(sd, "WasapiSettings"):
        try:
            extra = sd.WasapiSettings(auto_convert=True)
        except Exception:
            extra = None
    try:
        stream = sd.Stream(samplerate=dsp.SR, blocksize=a.block, device=(mic[0], out[0]), dtype="float32",
                           channels=(1, min(2, out[4])), callback=callback,
                           extra_settings=(extra, extra) if extra else None)
    except Exception as exc:
        print("Could not open the audio stream:", exc)
        print("Tip: try --block 512, or close other apps using the mic or CABLE.")
        return 1

    with stream:
        li, lo = stream.latency
        print(f"Latency: input {li*1000:.0f} ms + output {lo*1000:.0f} ms = about {(li+lo)*1000:.0f} ms (plus Discord's own)")
        print("Running. Set Discord's Input Device to 'CABLE Output'.  Keys: d r h  [ ]  q\n")
        try:
            import msvcrt
            getkey = lambda: msvcrt.getwch() if msvcrt.kbhit() else None
        except ImportError:
            getkey = lambda: None
        last = 0
        while True:
            k = getkey()
            if k:
                k = k.lower()
                if k == "q": break
                if k in "drh": state["mode"] = {"d": "dry", "r": "radio", "h": "helmet"}[k]
                if k == "[": state["p"] = max(0.0, state["p"] - 0.1)
                if k == "]": state["p"] = min(1.0, state["p"] + 0.1)
            if time.time() - last > 1:
                last = time.time()
                print(f"\r{state['mode']:6s} strength {state['p']*100:3.0f}%  level {state['peak']:.2f}  cpu {state['load']*100:4.1f}%  dropouts {state['xr']}   ", end="", flush=True)
            time.sleep(0.03)
    print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
