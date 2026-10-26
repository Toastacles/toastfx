#!/usr/bin/env bash
# Builds toastfx_<version>_<arch>.deb on THIS machine (so the engine is compiled against your PipeWire).
#   ./build-deb.sh            compile the engine and build the package
# Needs: gcc, pkg-config, libpipewire-0.3-dev, dpkg-deb   (sudo apt install build-essential pkg-config libpipewire-0.3-dev)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/.." && pwd)"
VER="${TOASTFX_VERSION:-1.0.0}"
ARCH="$(dpkg --print-architecture)"
BUILD="$HERE/build"
ROOT="$BUILD/toastfx_${VER}_${ARCH}"

command -v dpkg-deb >/dev/null || { echo "dpkg-deb not found"; exit 1; }
rm -rf "$BUILD"
mkdir -p "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/lib/toastfx/ui" "$ROOT/usr/lib/systemd/user" \
         "$ROOT/usr/share/applications" "$ROOT/usr/share/pixmaps" "$ROOT/etc/xdg/autostart" "$ROOT/usr/share/doc/toastfx"

echo "== Engine =="
if [ -n "${TOASTFX_PREBUILT:-}" ]; then
  cp "$TOASTFX_PREBUILT" "$ROOT/usr/bin/toastfx"; echo "  using prebuilt $TOASTFX_PREBUILT"
else
  command -v gcc >/dev/null || { echo "gcc missing: sudo apt install build-essential"; exit 1; }
  pkg-config --exists libpipewire-0.3 || { echo "PipeWire headers missing: sudo apt install libpipewire-0.3-dev pkg-config"; exit 1; }
  gcc -O2 -Wall "$REPO/engine/toastfx.c" -o "$ROOT/usr/bin/toastfx" $(pkg-config --cflags --libs libpipewire-0.3) -lm -lpthread
  echo "  compiled"
fi
chmod 755 "$ROOT/usr/bin/toastfx"

echo "== Window, soundboard, hotkeys =="
cp -r "$REPO/ui/." "$ROOT/usr/lib/toastfx/ui/"
rm -f "$ROOT/usr/lib/toastfx/ui/install.sh" "$ROOT/usr/lib/toastfx/ui/uninstall.sh"
chmod 755 "$ROOT"/usr/lib/toastfx/ui/toastfx-control "$ROOT"/usr/lib/toastfx/ui/toastfx-sfx "$ROOT"/usr/lib/toastfx/ui/toastfx-hotkeys
find "$ROOT/usr/lib/toastfx/ui" -type f ! -name 'toastfx-*' -exec chmod 644 {} +
for t in toastfx-control toastfx-sfx toastfx-hotkeys; do
  ln -s "../lib/toastfx/ui/$t" "$ROOT/usr/bin/$t"
done
install -m 755 "$REPO/engine/toastfx-ctl" "$ROOT/usr/bin/toastfx-ctl"
install -m 644 "$HERE/extras/toastfx.png" "$ROOT/usr/share/pixmaps/toastfx.png"

echo "== Menu entry and hotkey autostart =="
cat > "$ROOT/usr/share/applications/toastfx-control.desktop" <<D
[Desktop Entry]
Type=Application
Name=ToastFX
Comment=Voice effects and soundboard
Exec=/usr/bin/toastfx-control
Icon=toastfx
Categories=AudioVideo;Audio;
Terminal=false
D
cat > "$ROOT/etc/xdg/autostart/toastfx-hotkeys.desktop" <<D
[Desktop Entry]
Type=Application
Name=ToastFX hotkeys
Exec=/usr/bin/toastfx-hotkeys
NoDisplay=true
D

echo "== Services (installed, not enabled) =="
cat > "$ROOT/usr/lib/systemd/user/toastfx.service" <<'D'
[Unit]
Description=ToastFX Real-Time Voice Changer
After=pipewire.service wireplumber.service toastfx-mic.service

[Service]
Type=simple
Environment=TOASTFX_OUTPUT=toastfx_sink
ExecStart=/usr/bin/toastfx
Restart=on-failure
RestartSec=2
TimeoutStopSec=5

[Install]
WantedBy=default.target
D
MIC_UNIT="$HOME/.config/systemd/user/toastfx-mic.service"
if [ -f "$MIC_UNIT" ]; then
  cp "$MIC_UNIT" "$ROOT/usr/lib/systemd/user/toastfx-mic.service"; echo "  packaged your working toastfx-mic.service"
else
  cat > "$ROOT/usr/lib/systemd/user/toastfx-mic.service" <<'D'
[Unit]
Description=ToastFX virtual microphone (toastfx_sink -> toastfx_mic)
After=pipewire.service wireplumber.service

[Service]
Type=simple
ExecStart=/usr/bin/pw-loopback -m "[ FL FR ]" --capture-props="media.class=Audio/Sink node.name=toastfx_sink node.description=ToastFX-Output" --playback-props="media.class=Audio/Source node.name=toastfx_mic node.description=ToastFX-Mic"
Restart=on-failure

[Install]
WantedBy=default.target
D
  echo "  no existing unit found: wrote a default one (untested on your machine)"
fi

cat > "$ROOT/usr/share/doc/toastfx/README.Debian" <<'D'
ToastFX
-------
First time on a new machine (as your normal user, not root):
  systemctl --user enable --now toastfx-mic toastfx
  # optional: pin the microphone (find names with: pactl list short sources)
  systemctl --user edit toastfx      ->  [Service]
                                         Environment=TOASTFX_INPUT=<your mic node name>
Then open "ToastFX" from the app menu. In Discord set Input Device to "ToastFX Mic" and turn Automatic Gain Control off.
Hotkeys start at login (X11 sessions only).
Your own units in ~/.config/systemd/user override the packaged ones.
D

cat > "$ROOT/DEBIAN/control" <<D
Package: toastfx
Version: $VER
Architecture: $ARCH
Maintainer: ToastFX <noreply@localhost>
Section: sound
Priority: optional
Depends: python3 (>= 3.8), python3-tk, python3-pil, pipewire, pipewire-bin, pulseaudio-utils, libx11-6, libpipewire-0.3-0t64 | libpipewire-0.3-0
Recommends: ffmpeg, libnotify-bin, wireplumber
Installed-Size: $(du -sk "$ROOT" | cut -f1)
Description: Real-time voice changer and soundboard for PipeWire
 Voice effects (Dry, Radio, Helmet Comms, Robot) with live tweak sliders,
 a PipeWire soundboard and global hotkeys (X11), all in one window.
 Feeds a virtual microphone ("ToastFX Mic") for Discord and games.
D
cat > "$ROOT/DEBIAN/postinst" <<'D'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
echo "ToastFX installed. First time here? See /usr/share/doc/toastfx/README.Debian"
exit 0
D
cat > "$ROOT/DEBIAN/prerm" <<'D'
#!/bin/sh
set -e
pkill -x toastfx-hotkeys 2>/dev/null || true
exit 0
D
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm"
find "$ROOT" -type d -exec chmod 755 {} +

dpkg-deb --root-owner-group --build "$ROOT" "$HERE/toastfx_${VER}_${ARCH}.deb" >/dev/null
echo
echo "Built: $HERE/toastfx_${VER}_${ARCH}.deb"
echo "Install with:  sudo apt install $HERE/toastfx_${VER}_${ARCH}.deb"
