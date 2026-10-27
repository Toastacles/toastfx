"""Window logic for toastfx-control: state, actions and background polling. No Tk, no Pillow."""
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from toastfx_common import *

SERVICE = "toastfx"
PER_PAGE = 8                 # slots per page; the "Add sound" tile takes one
SOUND_ICONS = ["burst", "note", "chick", "flame", "cat", "pizza", "beer"]
NAME_TO_ID = {"Dry Mic": "dry", "Radio": "radio", "Helmet Comms": "helmet", "Robot": "robot"}
DEVNULL = subprocess.DEVNULL


def parse_mode(journal_text):
    """Last mode ToastFX reported, from its journal lines ('ToastFX running (mode: X)' / 'Mode: X')."""
    mode = None
    for line in journal_text.splitlines():
        m = re.search(r"ToastFX running \(mode: ([^)]+)\)", line) or re.search(r"\bMode: (.+?)\s*$", line)
        if m and m.group(1).strip() in NAME_TO_ID:
            mode = NAME_TO_ID[m.group(1).strip()]
    return mode


def keysym_to_combo(keysym, state, ctrl_mask=0x4, alt_mask=0x8, shift_mask=0x1, super_mask=0x40):
    """Tk key event (keysym name + state bits) -> 'Ctrl+Alt+1' or None for a bare modifier press."""
    if keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Super_L", "Super_R",
                  "Meta_L", "Meta_R", "Caps_Lock", "Num_Lock", "ISO_Level3_Shift", "Mode_switch"):
        return None
    mods = []
    if state & ctrl_mask:
        mods.append("Ctrl")
    if state & alt_mask:
        mods.append("Alt")
    if state & shift_mask:
        mods.append("Shift")
    if state & super_mask:
        mods.append("Super")
    key = keysym
    if len(key) == 1:
        key = key.lower()
    if key == "ISO_Left_Tab":
        key = "Tab"
    return make_combo(mods, key)


EXIT_MISSING_CODE = 3


class Core:
    def __init__(self):
        self.cfg = load_config()
        self.lib = load_library()
        self.page = 0
        self.view = "board"               # "board" (sound tiles) or "callouts"
        self.mode = "dry"                 # the engine always starts in Dry Mic
        self.engine = False
        self.playing = set()              # names of sounds playing right now
        self.level = 0.0
        self.listening = None             # target being assigned, e.g. "voice:radio" / "sound:Airhorn"
        self.flash = None                 # (lines, until) short-lived message for the hint box
        self.hk_failed = []
        self.hk_on = False
        self.pw_detail = "PipeWire"
        self.lock = threading.Lock()
        self._ensure_icons()

    # ---- library / pages ------------------------------------------------------------
    def _ensure_icons(self):
        changed = False
        for s in self.lib:
            if s["name"] not in self.cfg["icons"]:
                self.cfg["icons"][s["name"]] = SOUND_ICONS[len(self.cfg["icons"]) % len(SOUND_ICONS)]
                changed = True
        if changed:
            save_config(self.cfg)

    def items(self):
        return self.lib + [None]          # None = the "Add sound" tile

    def pages(self):
        return max(1, -(-len(self.items()) // PER_PAGE))

    def page_items(self):
        self.page = max(0, min(self.page, self.pages() - 1))
        chunk = self.items()[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]
        return list(enumerate(chunk))     # [(slot, sound dict | None)]

    def icon_for(self, name):
        return self.cfg["icons"].get(name, SOUND_ICONS[0])

    def turn_page(self, step):
        self.page = max(0, min(self.pages() - 1, self.page + step))

    def add_sounds(self, paths):
        added = 0
        have = {s["name"].lower() for s in self.lib}
        for p in paths:
            p = str(Path(p).expanduser().resolve())
            base = Path(p).stem[:40] or "Sound"
            name, n = base, 2
            while name.lower() in have:
                name, n = f"{base} {n}", n + 1
            have.add(name.lower())
            self.lib.append({"name": name, "path": p})
            added += 1
        if added:
            save_library(self.lib)
            self._ensure_icons()
            self.page = self.pages() - 1
            self.say([f"Added {added} sound" + ("s" if added > 1 else ""), ""])
        return added

    def remove_sound(self, name):
        self.lib = [s for s in self.lib if s["name"] != name]
        save_library(self.lib)
        self.cfg["hotkeys"].pop("sound:" + name, None)
        self.cfg["icons"].pop(name, None)
        save_config(self.cfg)
        self.reload_listener()
        self.page = max(0, min(self.page, self.pages() - 1))

    def rename_sound(self, old, new):
        """Returns an error message, or None on success."""
        new = (new or "").strip()[:40]
        if not new:
            return "Name can't be empty"
        if new == old:
            return None
        if any(s["name"].lower() == new.lower() for s in self.lib if s["name"] != old):
            return "That name is already used"
        for sound in self.lib:
            if sound["name"] == old:
                sound["name"] = new
        save_library(self.lib)
        hk = self.cfg["hotkeys"]
        if "sound:" + old in hk:
            hk["sound:" + new] = hk.pop("sound:" + old)
        if old in self.cfg["icons"]:
            self.cfg["icons"][new] = self.cfg["icons"].pop(old)
        save_config(self.cfg)
        self.reload_listener()
        return None

    # ---- actions --------------------------------------------------------------------
    def bg(self, argv, timeout=8, done=None):
        def work():
            try:
                r = subprocess.run(argv, stdin=DEVNULL, capture_output=True, text=True, timeout=timeout)
            except Exception as exc:
                r = None
                self.say(["Command failed", str(exc)[:18]], warn=True)
            if done:
                done(r)
        threading.Thread(target=work, daemon=True).start()

    def set_voice(self, vid):
        ctl = find_ctl()
        if not ctl:
            self.say(["toastfx-ctl", "not found"], warn=True)
            return

        def done(r):
            if r is not None and r.returncode == 0:
                self.mode = vid
            elif r is not None:
                self.say(["Engine not", "running?"], warn=True)
        self.bg([ctl, vid], timeout=4, done=done)

    def toggle_engine(self):
        """Ask systemd what is true right now, then do the opposite (the window's own idea can be a moment stale)."""
        self.engine_hold = time.time() + 4          # ignore status polls that were already in flight
        self.engine = not self.engine                # show the change at once

        def work():
            try:
                now = subprocess.run(["systemctl", "--user", "is-active", SERVICE], stdin=DEVNULL,
                                     capture_output=True, text=True, timeout=5).stdout.strip() == "active"
                act = "stop" if now else "start"
                r = subprocess.run(["systemctl", "--user", act, SERVICE], stdin=DEVNULL, capture_output=True,
                                   text=True, timeout=20)
                self.engine = (act == "start") and r.returncode == 0
                if r.returncode != 0:
                    why = (r.stderr or "").strip().splitlines()[-1:] or ["failed"]
                    self.say(["Engine " + act + " failed", why[0][:22]], warn=True, secs=6)
            except Exception as exc:
                self.say(["Engine command", str(exc)[:20]], warn=True)
            self.engine_hold = time.time() + 1.5
        threading.Thread(target=work, daemon=True).start()

    def play(self, name):
        self.bg([sys.executable, str(BASE / "toastfx-sfx"), "play", name], timeout=15, done=self._sfx_done)

    def stop_all(self):
        self.bg([sys.executable, str(BASE / "toastfx-sfx"), "stop"], timeout=5)
        self.playing = set()

    def _sfx_done(self, r):
        if r is not None and r.returncode != 0:
            msg = (r.stderr or "").strip().splitlines()[-1:] or ["play failed"]
            self.say(["Can't play:", msg[0].replace("toastfx-sfx: ", "")[:20]], warn=True)

    def set_volume(self, v, save=False):
        self.cfg["volume"] = max(0.0, min(1.0, float(v)))
        if save:
            save_config(self.cfg)

    # ---- live tweaks (sent to the engine through its command pipe) ----------------------
    TWEAKS = ("radio", "helmet", "mix")

    def tweak(self, name):
        return int(self.cfg.get("tweaks", {}).get(name, 100))

    def set_tweak(self, name, value, save=False):
        pct = int(round(max(0.0, min(1.0, float(value))) * 100))
        tw = self.cfg.setdefault("tweaks", {})
        changed = tw.get(name) != pct
        tw[name] = pct
        if changed and self.engine:
            self.send_cmd(f"tweak {name} {pct}")
        if save:
            save_config(self.cfg)

    def send_tweaks(self):
        for name in self.TWEAKS:
            self.send_cmd(f"tweak {name} {self.tweak(name)}")

    def send_cmd(self, text):
        d = os.environ.get("XDG_RUNTIME_DIR")
        path = f"{d}/toastfx.cmd" if d else f"/tmp/toastfx-{os.getuid()}.cmd"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            return False
        try:
            os.write(fd, (text + "\n").encode())
            return True
        except OSError:
            return False
        finally:
            os.close(fd)

    def toggle_monitor(self):
        self.cfg["monitor"] = not self.cfg.get("monitor", False)
        save_config(self.cfg)

    # ---- hotkeys --------------------------------------------------------------------
    def key_of(self, target):
        return self.cfg["hotkeys"].get(target, "")

    def key_text(self, target):
        if self.listening == target:
            return "PRESS A KEY", "listen"
        k = self.key_of(target)
        return (pretty(k), "set") if k else ("+ KEY", "empty")

    def label_of(self, target):
        kind, _, arg = target.partition(":")
        if kind == "callout":
            return CALLOUT_SHORT.get(arg, arg)
        return VOICE_LABELS.get(arg, arg) if kind == "voice" else arg

    def begin_listen(self, target):
        self.listening = target
        signal_listener(signal.SIGUSR1)        # release the grabs so the window can see the key

    def end_listen(self):
        self.listening = None
        self.reload_listener()

    def reload_listener(self):
        if not signal_listener(signal.SIGHUP):
            self.start_listener()

    def start_listener(self):
        exe = BASE / "toastfx-hotkeys"
        if not exe.exists() or listener_pid():
            return
        try:
            subprocess.Popen([sys.executable, str(exe)], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL,
                             start_new_session=True)
        except OSError:
            pass

    def assign(self, target, combo):
        """Returns True when the combo was stored."""
        parsed = parse_combo(combo)
        if not parsed or not combo_ok(*parsed):
            self.say(["Add Ctrl, Alt", "or Shift"], warn=True)
            return False
        mods, key = parsed
        if "Ctrl" in mods and "Alt" in mods and key.upper() in {f"F{i}" for i in range(1, 13)}:
            self.say(["Ctrl+Alt+F1-12", "switch consoles"], warn=True)       # the X server eats these before any app
            return False
        stolen = [t for t, c in self.cfg["hotkeys"].items() if c == combo and t != target]
        for t in stolen:
            del self.cfg["hotkeys"][t]
        self.cfg["hotkeys"][target] = combo
        save_config(self.cfg)
        if stolen:
            self.say(["Moved from", self.label_of(stolen[0])[:14]])
        self.end_listen()
        return True

    def clear(self, target):
        self.cfg["hotkeys"].pop(target, None)
        save_config(self.cfg)
        self.end_listen()

    # ---- squad callouts ---------------------------------------------------------------
    def co(self):
        return callouts_cfg(self.cfg)

    def co_on(self):
        return self.co()["enabled"]

    def slot(self, sid):
        return self.co()["slots"][sid]

    def slot_state(self, sid):
        """'playing' | 'unavailable' | 'off' | 'on' (what the tile shows)."""
        if ("callout:" + sid) in self.playing:
            return "playing"
        if callout_file(sid) is None:
            return "unavailable"
        if not self.co_on() or not self.slot(sid)["enabled"]:
            return "off"
        return "on"

    # ---- auto beep (plays a cue after you stop talking, Helmet mode only) ----------------------
    def auto(self):
        return self.co()["auto"]

    def auto_status(self):
        """(text, kind) for the Auto beep tile: kind is 'off' | 'wait' | 'armed' | 'live'."""
        au = self.auto()
        if not au["enabled"]:
            return "OFF", "off"
        if not self.co_on() or not self.slot(au["slot"])["enabled"]:
            return "CUE IS OFF", "wait"
        if not self.engine:
            return "ENGINE STOPPED", "wait"
        if self.mode != "helmet":
            return "WAITS FOR HELMET", "armed"
        return "LISTENING", "live"

    def toggle_auto(self):
        au = self.auto()
        au["enabled"] = not au["enabled"]
        save_config(self.cfg)
        self.reload_listener()                       # the hotkeys helper starts / stops the watcher
        self.say(["Auto beep", "ON" if au["enabled"] else "OFF"])

    def set_auto_sens(self, v, save=False):
        self.auto()["sensitivity"] = max(0.0, min(1.0, float(v)))
        if save:
            save_config(self.cfg)                    # the watcher re-reads this every couple of seconds

    def set_auto_slot(self, sid):
        self.auto()["slot"] = sid
        save_config(self.cfg)
        self.say(["Auto beep plays", CALLOUT_SHORT[sid]])

    def set_view(self, view):
        self.view = view

    def toggle_callouts(self):
        c = self.co()
        c["enabled"] = not c["enabled"]
        save_config(self.cfg)
        self.reload_listener()                       # a switched-off soundboard gives its keys back
        self.say(["Callouts " + ("ON" if c["enabled"] else "OFF")])

    def toggle_slot(self, sid):
        sl = self.slot(sid)
        sl["enabled"] = not sl["enabled"]
        save_config(self.cfg)
        self.reload_listener()
        self.say([CALLOUT_SHORT[sid], "ON" if sl["enabled"] else "OFF"])

    def set_co_volume(self, v, sid=None, save=False):
        v = max(0.0, min(1.0, float(v)))
        (self.slot(sid) if sid else self.co())["volume"] = v
        if save:
            save_config(self.cfg)

    def play_callout(self, sid):
        """Same path the hotkey uses, so the window and the key behave identically (including every check)."""
        if not self.co_on():
            self.say(["Callouts are", "switched off"], warn=True)
            return
        if not self.slot(sid)["enabled"]:
            self.say([CALLOUT_SHORT[sid], "is off"], warn=True)
            return
        self.bg([sys.executable, str(BASE / "toastfx-sfx"), "callout", sid], timeout=10, done=self._callout_done)

    def _callout_done(self, r):
        if r is not None and r.returncode == EXIT_MISSING_CODE:
            self.say(["Sound missing", "or unreadable"], warn=True)

    def replace_slot(self, sid, path, wait=False):
        """Convert + store a WAV for a slot. Runs in a thread (a long file takes a moment in pure Python)."""
        def work():
            err = import_wav(path, CALLOUT_DIR / f"{sid}.wav")
            if err:
                self.say(["Can't use that:", err[:22]], warn=True, secs=6)
            else:
                self.say([CALLOUT_SHORT[sid], "replaced"])
            self.replaced = err
        self.say(["Converting", "your WAV..."])
        t = threading.Thread(target=work, daemon=True)
        t.start()
        if wait:
            t.join()
        return t

    def reset_slot(self, sid):
        callout_reset(sid)
        self.say([CALLOUT_SHORT[sid], "back to default"])

    # ---- hint box -------------------------------------------------------------------
    def say(self, lines, warn=False, secs=3.0):
        self.flash = (lines, warn, time.time() + secs)

    def hint(self):
        """(lines, warn) for the dashed box at the bottom right."""
        if self.listening:
            return ["Press a combo", "Esc cancels"], False
        if self.flash and self.flash[2] > time.time():
            return self.flash[0], self.flash[1]
        if not self.hk_on:
            return ["Hotkeys off", "click to start"], True
        if self.hk_failed:
            return ["Key in use:", pretty(self.hk_failed[0])], True
        return ["Click a badge", "to set a key"], False

    def hotkey_rows(self):
        rows = []
        for vid in VOICE_IDS:
            rows.append((pretty(self.key_of("voice:" + vid)) or "—", VOICE_LABELS[vid]))
        rows.append((pretty(self.key_of("stop:all")) or "—", "Stop all sounds"))
        rows.append(("Bksp", "Clear a key"))
        return rows

    # ---- polling (runs in a thread) -------------------------------------------------
    def poll_once(self):
        out = {}
        try:
            r = subprocess.run(["systemctl", "--user", "is-active", SERVICE], capture_output=True, text=True, timeout=3)
            out["engine"] = r.stdout.strip() == "active"
        except Exception:
            out["engine"] = None
        if out["engine"]:
            try:
                r = subprocess.run(["journalctl", "--user", "-u", SERVICE, "-n", "60", "--no-pager", "-o", "cat"],
                                   capture_output=True, text=True, timeout=4)
                out["mode"] = parse_mode(r.stdout)
            except Exception:
                out["mode"] = None
        out["playing"] = set(players().values())
        out["hk_on"] = listener_pid() is not None
        out["hk_failed"] = (read_json(HK_STATUS, {}) or {}).get("failed", [])
        return out

    def apply_poll(self, d):
        if d.get("engine") is not None and time.time() >= getattr(self, "engine_hold", 0):
            was = self.engine
            self.engine = d["engine"]
            if self.engine and not was:          # engine just (re)started: it begins at 100%, so resend ours
                self.send_tweaks()
        if d.get("mode"):
            self.mode = d["mode"]
        self.playing = d.get("playing", set())
        self.hk_on = d.get("hk_on", False)
        self.hk_failed = d.get("hk_failed", [])

    def load_versions(self):
        try:
            out = subprocess.run(["pipewire", "--version"], capture_output=True, text=True, timeout=3).stdout
            m = re.search(r"libpipewire\s+([\d.]+)", out)
            if m:
                self.pw_detail = f"PipeWire {m.group(1)}  •  48kHz  •  2ch"
        except Exception:
            pass


class MeterReader(threading.Thread):
    """Reads the processed mic (toastfx_mic) with parec and keeps a smoothed 0..1 level."""

    def __init__(self, core):
        super().__init__(daemon=True)
        self.core, self.proc, self.stop_flag = core, None, False

    def run(self):
        import array
        import math
        if not shutil.which("parec"):
            return
        while not self.stop_flag:
            try:
                self.proc = subprocess.Popen(
                    ["parec", f"--device={MIC_SOURCE}", "--raw", "--format=s16le", "--rate=24000", "--channels=1",
                     "--latency-msec=20"], stdout=subprocess.PIPE, stderr=DEVNULL, bufsize=0)
                while not self.stop_flag:
                    raw = self.proc.stdout.read(960)
                    if not raw:
                        break
                    s = array.array("h")
                    s.frombytes(raw[:len(raw) // 2 * 2])
                    if s:
                        rms = math.sqrt(sum(v * v for v in s) / len(s))
                        lvl = min(1.0, math.sqrt(rms / 9000.0))
                        old = self.core.level
                        self.core.level = lvl if lvl > old else old * 0.86 + lvl * 0.14
            except Exception:
                pass
            self.core.level = 0.0
            for _ in range(20):
                if self.stop_flag:
                    return
                time.sleep(0.1)

    def stop(self):
        self.stop_flag = True
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        except Exception:
            pass
