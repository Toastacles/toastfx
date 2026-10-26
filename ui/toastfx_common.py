"""Shared helpers for toastfx-control, toastfx-sfx and toastfx-hotkeys (no third-party imports)."""
import json
import os
import re
import shutil
import signal
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONF_DIR = Path.home() / ".config" / "toastfx"
CONFIG = CONF_DIR / "config.json"
LIBRARY = CONF_DIR / "soundboard.json"          # list of {"name", "path"}: the same file the old soundboard used
CACHE = Path.home() / ".cache" / "toastfx"
RUN = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/toastfx-{os.getuid()}")
PLAYING = RUN / "toastfx-sfx"                   # one file per running pw-play: name = pid, content = sound name
HK_PID = RUN / "toastfx-hotkeys.pid"
HK_STATUS = RUN / "toastfx-hotkeys.status"
SINK = "toastfx_sink"
MIC_SOURCE = "toastfx_mic"

VOICE_IDS = ["dry", "radio", "helmet", "robot"]
VOICE_LABELS = {"dry": "Dry Mic", "radio": "Radio", "helmet": "Helmet Comms", "robot": "Robot"}
DEFAULT_HOTKEYS = {"voice:dry": "Ctrl+Alt+1", "voice:radio": "Ctrl+Alt+2", "voice:helmet": "Ctrl+Alt+3",
                   "voice:robot": "Ctrl+Alt+4", "stop:all": "Ctrl+Alt+0"}
MODS = ("Ctrl", "Alt", "Shift", "Super")


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def load_config():
    cfg = read_json(CONFIG, None)
    fresh = not isinstance(cfg, dict)
    if fresh:
        cfg = {"hotkeys": dict(DEFAULT_HOTKEYS)}
    if not isinstance(cfg.get("hotkeys"), dict):
        cfg["hotkeys"] = dict(DEFAULT_HOTKEYS)
    cfg.setdefault("volume", 0.7)
    cfg.setdefault("monitor", True)
    cfg.setdefault("icons", {})
    if fresh:
        write_json(CONFIG, cfg)
    return cfg


def save_config(cfg):
    write_json(CONFIG, cfg)


def load_library():
    lib = read_json(LIBRARY, [])
    if not isinstance(lib, list):
        return []
    return [s for s in lib if isinstance(s, dict) and s.get("name") and s.get("path")]


def save_library(lib):
    write_json(LIBRARY, lib)


def find_ctl():
    for cand in (BASE / "toastfx-ctl", BASE.parent / "toastfx-ctl"):
        if cand.exists():
            return str(cand)
    return shutil.which("toastfx-ctl")


# ---- key combos ---------------------------------------------------------------
def parse_combo(text):
    """'Ctrl+Alt+1' -> (['Ctrl', 'Alt'], '1'); None if unreadable."""
    if not text:
        return None
    parts = text.split("+")
    key, mods = parts[-1], parts[:-1]
    if not key or any(m not in MODS for m in mods):
        return None
    return mods, key


def combo_ok(mods, key):
    """A grabbed key never reaches games, so a bare key is only allowed when games rarely use it."""
    if mods:
        return True
    return bool(re.fullmatch(r"F(1[3-9]|2[0-4])", key)) or key.startswith("KP_") or key.startswith("XF86")


def make_combo(mods, key):
    return "+".join([m for m in MODS if m in mods] + [key])


def pretty(combo):
    p = parse_combo(combo)
    if not p:
        return combo or ""
    mods, key = p
    shown = key.upper() if len(key) == 1 else key.replace("KP_", "Num ").replace("Prior", "PgUp").replace("Next", "PgDn")
    return "+".join(mods + [shown])


# ---- players & listener ---------------------------------------------------------
def pid_alive(pid, needle):
    try:
        return needle.encode() in Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False


def players():
    """{pid: sound name} for running soundboard clips; cleans up files of finished ones."""
    out = {}
    try:
        files = list(PLAYING.iterdir())
    except OSError:
        return out
    for f in files:
        try:
            pid = int(f.name)
        except ValueError:
            continue
        if pid_alive(pid, "pw-"):
            try:
                out[pid] = f.read_text()
            except OSError:
                out[pid] = ""
        else:
            try:
                f.unlink()
            except OSError:
                pass
    return out


def listener_pid():
    try:
        pid = int(HK_PID.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid, "toastfx-hotkeys") else None


def signal_listener(sig):
    pid = listener_pid()
    if pid:
        try:
            os.kill(pid, sig)
            return True
        except OSError:
            pass
    return False
