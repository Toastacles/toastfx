#!/usr/bin/env bash
# ToastFX control window: installs only the window, soundboard player and hotkey listener.
# It does NOT touch the toastfx engine, its services or any audio routing. Undo with ./uninstall.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/toastfx/ui"
BIN="$HOME/.local/bin"
AUTO="$HOME/.config/autostart"
APPS="$HOME/.local/share/applications"

echo "== Checking what the window needs =="
miss=0
python3 -c "import tkinter, PIL" 2>/dev/null || { echo "  MISSING: python3-tk and python3-pil  ->  sudo apt install python3-tk python3-pil"; miss=1; }
for c in pw-play parec ffmpeg; do
  command -v "$c" >/dev/null || { echo "  MISSING: $c"; miss=1; }
done
echo "  (pw-play and parec come from pipewire-bin / pulseaudio-utils; ffmpeg only matters for mp3/m4a files)"
python3 -c "import tkinter, PIL" 2>/dev/null || { echo "Install python3-tk and python3-pil first, then run this again."; exit 1; }
[ -n "$DISPLAY" ] || echo "  note: DISPLAY not set (run this from your desktop session)"

echo "== Installing to $DEST =="
mkdir -p "$DEST" "$BIN" "$AUTO" "$APPS"
rm -rf "$DEST/assets"
cp -r "$HERE/assets" "$DEST/assets"
cp "$HERE"/toastfx_common.py "$HERE"/toastfx_core.py "$HERE"/toastfx_ui.py \
   "$HERE"/toastfx-control "$HERE"/toastfx-sfx "$HERE"/toastfx-hotkeys "$HERE"/toastfx-vox "$DEST/"
chmod +x "$DEST"/toastfx-control "$DEST"/toastfx-sfx "$DEST"/toastfx-hotkeys "$DEST"/toastfx-vox

# the voice switcher the window and hotkeys call
CTL=""
for c in "$(command -v toastfx-ctl || true)" "$HOME/Desktop/toastfx/toastfx/toastfx-ctl" "$HOME/toastfx/toastfx-ctl"; do
  [ -n "$c" ] && [ -x "$c" ] && { CTL="$c"; break; }
done
if [ -n "$CTL" ]; then ln -sf "$CTL" "$DEST/toastfx-ctl"; echo "  voice switcher: $CTL"
else echo "  WARNING: toastfx-ctl not found. Put it at $DEST/toastfx-ctl (voice buttons need it)."; fi

for t in toastfx-control toastfx-sfx toastfx-hotkeys; do ln -sf "$DEST/$t" "$BIN/$t"; done

cat > "$AUTO/toastfx-hotkeys.desktop" <<D
[Desktop Entry]
Type=Application
Name=ToastFX hotkeys
Exec=$DEST/toastfx-hotkeys
X-GNOME-Autostart-enabled=true
NoDisplay=true
D
cat > "$APPS/toastfx-control.desktop" <<D
[Desktop Entry]
Type=Application
Name=ToastFX
Comment=Voice effects and soundboard
Exec=$DEST/toastfx-control
Icon=$DEST/assets/app_icon.png
Categories=AudioVideo;Audio;
Terminal=false
D

echo "== Done =="
echo "Open it:  toastfx-control   (or search 'ToastFX' in your app menu)"
echo "Hotkeys start at login; to start them now:  nohup toastfx-hotkeys >/dev/null 2>&1 &"
echo "Check the soundboard path:  toastfx-sfx test   (say 'Let's Check' in Discord's mic test)"
