#!/usr/bin/env bash
# Set the tray widget to start at login, and start it now.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script="$here/audio-tray.py"
autostart="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/audio-device-tray.desktop"

if ! command -v pactl >/dev/null; then
    echo "Missing: pactl. Try: sudo apt install pulseaudio-utils" >&2
    exit 1
fi
if ! python3 -c "
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
" 2>/dev/null; then
    echo "Missing GTK/AppIndicator bindings. Try:" >&2
    echo "  sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1" >&2
    exit 1
fi

mkdir -p "$(dirname "$autostart")"
cat > "$autostart" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Audio Device Tray
Comment=Pick the default audio output and input from the system tray
Exec=/usr/bin/python3 "$script"
Icon=audio-headset
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
NoDisplay=false
DESKTOP
echo "Autostart entry written to $autostart"

if pgrep -f "python3 .*audio-tray\.py" >/dev/null; then
    echo "Already running."
else
    setsid nohup python3 "$script" >/dev/null 2>&1 &
    echo "Started."
fi
