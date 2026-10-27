"""Tests for the squad-callout soundboard. Run:  python3 -m unittest discover -s tests -v

No real audio is needed: `pw-play` is replaced by a stub that logs its arguments. The hotkey test needs Xvfb and
libXtst (skipped if they are missing); the window test uses a fake tkinter, so it needs neither a display nor Tk.
"""
import array
import importlib.machinery
import importlib.util
import json
import math
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
UI = Path(os.environ.get("TOASTFX_UI", ROOT / "ui"))
SLOTS = ["comms_check", "ack", "incoming", "disconnect"]


def write_wav(path, rate=48000, ch=2, width=2, seconds=0.5, amp=0.5, freq=440.0):
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(width)
        w.setframerate(rate)
        buf = bytearray()
        for i in range(n):
            v = amp * math.sin(2 * math.pi * freq * i / rate)
            for _ in range(ch):
                if width == 1:
                    buf += struct.pack("<B", int(128 + v * 127))
                elif width == 2:
                    buf += struct.pack("<h", int(v * 32767))
                elif width == 3:
                    buf += struct.pack("<i", int(v * 8388607))[:3]
                else:
                    buf += struct.pack("<i", int(v * 2147483647))
        w.writeframes(bytes(buf))


class Sandbox(unittest.TestCase):
    """Fresh HOME and runtime dir, a stub pw-play first on PATH, and the ui package imported against them."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="toastfx-test-"))
        self.home, self.run = self.tmp / "home", self.tmp / "run"
        self.bin = self.tmp / "bin"
        for d in (self.home, self.run, self.bin):
            d.mkdir()
        self.log = self.tmp / "pwplay.log"
        stub = self.bin / "pw-play"
        hold = self.bin / "pw-play-hold"                       # stands in for a running pw-play for 2 s
        shutil.copy(shutil.which("sleep"), hold)
        stub.write_text(f'#!/bin/sh\necho "$@" >> "{self.log}"\nexec "{hold}" "${{STUB_HOLD:-2}}"\n')
        stub.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), XDG_RUNTIME_DIR=str(self.run),
                        XDG_CONFIG_HOME=str(self.home / ".config"), PATH=f"{self.bin}:{os.environ['PATH']}")
        self.env.pop("DISPLAY", None)
        self._old = dict(os.environ)
        os.environ.update(self.env)
        os.environ.pop("DISPLAY", None)
        for m in [m for m in sys.modules if m.startswith("toastfx_")]:
            del sys.modules[m]
        sys.path.insert(0, str(UI))
        import toastfx_common as C
        self.C = C

    def tearDown(self):
        subprocess.run(["pkill", "-f", str(self.bin / "pw-play-hold")], capture_output=True)
        os.environ.clear()
        os.environ.update(self._old)
        sys.path.remove(str(UI))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sfx(self, *args):
        return subprocess.run([sys.executable, str(UI / "toastfx-sfx"), *args], env=self.env,
                              capture_output=True, text=True, timeout=20)

    def plays(self):
        time.sleep(0.25)
        return self.log.read_text().strip().splitlines() if self.log.exists() else []

    def set_cfg(self, fn):
        cfg = self.C.load_config()
        fn(self.C.callouts_cfg(cfg), cfg)
        self.C.save_config(cfg)


class TestAssets(unittest.TestCase):
    def test_four_shipped_cues_are_clean(self):
        for sid in SLOTS:
            p = UI / "assets" / "callouts" / f"{sid}.wav"
            self.assertTrue(p.is_file(), f"{sid}.wav missing")
            with wave.open(str(p), "rb") as w:
                self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (48000, 2, 2), sid)
                n = w.getnframes()
                self.assertLess(n / 48000, 2.0, f"{sid} should be a short cue")
                data = array.array("h")
                data.frombytes(w.readframes(n))
            peak = max(abs(v) for v in data) / 32768.0
            self.assertLess(20 * math.log10(peak), -6.0, f"{sid} peak too hot")
            self.assertGreater(peak, 0.05, f"{sid} nearly silent")
            self.assertLess(abs(data[0]) + abs(data[1]), 400, f"{sid} starts with a click")
            self.assertLess(abs(data[-1]) + abs(data[-2]), 400, f"{sid} ends with a click")

    def test_generator_is_reproducible(self):
        try:
            import numpy, scipy  # only needed to regenerate the sounds, not to use them
        except ImportError:
            self.skipTest("numpy/scipy not installed")
        out = Path(tempfile.mkdtemp())
        try:
            subprocess.run([sys.executable, str(ROOT / "tools" / "make_callouts.py"), str(out)], check=True,
                           capture_output=True)
            for sid in SLOTS:
                self.assertEqual((out / f"{sid}.wav").read_bytes(),
                                 (UI / "assets" / "callouts" / f"{sid}.wav").read_bytes(), sid)
        finally:
            shutil.rmtree(out, ignore_errors=True)


class TestConfig(Sandbox):
    def test_defaults_are_conservative_and_keyless(self):
        cfg = self.C.load_config()
        co = self.C.callouts_cfg(cfg)
        self.assertTrue(co["enabled"])
        self.assertLessEqual(co["volume"], 0.7)
        for sid in SLOTS:
            self.assertTrue(co["slots"][sid]["enabled"])
            self.assertLessEqual(co["slots"][sid]["volume"], 0.7)
        self.assertFalse([k for k in cfg["hotkeys"] if k.startswith("callout:")], "no default callout keys")
        self.assertFalse(cfg["monitor"], "callouts must not reach your headphones unless you ask")

    def test_bad_values_are_repaired(self):
        cfg = {"hotkeys": {}, "callouts": {"enabled": "yes", "volume": 7, "slots": {"ack": {"volume": -3}, "x": 1}}}
        co = self.C.callouts_cfg(cfg)
        self.assertEqual(co["volume"], 1.0)
        self.assertEqual(co["slots"]["ack"]["volume"], 0.0)
        self.assertEqual(sorted(co["slots"]), sorted(SLOTS))


class TestImport(Sandbox):
    def imp(self, name="x.wav", **kw):
        src = self.tmp / name
        write_wav(src, **kw)
        dest = self.tmp / "out.wav"
        err = self.C.import_wav(src, dest)
        return err, dest

    def check_out(self, dest, seconds, peak_max=0.51):
        with wave.open(str(dest), "rb") as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (48000, 2, 2))
            self.assertAlmostEqual(w.getnframes() / 48000, seconds, delta=0.02)
            d = array.array("h")
            d.frombytes(w.readframes(w.getnframes()))
        self.assertLessEqual(max(abs(v) for v in d) / 32768.0, peak_max)

    def test_mono_44k_becomes_48k_stereo(self):
        err, dest = self.imp(rate=44100, ch=1, seconds=0.5, amp=0.3)
        self.assertIsNone(err)
        self.check_out(dest, 0.5)

    def test_24_and_8_bit(self):
        for width in (1, 3, 4):
            err, dest = self.imp(width=width, seconds=0.3, amp=0.3)
            self.assertIsNone(err, f"{width * 8}-bit")
            self.check_out(dest, 0.3)

    def test_loud_file_is_turned_down_quiet_file_is_not(self):
        _, dest = self.imp(amp=0.99)
        self.check_out(dest, 0.5, peak_max=0.51)
        _, dest = self.imp(amp=0.1)
        with wave.open(str(dest), "rb") as w:
            d = array.array("h")
            d.frombytes(w.readframes(w.getnframes()))
        self.assertAlmostEqual(max(abs(v) for v in d) / 32768.0, 0.1, delta=0.01)

    def test_too_long_garbage_missing_silent(self):
        err, _ = self.imp(seconds=16, rate=8000)
        self.assertIn("long", err.lower())
        junk = self.tmp / "junk.wav"
        junk.write_bytes(b"this is not audio" * 100)
        self.assertTrue(self.C.import_wav(junk, self.tmp / "o.wav"))
        self.assertEqual(self.C.import_wav(self.tmp / "nope.wav", self.tmp / "o.wav"), "file not found")
        err, dest = self.imp(amp=0.0)
        self.assertIn("silent", err)
        self.assertFalse(dest.exists(), "a rejected file must not leave anything behind")
        self.assertFalse(list(self.tmp.glob("*.part")))

    def test_oversize_file_rejected_before_reading(self):
        big = self.tmp / "big.wav"
        with open(big, "wb") as f:
            f.truncate(self.C.WAV_MAX_BYTES + 1)
        self.assertIn("too big", self.C.import_wav(big, self.tmp / "o.wav"))


class TestSfxCommand(Sandbox):
    def test_plays_through_the_virtual_mic_only(self):
        r = self.sfx("callout", "comms_check")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = self.plays()
        self.assertEqual(len(lines), 1, "one player: nothing goes to the headphones")
        self.assertIn("--target toastfx_sink", lines[0])
        self.assertIn("comms_check.wav", lines[0])
        self.assertIn("--volume 0.49", lines[0], "0.7 master x 0.7 slot")

    def test_monitor_only_when_chosen(self):
        self.set_cfg(lambda co, cfg: cfg.__setitem__("monitor", True))
        self.sfx("callout", "incoming")
        lines = self.plays()
        self.assertEqual(len(lines), 2)
        self.assertEqual(sum("--target" in l for l in lines), 1, "one to the mic, one to the headphones")

    def test_each_slot_is_independent(self):
        for sid in SLOTS:
            self.assertEqual(self.sfx("callout", sid).returncode, 0)
        self.assertEqual([sid in l for sid, l in zip(SLOTS, self.plays())], [True] * 4)

    def test_key_repeat_is_swallowed_then_allowed(self):
        # a 2 s window so a loaded machine (slow process start-up) cannot make a "repeat" look like a new press
        self.env["TOASTFX_CALLOUT_DEBOUNCE"] = "2"
        self.sfx("callout", "ack")
        for _ in range(3):
            self.assertEqual(self.sfx("callout", "ack").returncode, 0)
        self.assertEqual(len(self.plays()), 1)
        time.sleep(2.2)
        self.sfx("callout", "ack")
        self.assertEqual(len(self.plays()), 2)

    def test_disabled_slot_and_master_switch(self):
        self.set_cfg(lambda co, cfg: co["slots"]["ack"].__setitem__("enabled", False))
        r = self.sfx("callout", "ack")
        self.assertEqual(r.returncode, 2)
        self.assertIn("is off", r.stderr)
        self.assertEqual(self.sfx("callout", "incoming").returncode, 0)
        self.set_cfg(lambda co, cfg: co.__setitem__("enabled", False))
        self.assertEqual(self.sfx("callout", "incoming").returncode, 2)
        self.assertEqual(len(self.plays()), 1, "only the one before the master switch went off")

    def test_volume_is_master_times_slot_and_clamped(self):
        def f(co, cfg):
            co["volume"], co["slots"]["ack"]["volume"] = 0.5, 0.5
            co["slots"]["incoming"]["volume"] = 0.0
        self.set_cfg(f)
        self.sfx("callout", "ack")
        self.assertIn("--volume 0.25", self.plays()[0])

    def test_replacement_missing_and_corrupt_files(self):
        src = self.tmp / "mine.wav"
        write_wav(src, rate=44100, ch=1, amp=0.4)
        r = self.sfx("callout-replace", "disconnect", str(src))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.C.callout_is_custom("disconnect"))
        self.sfx("callout", "disconnect")
        self.assertIn(str(self.C.CALLOUT_DIR / "disconnect.wav"), self.plays()[0])
        # a bad replacement is refused and the old sound is kept
        junk = self.tmp / "junk.wav"
        junk.write_bytes(b"nope")
        r = self.sfx("callout-replace", "disconnect", str(junk))
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(self.C.callout_is_custom("disconnect"))
        # a corrupt file that appears on disk later: graceful message, nothing played
        (self.C.CALLOUT_DIR / "ack.wav").write_bytes(b"corrupt")
        time.sleep(0.5)
        r = self.sfx("callout", "ack")
        self.assertEqual(r.returncode, 3)
        self.assertIn("unreadable", r.stderr)
        self.assertEqual(len(self.plays()), 1)
        # reset goes back to the shipped sound
        self.sfx("callout-reset", "disconnect")
        self.assertFalse(self.C.callout_is_custom("disconnect"))

    def test_stop_all_stops_callouts_too(self):
        self.sfx("callout", "incoming")
        self.plays()
        self.assertTrue(self.C.players(), "the cue is tracked as a running player")
        self.sfx("stop")
        time.sleep(0.3)
        self.assertFalse(self.C.players())

    def test_unknown_slot(self):
        self.assertEqual(self.sfx("callout", "nope").returncode, 1)
        self.assertEqual(len(self.plays()), 0)


class TestEngineUntouched(unittest.TestCase):
    """Callouts are mixed by PipeWire, so the audio callback must not know about them at all."""

    def test_engine_has_no_callout_or_file_code(self):
        src = (ROOT / "engine" / "toastfx.c").read_text() if (ROOT / "engine" / "toastfx.c").exists() else ""
        if not src:
            self.skipTest("engine source not found")
        for word in ("callout", "fopen", "malloc(", "wav"):
            self.assertNotIn(word, src.lower().replace("// ", ""), f"engine mentions '{word}'")


class TestMixHeadroom(unittest.TestCase):
    def test_default_cue_leaves_room_for_the_voice(self):
        worst = 0.0
        for sid in SLOTS:
            with wave.open(str(UI / "assets" / "callouts" / f"{sid}.wav"), "rb") as w:
                d = array.array("h")
                d.frombytes(w.readframes(w.getnframes()))
            worst = max(worst, max(abs(v) for v in d) / 32768.0 * 0.7 * 0.7)
        self.assertLess(20 * math.log10(worst), -14.0, "default cue peak at the mix, in dBFS")
        # voice leaves the engine limiter at <= 0.9; even a coincident peak stays below +1 dB over
        self.assertLess(0.9 + worst, 1.12)


class TestSpeechGate(unittest.TestCase):
    """The talk-ended detector, fed synthetic 20 ms levels (dBFS) with a little random wobble."""

    @staticmethod
    def run_gate(parts, seed=1, sd=2.5, **kw):
        import random
        rnd = random.Random(seed)
        sys.path.insert(0, str(UI))
        from toastfx_common import SpeechGate
        g, hits, i = SpeechGate(**kw), [], 0
        for seconds, db in parts:
            for _ in range(int(seconds / 0.02)):
                if g.feed(db + rnd.gauss(0, sd)):
                    hits.append(round(i * 0.02, 2))
                i += 1
        return hits

    def many(self, parts, want, runs=25, **kw):
        bad = [sd for sd in range(runs) if len(self.run_gate(parts, seed=sd, **kw)) != want]
        self.assertFalse(bad, f"wrong number of beeps (wanted {want}) for seeds {bad}")

    def test_one_beep_after_a_normal_stretch_of_talking(self):
        self.many([(2, -62), (1.5, -26), (2, -62)], 1)

    def test_blip_or_cough_is_ignored(self):
        self.many([(2, -62), (0.3, -26), (2, -62)], 0)

    def test_short_pause_between_phrases_is_not_the_end(self):
        self.many([(2, -62), (1.2, -26), (0.4, -62), (1.2, -26), (2, -62)], 1)

    def test_steady_background_noise_never_triggers(self):
        self.many([(10, -45)], 0)
        self.many([(10, -35)], 0)

    def test_speech_over_a_noisy_room(self):
        self.many([(3, -45), (1.5, -25), (3, -45)], 1)

    def test_two_separate_talks_give_two_beeps(self):
        self.many([(2, -62), (1.5, -26), (3, -62), (1.2, -26), (2, -62)], 2)

    def test_refractory_blocks_a_second_beep_right_away(self):
        self.many([(2, -62), (1.5, -26), (0.9, -62), (1.2, -26), (2, -62)], 1, refractory=3.0)

    def test_sensitivity_changes_what_counts_as_quiet_speech(self):
        whisper = [(2, -62), (1.5, -38), (2, -62)]
        self.many(whisper, 0, sensitivity=0.0)
        self.many(whisper, 1, sensitivity=1.0)

    def test_our_own_sounds_are_not_speech(self):
        sys.path.insert(0, str(UI))
        from toastfx_common import SpeechGate
        g = SpeechGate()
        fired = [g.feed(-26.0, muted=True) for _ in range(200)] + [g.feed(-62.0) for _ in range(200)]
        self.assertFalse(any(fired))


class TestAutoBeepWatcher(Sandbox):
    """Runs the real toastfx-vox with a fake parec (synthetic speech), journalctl (voice mode) and pw-play."""

    def fake_tools(self, mode_text, pcm_script):
        (self.bin / "journalctl").write_text(f'#!/bin/sh\necho "{mode_text}"\n')
        (self.bin / "parec").write_text(f"#!{sys.executable}\n{pcm_script}\n")
        for n in ("journalctl", "parec"):
            (self.bin / n).chmod(0o755)

    SPEECH = """
import random, struct, sys, time
random.seed(3)
def block(db):
    amp = 32768 * 10 ** (db / 20) * 1.7
    return b"".join(struct.pack("<h", int(max(-32768, min(32767, random.gauss(0, amp))))) for _ in range(320))
plan = [(1.0, -66), (1.4, -28), (2.2, -66), (0.3, -28), (2.2, -66), (1.2, -28), (2.5, -66)]
for secs, db in plan:
    for _ in range(int(secs / 0.02)):
        sys.stdout.buffer.write(block(db)); sys.stdout.buffer.flush(); time.sleep(0.008)   # 2.5x real time
time.sleep(30)
"""

    def run_watcher(self, secs=14):
        env = dict(self.env, STUB_HOLD="0.3")                      # a cue "plays" for 0.3 s, like the real ones
        p = subprocess.Popen([sys.executable, str(UI / "toastfx-vox")], env=env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE)
        time.sleep(secs)
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
        p.stderr.close()
        return p

    def enable(self, **kw):
        def f(co, cfg):
            co["auto"].update(dict(enabled=True, slot="ack", **kw))
        self.set_cfg(f)

    def test_beeps_after_each_real_talk_in_helmet_mode_only_once_each(self):
        self.fake_tools("Mode: Helmet Comms", self.SPEECH)
        self.enable()
        self.run_watcher()
        lines = self.plays()
        self.assertEqual(len(lines), 2, f"two real talks, one blip: {lines}")
        self.assertTrue(all("--target toastfx_sink" in l and "ack.wav" in l for l in lines))
        self.assertFalse((self.run / "toastfx-vox.pid").exists(), "pid file is cleaned up on exit")

    def test_no_beep_in_other_voice_modes(self):
        for mode in ("Mode: Dry Mic", "Mode: Radio", "Mode: Robot"):
            self.fake_tools(mode, self.SPEECH)
            self.enable()
            self.run_watcher(secs=6)
            self.assertEqual(len(self.plays()), 0, mode)

    def test_off_by_default_and_respects_the_master_and_cue_switches(self):
        self.fake_tools("Mode: Helmet Comms", self.SPEECH)
        self.run_watcher(secs=6)                                   # Auto beep never turned on
        self.assertEqual(len(self.plays()), 0)
        self.enable()
        self.set_cfg(lambda co, cfg: co.__setitem__("enabled", False))
        self.run_watcher(secs=6)
        self.assertEqual(len(self.plays()), 0, "callout master switch off")
        self.set_cfg(lambda co, cfg: (co.__setitem__("enabled", True), co["slots"]["ack"].__setitem__("enabled", False)))
        self.run_watcher(secs=6)
        self.assertEqual(len(self.plays()), 0, "the chosen cue is switched off")

    def test_silent_while_a_soundboard_clip_is_playing(self):
        self.fake_tools("Mode: Helmet Comms", self.SPEECH)
        self.enable()
        (self.C.PLAYING).mkdir(parents=True, exist_ok=True)
        hold = subprocess.Popen([str(self.bin / "pw-play-hold"), "20"])
        (self.C.PLAYING / str(hold.pid)).write_text("airhorn")
        try:
            self.run_watcher(secs=9)
        finally:
            hold.terminate()
        self.assertEqual(len(self.plays()), 0, "a clip passing through the mic is not you talking")

    def test_second_copy_exits_quietly(self):
        self.fake_tools("Mode: Helmet Comms", self.SPEECH)
        self.enable()
        first = subprocess.Popen([sys.executable, str(UI / "toastfx-vox")], env=self.env, stdout=subprocess.DEVNULL)
        time.sleep(1.5)
        second = subprocess.run([sys.executable, str(UI / "toastfx-vox")], env=self.env, timeout=10)
        first.terminate()
        first.wait(timeout=5)
        self.assertEqual(second.returncode, 0)

    def test_hotkeys_helper_starts_and_stops_the_watcher(self):
        self.fake_tools("Mode: Dry Mic", "import time\ntime.sleep(60)")
        loader = importlib.machinery.SourceFileLoader("hk", str(UI / "toastfx-hotkeys"))
        spec = importlib.util.spec_from_loader("hk", loader)
        hk = importlib.util.module_from_spec(spec)
        loader.exec_module(hk)
        vox = hk.Vox()
        vox.sync()
        self.assertIsNone(vox.proc, "Auto beep is off: nothing runs")
        self.enable()
        vox.sync()
        self.assertIsNotNone(vox.proc)
        time.sleep(1.5)
        self.assertTrue((self.run / "toastfx-vox.pid").exists(), "the watcher is up")
        self.set_cfg(lambda co, cfg: co["auto"].__setitem__("enabled", False))
        vox.sync()
        self.assertIsNone(vox.proc, "switched off: the watcher is stopped")
        time.sleep(0.5)
        self.assertFalse((self.run / "toastfx-vox.pid").exists())

    def test_quiet_flag_means_no_desktop_note(self):
        (self.bin / "notify-send").write_text(f'#!/bin/sh\necho note >> "{self.tmp}/notes.log"\n')
        (self.bin / "notify-send").chmod(0o755)
        self.sfx("callout", "ack")
        time.sleep(0.6)
        self.sfx("callout", "ack", "--quiet")
        self.assertEqual((self.tmp / "notes.log").read_text().count("note"), 1, "only the non-quiet call notified")


@unittest.skipUnless(shutil.which("Xvfb"), "Xvfb not installed")
class TestHotkeys(Sandbox):
    def test_keys(self):
        try:
            import ctypes
            xt = ctypes.CDLL("libXtst.so.6")
            x11 = ctypes.CDLL("libX11.so.6")
        except OSError:
            self.skipTest("libXtst / libX11 not available")
        cfg = self.C.load_config()
        self.assertFalse([k for k in cfg["hotkeys"] if k.startswith("callout:")])
        cfg["hotkeys"]["callout:comms_check"] = "Ctrl+Alt+J"
        cfg["hotkeys"]["callout:ack"] = "Ctrl+Alt+K"
        self.C.callouts_cfg(cfg)["slots"]["ack"]["enabled"] = False
        self.C.save_config(cfg)
        n = next(i for i in range(60, 300) if not Path(f"/tmp/.X11-unix/X{i}").exists() and not Path(f"/tmp/.X{i}-lock").exists())
        disp = f":{n}"
        xv = subprocess.Popen(["Xvfb", disp, "-screen", "0", "640x480x24"], stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        env = dict(self.env, DISPLAY=disp)
        hk = subprocess.Popen([sys.executable, str(UI / "toastfx-hotkeys")], env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
        try:
            time.sleep(1.5)
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
            d = x11.XOpenDisplay(disp.encode())
            kc = lambda n: x11.XKeysymToKeycode(d, x11.XStringToKeysym(n.encode()))

            def key(n, down):
                xt.XTestFakeKeyEvent(d, kc(n), down, 0)
                x11.XFlush(d)

            def combo(n, repeats=1):
                key("Control_L", 1)
                key("Alt_L", 1)
                for _ in range(repeats):                 # what X auto-repeat sends: press/release pairs ~30 ms apart
                    key(n, 1)
                    key(n, 0)
                    time.sleep(0.03)
                key("Alt_L", 0)
                key("Control_L", 0)
                time.sleep(0.5)

            combo("j")
            self.assertEqual(len(self.plays()), 1, "one press, one cue")
            combo("j", repeats=40)
            self.assertEqual(len(self.plays()), 2, "holding the key (1.2 s of repeats) adds one cue, not forty")
            combo("k")
            self.assertEqual(len(self.plays()), 2, "a disabled cue's key is not even grabbed")
            self.C.callouts_cfg(cfg)["enabled"] = False
            self.C.save_config(cfg)
            os.kill(hk.pid, signal.SIGHUP)
            time.sleep(1.4)
            combo("j")
            self.assertEqual(len(self.plays()), 2, "master off: the soundboard holds no keys")
        finally:
            hk.terminate()
            xv.terminate()
            hk.wait()
            xv.wait()


def load_app():
    tk = types.ModuleType("tkinter")

    class W:
        def __init__(s, *a, **k):
            pass

        def __getattr__(s, n):
            return lambda *a, **k: 1
    tk.Tk = tk.Canvas = tk.Menu = W
    tk.PhotoImage = lambda **k: types.SimpleNamespace(**k)
    fd, mb, sd = (types.ModuleType("tkinter." + n) for n in ("filedialog", "messagebox", "simpledialog"))
    tk.filedialog, tk.messagebox, tk.simpledialog = fd, mb, sd
    sys.modules.update({"tkinter": tk, "tkinter.filedialog": fd, "tkinter.messagebox": mb, "tkinter.simpledialog": sd})
    loader = importlib.machinery.SourceFileLoader("tc", str(UI / "toastfx-control"))
    spec = importlib.util.spec_from_loader("tc", loader)
    tc = importlib.util.module_from_spec(spec)
    loader.exec_module(tc)
    with mock.patch.object(tc, "MeterReader"), mock.patch("threading.Thread"), \
            mock.patch.object(tc.Core, "start_listener"), mock.patch.object(tc.Core, "reload_listener"):
        root = W()
        root.winfo_screenwidth = lambda: 1920
        root.winfo_screenheight = lambda: 1080
        app = tc.App(root)
    return tc, app


class TestWindow(Sandbox):
    def setUp(self):
        super().setUp()
        self._mods = {k: sys.modules.get(k) for k in ("tkinter", "tkinter.filedialog", "tkinter.messagebox",
                                                      "tkinter.simpledialog")}
        self.tc, self.app = load_app()
        self.core = self.app.core

    def tearDown(self):
        for k, v in self._mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        super().tearDown()

    def click(self, kind, payload=None, dx=0.5):
        for r, k, p in self.app.hits:
            if k == kind and p == payload:
                x = r[0] + (r[2] - r[0]) * dx
                e = types.SimpleNamespace(x=x * self.app.sc, y=(r[1] + r[3]) / 2 * self.app.sc, x_root=0, y_root=0,
                                          state=0, keysym="")
                self.app.on_click(e)
                return e
        self.fail(f"no {kind}/{payload} on screen")

    def test_tabs_switch_views(self):
        self.assertEqual(self.core.view, "board")
        self.assertNotIn("co0", self.app.comp)
        self.click("tab", "callouts")
        self.assertEqual([n for n in self.app.comp if n.startswith("co")].__len__(), 7)
        self.assertNotIn("pager", self.app.comp)
        self.assertFalse([n for n in self.app.comp if n.startswith("tile")])
        self.click("tab", "board")
        self.assertNotIn("co0", self.app.comp)

    def test_click_plays_only_when_allowed(self):
        self.click("tab", "callouts")
        with mock.patch.object(self.core, "bg") as bg:
            self.click("callout", "ack")
            self.assertEqual(bg.call_args[0][0][-2:], ["callout", "ack"])
            self.click("co_switch", "ack")
            bg.reset_mock()
            self.click("callout", "ack")
            bg.assert_not_called()
            self.assertEqual(self.core.hint()[0], ["Acknowledge", "is off"])
            self.assertEqual(self.core.slot_state("ack"), "off")
            self.click("co_master")
            self.click("callout", "incoming")
            bg.assert_not_called()
            self.assertEqual(self.core.slot_state("incoming"), "off")

    def test_sliders_and_persistence(self):
        self.click("tab", "callouts")
        e = self.click("co_slider", "incoming", dx=0.0)
        self.app.on_release(e)
        self.assertLess(self.core.slot("incoming")["volume"], 0.1)
        e = self.click("co_vol", None, dx=0.25)
        self.app.on_release(e)
        saved = json.loads((self.C.CONF_DIR / "config.json").read_text())["callouts"]
        self.assertAlmostEqual(saved["volume"], 0.25, delta=0.12)
        self.assertLess(saved["slots"]["incoming"]["volume"], 0.1)

    def test_unavailable_state_and_replace(self):
        with mock.patch.object(self.tc, "callout_file", return_value=None), \
                mock.patch("toastfx_core.callout_file", return_value=None):
            self.assertEqual(self.core.slot_state("ack"), "unavailable")
        src = self.tmp / "mine.wav"
        write_wav(src, rate=22050, ch=1, amp=0.3)
        self.core.replace_slot("ack", src, wait=True)
        self.assertTrue(self.C.callout_is_custom("ack"))
        self.assertEqual(self.core.slot_state("ack"), "on")
        junk = self.tmp / "junk.wav"
        junk.write_bytes(b"x" * 50)
        self.core.replace_slot("ack", junk, wait=True)
        self.assertEqual(self.core.hint()[0][0], "Can't use that:")


    def test_auto_beep_tile(self):
        self.click("tab", "callouts")
        self.assertFalse(self.core.auto()["enabled"], "off until switched on")
        self.assertEqual(self.core.auto_status()[1], "off")
        with mock.patch.object(self.core, "reload_listener") as rl:
            self.click("auto_switch")
            self.assertTrue(self.core.auto()["enabled"])
            rl.assert_called()
        self.core.engine, self.core.mode = True, "radio"
        self.assertEqual(self.core.auto_status()[1], "armed", "waits for Helmet")
        self.core.mode = "helmet"
        self.assertEqual(self.core.auto_status(), ("LISTENING", "live"))
        self.click("co_master")                                    # callout master off
        self.assertEqual(self.core.auto_status()[1], "wait")
        e = self.click("auto_sens", dx=1.0)
        self.app.on_release(e)
        saved = json.loads((self.C.CONF_DIR / "config.json").read_text())["callouts"]["auto"]
        self.assertTrue(saved["enabled"])
        self.assertGreater(saved["sensitivity"], 0.9)
        self.core.set_auto_slot("incoming")
        self.assertEqual(self.core.auto()["slot"], "incoming")

    def test_hotkey_badge_assignment(self):
        self.click("tab", "callouts")
        self.click("badge", "callout:comms_check")
        self.assertEqual(self.core.listening, "callout:comms_check")
        with mock.patch("toastfx_core.signal_listener", return_value=True):
            self.app.on_key(types.SimpleNamespace(keysym="j", state=0x4 | 0x8))
        self.assertEqual(self.core.key_of("callout:comms_check"), "Ctrl+Alt+j")


if __name__ == "__main__":
    unittest.main(verbosity=2)
