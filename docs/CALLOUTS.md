# Squad callouts

Four short radio cues you can fire into your mic while you talk: **Comms Check**, **Transmission
Acknowledgement**, **Incoming Transmission** and **Radio Disconnect**. Your teammates hear them through
**ToastFX Mic**, mixed with your live voice. Open the **Callouts** tab next to **Soundboard** in the window.

## What you get

| | |
|---|---|
| Per-cue switch | the little toggle on each tile |
| Master switch | "Callout soundboard" tile; off means no cue plays and no keys are held |
| Volume | one slider per cue and one master (final level = master x cue); both start at 70 % |
| Hotkey per cue | click a tile's badge, press a combo. **No keys are set by default**, so nothing is grabbed until you choose |
| Panic | `Ctrl+Alt+0` (or the **Stop sounds** button) stops every sound and cue that is playing |
| Your own sound | right-click a tile > **Replace with my WAV...** (and **Back to the default sound**) |
| Feedback | tile glows and says PLAYING; a small desktop note appears (needs `libnotify-bin`; may not show over exclusive-fullscreen games); a disabled or missing cue says so instead of failing silently |

## Using your own WAV

Supported: **PCM WAV**, 8 / 16 / 24 / 32-bit, mono or stereo, any sample rate, up to **15 seconds** and
**20 MB**. ToastFX converts it once, when you pick it, into 48 kHz stereo 16-bit and stores it in
`~/.config/toastfx/callouts/<cue>.wav`. A very loud file is turned down to a -6 dBFS peak; quiet files are never
boosted. Other WAV flavours (float, ADPCM) and other formats work if `ffmpeg` is installed.
A file that is too long, silent, unreadable or too big is refused with a message and the previous sound is kept.
If a file you dropped into that folder by hand turns out to be damaged, the tile shows **NO SOUND FILE** and the
key does nothing but tell you.

Command line equivalents:

```bash
toastfx-sfx callouts                       # status of the master switch and the four cues
toastfx-sfx callout comms_check            # fire one (ids: comms_check ack incoming disconnect)
toastfx-sfx callout-replace ack ~/my.wav   # use your own WAV
toastfx-sfx callout-reset ack              # back to the shipped sound
toastfx-sfx callouts-off | callouts-on
```

## Auto beep (a roger beep when you stop talking)

On the Callouts tab, the **Auto beep** tile plays one cue by itself when you finish talking, like releasing a radio's
talk button. **Off by default.** It only listens while **Helmet Comms** is the active voice; in Dry Mic, Radio and
Robot it does nothing and is not even listening.

| | |
|---|---|
| Switch | the toggle on the tile (or click the tile); right-click for the menu |
| Which cue | right-click > **Beep sound** (default **Acknowledge**) |
| Sensitivity | slider on the tile, default 50 %: higher catches quieter talking, lower ignores more background noise |
| Test | right-click > **Test the beep** |
| Status line | OFF, CUE IS OFF (the master switch or that cue is off), ENGINE STOPPED, WAITS FOR HELMET, LISTENING |

What counts as "finished talking": at least 0.8 s of speech, then 0.7 s of quiet. A cough, a click or one short
word does nothing, and a pause of less than 0.7 s between phrases does not end the talk. After a beep it stays quiet for
2 s. It learns your room's background noise, so a steady fan or hiss does not set it off. It never reacts to its own
cue or to soundboard clips: while any of those play, it ignores the mic level.

How it works and what it does not do:

- The helper `toastfx-vox` reads only the **level** of the processed mic (`toastfx_mic`) with `parec`, 50 times a
  second. Each 20 ms block becomes one number and is dropped. Nothing is recorded, stored or sent anywhere.
- It runs as a separate process, started and stopped by the hotkeys helper when you switch the tile on or off. The
  audio engine is not touched, so the live voice path and its latency are unchanged.
- The beep goes through the normal callout path, so the master switch, the cue's own switch and volume, and "Hear
  it myself" off by default all apply.
- The beep comes about 0.7 s after you stop, because that is how long it waits to be sure you are done. It cannot
  come sooner without also firing in the middle of sentences.
- Needs `parec` (package `pulseaudio-utils`). If you change the sensitivity, it takes effect within a couple of
  seconds.

## Key-repeat

Holding a cue's key fires it once. The listener ignores repeats until the key has been quiet for 0.6 s, and the
player itself ignores a second trigger of the same cue inside 0.45 s (window clicks, a second hotkey tool, ...).
`Ctrl+Alt+F1`-`F12` cannot be used: the X server turns them into console switches before any program sees them.

## How the audio works (and what it does not do)

Callouts do not touch the voice engine. A cue is played with `pw-play --target toastfx_sink`, the same sink your
processed voice goes into, so PipeWire mixes the two before they reach `ToastFX Mic`. Consequences:

- The engine's real-time callback is unchanged: no file reading, allocation or locking was added to it. Decoding,
  resampling and the file check happen in the window or the `toastfx-sfx` helper, never in the audio thread.
- Cues are independent of Radio / Helmet / Robot: they are not run through those effects, whichever is selected.
- Cues are **not** sent to your headphones unless **Hear it myself** is on.
- Your voice never pauses; a cue starting is a new stream joining the mix.
- A cue starts once the helper has launched `pw-play` (a Python start-up plus a process launch, measured at about 40 ms here
  with a stub player; real PipeWire stream set-up adds a little more). `pw-play`, not
  the engine, reads the small file from disk.

**Clipping.** There is no limiter on the mixed result; adding one would mean a new processing stage and extra
latency in the path. Instead there is headroom: shipped cues peak at -12 dBFS, and the default 70 % x 70 % puts a cue
at about -18 dBFS. Your voice leaves the engine at no more than -0.9 dBFS (its soft limiter), so a loud shout that
lands exactly on a cue's peak could in theory exceed full scale by a fraction of a dB. In practice the PipeWire mix is
floating-point (it does not clip in the graph), and the cue is short and quiet, so audible clipping is unlikely, but
if you replace a cue with something loud, keep its volume slider down.

## Shipped sounds

The four cues are synthesised by `tools/make_callouts.py` (numpy + scipy, fixed random seed): original work in a gentle "helmet cam" style (low static, soft crackle, muffled flat beeps, soft starts, no harsh edges). Other sets: `--style cam` (grittier) and `--style muffled` (the earlier set). Original work,
released under the project's MIT license, no samples from any game or film. Run
`python3 tools/make_callouts.py` to regenerate them byte for byte.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Covers the shipped assets, the auto-beep speech detector on synthetic talking (one beep per real talk, ignores coughs, steady noise and its own sounds, whisper vs. sensitivity), the whole `toastfx-vox` process against fake `parec`/`journalctl` streams (Helmet only, switches respected, silent during clips, single instance), the hotkeys helper starting and stopping it, WAV import limits, config defaults and repair, every `toastfx-sfx callout` rule (enabled,
volume, repeat, missing/corrupt file, monitor off by default, stop-all), hotkeys under a virtual X server
(one cue per held key, disabled cue not grabbed, master off releases keys), the window's clicks and sliders, and a
check that the engine source contains no callout or file code. Not covered: real PipeWire mixing into Discord and
the real Tk window; test those by hand (below).

## Check it by hand

1. Discord: Input Device = **ToastFX Mic**. Join a voice channel with a friend, or record it:
   `parecord --device=toastfx_mic.monitor /tmp/cue.wav`.
2. Talk, and while talking trigger a cue: your voice must carry on without a gap and the cue must be audible with it.
3. Trigger a cue with **Hear it myself** off: you should hear nothing in your headphones, but the recording has it.
