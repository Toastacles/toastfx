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
VOX_PID = RUN / "toastfx-vox.pid"
SINK = "toastfx_sink"
MIC_SOURCE = "toastfx_mic"

# Squad callouts: four short cues you can trigger by key; mixed into the virtual mic by PipeWire (outside the engine).
CALLOUTS = [("comms_check", "Comms Check"), ("ack", "Transmission Acknowledgement"),
            ("incoming", "Incoming Transmission"), ("disconnect", "Radio Disconnect")]
CALLOUT_IDS = [c[0] for c in CALLOUTS]
CALLOUT_LABELS = dict(CALLOUTS)
CALLOUT_SHORT = {"comms_check": "Comms Check", "ack": "Acknowledge", "incoming": "Incoming", "disconnect": "Disconnect"}
CALLOUT_DIR = CONF_DIR / "callouts"                      # your own replacements, converted to 48 kHz stereo WAV
CALLOUT_ASSETS = BASE / "assets" / "callouts"            # the shipped (original) sounds
CALLOUT_DEBOUNCE = float(os.environ.get("TOASTFX_CALLOUT_DEBOUNCE", 0.45))   # env override is for the tests
CALLOUT_REPEAT_GAP = 0.6   # key held down: ignore events until the key has been quiet this long                                  # seconds: ignores key-repeat and double presses
WAV_MAX_SECONDS = 15
WAV_MAX_BYTES = 20 * 1024 * 1024

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
    cfg.setdefault("monitor", False)        # callouts/sounds only reach your headphones if you turn this on
    cfg.setdefault("icons", {})
    callouts_cfg(cfg)
    if fresh:
        write_json(CONFIG, cfg)
    return cfg


def callouts_cfg(cfg):
    """Return cfg["callouts"] with every field present and clamped (conservative volumes by default)."""
    co = cfg.get("callouts")
    if not isinstance(co, dict):
        co = cfg["callouts"] = {}
    co["enabled"] = bool(co.get("enabled", True))
    co["volume"] = _vol(co.get("volume"), 0.7)
    slots = co.get("slots")
    if not isinstance(slots, dict):
        slots = co["slots"] = {}
    au = co.get("auto")
    if not isinstance(au, dict):
        au = co["auto"] = {}
    au["enabled"] = bool(au.get("enabled", False))                  # off until you turn it on
    au["slot"] = au.get("slot") if au.get("slot") in CALLOUT_IDS else "ack"
    au["sensitivity"] = _vol(au.get("sensitivity"), 0.5)
    for stray in [k for k in slots if k not in CALLOUT_IDS]:
        del slots[stray]
    for sid in CALLOUT_IDS:
        sl = slots.get(sid)
        if not isinstance(sl, dict):
            sl = slots[sid] = {}
        sl["enabled"] = bool(sl.get("enabled", True))
        sl["volume"] = _vol(sl.get("volume"), 0.7)
    return co


def _vol(v, default):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


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


# ---- callout sounds ------------------------------------------------------------
def callout_file(sid):
    """The file a callout plays: your replacement if you set one, else the shipped sound. None if neither exists."""
    for p in (CALLOUT_DIR / f"{sid}.wav", CALLOUT_ASSETS / f"{sid}.wav"):
        if p.is_file():
            return p
    return None


def callout_is_custom(sid):
    return (CALLOUT_DIR / f"{sid}.wav").is_file()


def callout_reset(sid):
    try:
        (CALLOUT_DIR / f"{sid}.wav").unlink()
    except OSError:
        pass


def _read_pcm_wav(path):
    """-> (rate, channels, [per-channel float lists]) or raises ValueError with a plain message."""
    import array
    import sys
    import wave
    try:
        w = wave.open(str(path), "rb")
    except (wave.Error, EOFError, OSError) as exc:
        raise ValueError("not a PCM WAV file") from exc
    with w:
        nch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if rate <= 0 or nch < 1 or n < 1:
            raise ValueError("the WAV is empty")
        if n / rate > WAV_MAX_SECONDS:
            raise ValueError(f"too long ({n / rate:.0f} s; limit {WAV_MAX_SECONDS} s)")
        raw = w.readframes(n)
    if width == 1:
        vals = [(b - 128) / 128.0 for b in raw]
    elif width == 2:
        a = array.array("h"); a.frombytes(raw[:len(raw) // 2 * 2])
        if sys.byteorder == "big":
            a.byteswap()
        vals = [v / 32768.0 for v in a]
    elif width == 3:
        vals = []
        for i in range(0, len(raw) - 2, 3):
            v = int.from_bytes(raw[i:i + 3], "little", signed=True)
            vals.append(v / 8388608.0)
    elif width == 4:
        a = array.array("i"); a.frombytes(raw[:len(raw) // 4 * 4])
        if sys.byteorder == "big":
            a.byteswap()
        vals = [v / 2147483648.0 for v in a]
    else:
        raise ValueError("unsupported sample size")
    chans = [vals[c::nch] for c in range(min(nch, 2))]
    return rate, len(chans), chans


def import_wav(src, dest):
    """Validate a WAV and store it as 48 kHz stereo 16-bit at `dest`, quieter if it was very loud.
    Runs in the window / CLI (never in the audio engine). Returns None on success or an error message."""
    import shutil
    import subprocess
    import tempfile
    import wave
    from pathlib import Path as P
    src = P(src).expanduser()
    if not src.is_file():
        return "file not found"
    if src.stat().st_size > WAV_MAX_BYTES:
        return f"file too big (limit {WAV_MAX_BYTES // 1048576} MB)"
    tmp = None
    try:
        try:
            rate, nch, chans = _read_pcm_wav(src)
        except ValueError as first:
            if not shutil.which("ffmpeg"):            # float / ADPCM / other formats need ffmpeg
                return f"{first}; use a 16-bit PCM WAV (or install ffmpeg to import other formats)"
            fd, tmp = tempfile.mkstemp(suffix=".wav"); os.close(fd)
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-t", str(WAV_MAX_SECONDS + 1),
                                "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", tmp], capture_output=True)
            if r.returncode:
                return "could not read that file"
            try:
                rate, nch, chans = _read_pcm_wav(tmp)
            except ValueError as exc:
                return str(exc)
        if nch == 1:
            chans = [chans[0], chans[0]]
        if rate != 48000:                              # linear resample, done here so the engine never has to
            ratio, out_n = rate / 48000.0, int(len(chans[0]) * 48000 / rate)
            res = []
            for ch in chans:
                last = len(ch) - 1
                o = []
                for i in range(out_n):
                    pos = i * ratio
                    j = int(pos)
                    f = pos - j
                    a = ch[j if j <= last else last]
                    b = ch[j + 1 if j + 1 <= last else last]
                    o.append(a + (b - a) * f)
                res.append(o)
            chans = res
        peak = max((abs(v) for ch in chans for v in ch), default=0.0)
        if peak < 1e-4:
            return "the sound is silent"
        gain = min(1.0, 0.5 / peak)                    # only ever turn loud files down (peak -6 dBFS)
        frames = bytearray()
        import struct
        for l, r_ in zip(chans[0], chans[1]):
            frames += struct.pack("<hh", int(max(-1.0, min(1.0, l * gain)) * 32767),
                                  int(max(-1.0, min(1.0, r_ * gain)) * 32767))
        dest = P(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        with wave.open(str(part), "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
            w.writeframes(bytes(frames))
        part.replace(dest)
        return None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


# ---- speech detector for the auto beep ---------------------------------------------
class SpeechGate:
    """Decides when you have finished talking. Feed it one 20 ms level (dBFS) at a time with feed(db, muted).

    feed() returns True exactly once per finished stretch of talking: after `hang` seconds of quiet that followed at
    least `min_talk` seconds of speech. Short blips (a cough, a click, one word) never count, our own cues and
    soundboard clips (muted=True) never count, and after a trigger it stays quiet for `refractory` seconds.
    Everything is counted in frames, not clock time, so it behaves the same on a loaded machine.
    """
    FRAME = 0.02

    def __init__(self, sensitivity=0.5, hang=0.7, min_talk=0.8, refractory=2.0):
        self.hang, self.min_talk, self.refractory = hang, min_talk, refractory
        self.set_sensitivity(sensitivity)
        self.floor = -60.0
        self.reset()

    def set_sensitivity(self, s):
        s = max(0.0, min(1.0, float(s)))
        self.margin = 6.0 + 8.0 * (1.0 - s)            # dB above the room's noise floor that counts as speech
        self.abs_min = -46.0 + 10.0 * (1.0 - s)        # and never quieter than this

    def reset(self):
        self.talking, self.lead, self.quiet, self.voiced, self.span, self.cool = False, 0, 0, 0, 0, 0

    def threshold(self):
        return max(self.floor + self.margin, self.abs_min)

    def feed(self, db, muted=False):
        if self.cool > 0:
            self.cool -= 1
        if muted:                                       # our own sound is playing: forget what we were hearing
            self.reset()
            self.cool = max(self.cool, int(0.4 / self.FRAME))
            return False
        active = db > self.threshold() + (3.0 if self.talking else 0.0)   # noise wobble must not keep a talk alive
        if not self.talking and not active:             # learn the room: fall fast, rise slowly
            self.floor = db if db < self.floor else self.floor + (db - self.floor) * 0.004
            self.floor = max(-80.0, min(-35.0, self.floor))
        if not self.talking:
            self.lead = self.lead + 1 if active else max(0, self.lead - 1)
            if self.lead >= 6 and self.cool == 0:       # 120 ms of voice: talking has started
                self.talking, self.quiet, self.voiced, self.span = True, 0, self.lead, self.lead
            return False
        self.span += 1
        if active:
            self.quiet, self.voiced = 0, self.voiced + 1
            return False
        self.quiet += 1
        if self.quiet * self.FRAME < self.hang:
            return False
        long_enough = self.voiced * self.FRAME >= self.min_talk
        self.reset()
        if long_enough:
            self.cool = int(self.refractory / self.FRAME)
            return True
        return False


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
