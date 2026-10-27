# ToastFX

Real-time voice changer and soundboard for Linux (PipeWire), built for games and Discord.

- Voice effects: **Dry Mic**, **Radio** (wartime tinny), **Helmet Comms** (squad comms), **Robot**
- Live **Quick Tweaks** sliders: Radio Filter, Helmet Filter, Dry/Wet Mix
- **Soundboard** that mixes into your mic through PipeWire (mp3, wav, ogg, flac, m4a ...)
- **Global hotkeys** for every voice and sound (X11), with key badges on each button
- One window, one `.deb`

> Status: works on Pop!_OS (X11, PipeWire 1.x, KDE/COSMIC). Other setups are untested.


## Install (Debian / Ubuntu / Pop!_OS)

### Option 1: Install the prebuilt package (recommended)

1. Download the latest `toastfx` `.deb` package from the [GitHub Releases page](https://github.com/Toastacles/toastfx/releases).
2. Open a terminal in your Downloads folder and run:

   ```bash
   sudo apt install ./toastfx_1.0.0_*.deb
   ```

   If the downloaded filename differs, replace the wildcard pattern with the actual filename.

### Option 2: Build from source

Install the required build dependencies, clone the repository, and build the Debian package:

```bash
sudo apt install build-essential pkg-config libpipewire-0.3-dev
git clone https://github.com/Toastacles/toastfx.git
cd toastfx
./packaging/build-deb.sh
sudo apt install ./packaging/toastfx_1.0.0_*.deb
```

**Note:** If APT reports a sandbox warning when installing a locally built package, copy the `.deb` to a directory accessible to APT, such as `/tmp`, and install it from there.
First run (as your normal user):

```bash
systemctl --user enable --now toastfx-mic toastfx
# optional: pin your microphone (find it with: pactl list short sources)
systemctl --user edit toastfx      # add:  [Service]
                                   #       Environment=TOASTFX_INPUT=<your mic node name>
```

Open **ToastFX** from the app menu. In Discord set **Input Device** to **ToastFX Mic** and turn **Automatic Gain Control** off.

Needs: `pipewire`, `pipewire-bin` (pw-play, pw-loopback), `pulseaudio-utils` (parec), `python3-tk`, `python3-pil`; `ffmpeg` for mp3/m4a.

## Controls

- Click a voice card or press its hotkey (defaults `Ctrl+Alt+1..4`; `Ctrl+Alt+0` stops all sounds).
- Click a key badge, press a combo to set it; Esc cancels, Backspace clears. Right-click a sound for more.
- A bare key is only allowed for F13-F24, keypad and media keys, so normal typing and games keep working.

## Windows (experimental proof)

`windows/` has a tiny Python proof (mic -> effect -> VB-Cable). See `windows/README.md`.

## Layout

| Path | What |
|---|---|
| `engine/` | the C engine and `toastfx-ctl` |
| `ui/` | window, soundboard player, hotkey listener, artwork |
| `packaging/` | `.deb` builder |
| `systemd/` | user service examples |
| `windows/` | Windows proof of concept |
| `tools/` | scripts used to cut the artwork into `ui/assets` |
| `docs/` | how it fits together |

## License

MIT, see `LICENSE`. Please keep the copyright notice in copies. The artwork in `ui/assets` is part of this project.
