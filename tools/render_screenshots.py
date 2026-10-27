#!/usr/bin/env python3
"""Render README screenshots of the ToastFX window without a display.

Uses the window's own drawing code (ui/toastfx_ui.py) and artwork, with a stand-in for Tk, so the pictures show
the real layout with made-up example data (sounds, keys, levels). They are renders, not captures of a live window.

Usage: python3 tools/render_screenshots.py [output_dir]      (default: docs/screenshots)
"""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"

home = tempfile.mkdtemp(prefix="toastfx-shots-")
os.environ.update(HOME=home, XDG_RUNTIME_DIR=home + "/run", XDG_CONFIG_HOME=home + "/cfg", TOASTFX_FLAT="1",
                  TOASTFX_SCALE="1.0")
os.makedirs(home + "/run")
sys.path.insert(0, str(UI))

tk = types.ModuleType("tkinter")


class W:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, n):
        return lambda *a, **k: 1


tk.Tk = tk.Canvas = tk.Menu = W
tk.PhotoImage = lambda **k: types.SimpleNamespace(**k)
for n in ("filedialog", "messagebox", "simpledialog"):
    m = types.ModuleType("tkinter." + n)
    setattr(tk, n, m)
    sys.modules["tkinter." + n] = m
sys.modules["tkinter"] = tk

loader = importlib.machinery.SourceFileLoader("tc", str(UI / "toastfx-control"))
spec = importlib.util.spec_from_loader("tc", loader)
tc = importlib.util.module_from_spec(spec)
loader.exec_module(tc)

with mock.patch.object(tc, "MeterReader"), mock.patch("threading.Thread"), \
        mock.patch.object(tc.Core, "start_listener"), mock.patch.object(tc.Core, "reload_listener"):
    root = W()
    root.winfo_screenwidth = lambda: 3000
    root.winfo_screenheight = lambda: 2000
    app = tc.App(root)
core = app.core

core.lib = [{"name": n, "path": f"/example/{n}.wav"} for n in
            ("Airhorn", "Sad Trombone", "Crickets", "Vine Boom", "Wilhelm", "Rimshot", "Dial-up")]
core.cfg["icons"] = {"Airhorn": "burst", "Sad Trombone": "note", "Crickets": "chick", "Vine Boom": "flame",
                     "Wilhelm": "cat", "Rimshot": "pizza", "Dial-up": "beer"}
core.cfg["hotkeys"].update({"sound:Airhorn": "Ctrl+Alt+A", "sound:Rimshot": "Ctrl+Alt+R",
                            "callout:comms_check": "Ctrl+Alt+J", "callout:ack": "Ctrl+Alt+K"})
core.engine, core.mode, core.hk_on, core.level = True, "helmet", True, 0.58
core.pw_detail = "PipeWire · ToastFX Mic"
core.cfg["monitor"] = False
core.auto()["enabled"] = True
core.vox_on = True


def snap(name):
    app.refresh()
    frame = app.skin.copy()
    for n in tc.Z_ORDER:
        if n in app.comp:
            img, pos = app.comp[n]
            frame.alpha_composite(img, dest=pos)
    OUT.mkdir(parents=True, exist_ok=True)
    frame.convert("RGB").save(OUT / name, optimize=True)
    print("wrote", OUT / name)


core.playing = {"Vine Boom"}
snap("window-voices-soundboard.png")
core.view, core.playing = "callouts", {"callout:incoming"}
snap("window-callouts.png")
