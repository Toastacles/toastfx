# How ToastFX is put together

```
real mic -> ToastFX engine (effects) -> toastfx_sink -> toastfx_mic -> Discord / game
soundboard clips (pw-play) ------------^
```

- **Engine** (`engine/toastfx.c`): C + PipeWire. Reads the mic, applies the active effect, writes to the virtual sink.
  Commands arrive on a FIFO (`$XDG_RUNTIME_DIR/toastfx.cmd`): `dry`, `radio`, `helmet`, `robot`, `quit`, `tweak radio|helmet|mix 0-100`.
  Pick devices with `TOASTFX_INPUT` / `TOASTFX_OUTPUT` (PipeWire node names).
- **Virtual mic**: `systemd/toastfx-mic.service` runs `pw-loopback` to create `toastfx_sink` (a sink) and `toastfx_mic` (a source called "ToastFX Mic").
- **Window** (`ui/toastfx-control`): Tk + Pillow. `toastfx_ui.py` draws everything on top of `assets/skin.png`; `toastfx_core.py` holds the logic (no Tk).
- **Soundboard** (`ui/toastfx-sfx`): plays clips with `pw-play --target toastfx_sink`, so PipeWire mixes them with your voice.
- **Hotkeys** (`ui/toastfx-hotkeys`): X11 only, global `XGrabKey` through ctypes, no extra packages.
- **Stop fix**: `main()` ends with `fflush(stdout); _exit(0);` because the command thread sits in `fgets()` holding a stdio lock; a normal return would deadlock `exit()`.

## Gotchas
- Discord's Automatic Gain Control must be off (it raises the noise floor). Krisp and echo cancellation are fine.
- EasyEffects can hook the microphone path if it autostarts; keep it out of the way.
- Hotkeys need an X11 session. Wayland needs a different approach.
