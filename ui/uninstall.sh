#!/usr/bin/env bash
# Removes the ToastFX window, soundboard player and hotkey listener. Leaves the engine, services,
# routing and your config/sounds (~/.config/toastfx) alone.
pkill -f toastfx-hotkeys 2>/dev/null
pkill -f toastfx-vox 2>/dev/null
pkill -f toastfx-control 2>/dev/null
rm -f "$HOME/.local/bin/toastfx-control" "$HOME/.local/bin/toastfx-sfx" "$HOME/.local/bin/toastfx-hotkeys"
rm -f "$HOME/.config/autostart/toastfx-hotkeys.desktop" "$HOME/.local/share/applications/toastfx-control.desktop"
rm -rf "$HOME/.local/share/toastfx/ui"
echo "Removed. Your sounds and key choices are still in ~/.config/toastfx."
