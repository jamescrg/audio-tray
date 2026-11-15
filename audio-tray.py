#!/usr/bin/env python3
"""System tray widget for picking the default audio output and input device.

Talks to PipeWire/PulseAudio through `pactl`, and keeps the menu in sync with
`pactl subscribe` so devices appear and disappear as they are plugged in.
"""

import json
import os
import signal
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator
from gi.repository import GLib, Gtk

APP_ID = "audio-device-tray"
ICON = "audio-headset-symbolic"
# Events worth rebuilding the menu for. Stream events (sink-input etc.) are not.
WATCHED_EVENTS = (" on sink #", " on source #", " on card #", " on server")
CONFIG_PATH = os.path.join(
    GLib.get_user_config_dir(), "audio-device-tray", "hidden.json"
)


def load_hidden():
    try:
        with open(CONFIG_PATH) as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_hidden(hidden):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(sorted(hidden), f, indent=2)


def pactl(*args):
    result = subprocess.run(
        ["pactl", *args], capture_output=True, text=True, timeout=5
    )
    return result.stdout if result.returncode == 0 else ""


def pactl_json(*args):
    try:
        return json.loads(pactl("-f", "json", *args) or "null")
    except (json.JSONDecodeError, subprocess.TimeoutExpired):
        return None


def is_unplugged(device):
    """True when the device's active port reports nothing is plugged in."""
    ports = device.get("ports") or []
    active = device.get("active_port")
    for port in ports:
        if port.get("name") == active:
            return port.get("availability") == "not available"
    return bool(ports) and all(
        p.get("availability") == "not available" for p in ports
    )


def load_devices(kind):
    """Return [(name, label, unplugged)] for 'sinks' or 'sources'."""
    devices = pactl_json("list", kind) or []
    if kind == "sources":
        devices = [d for d in devices if d.get("monitor_source") in (None, "")
                   and not d.get("name", "").endswith(".monitor")]

    # Identical cards produce identical descriptions; number the repeats.
    totals, seen, out = {}, {}, []
    for d in devices:
        desc = d.get("description") or d.get("name", "?")
        totals[desc] = totals.get(desc, 0) + 1
    for d in devices:
        desc = d.get("description") or d.get("name", "?")
        label = desc
        if totals[desc] > 1:
            seen[desc] = seen.get(desc, 0) + 1
            label = f"{desc} #{seen[desc]}"
        out.append((d["name"], label, is_unplugged(d)))
    return out


class AudioTray:
    def __init__(self):
        self.indicator = AppIndicator.Indicator.new(
            APP_ID, ICON, AppIndicator.IndicatorCategory.HARDWARE
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("Audio devices")
        self.rebuild_pending = 0
        self.hidden = load_hidden()
        self.rebuild()
        self.start_subscription()

    # --- menu -------------------------------------------------------------

    def rebuild(self):
        self.rebuild_pending = 0
        info = pactl_json("info") or {}
        menu = Gtk.Menu()

        # The panel is at the bottom, so the menu's last entries are the
        # shortest reach: rarely used items go first, outputs go last.
        manage = Gtk.Menu()
        manage_item = Gtk.MenuItem(label="Show / hide devices")
        manage_item.set_submenu(manage)
        menu.append(manage_item)
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_: Gtk.main_quit())
        menu.append(quit_item)
        menu.append(Gtk.SeparatorMenuItem())

        self.add_section(
            menu, manage, "Input", "sources", info.get("default_source_name"),
            self.set_source,
        )
        menu.append(Gtk.SeparatorMenuItem())
        manage.append(Gtk.SeparatorMenuItem())
        current_out = self.add_section(
            menu, manage, "Output", "sinks", info.get("default_sink_name"),
            self.set_sink,
        )

        menu.show_all()
        self.indicator.set_menu(menu)
        self.indicator.set_title(
            f"Audio: {current_out}" if current_out else "Audio devices"
        )
        return False

    def add_section(self, menu, manage, title, kind, default_name, callback):
        for target in (menu, manage):
            header = Gtk.MenuItem(label=title)
            header.set_sensitive(False)
            target.append(header)

        devices = load_devices(kind)
        group, current_label, shown = None, None, 0
        for name, label, unplugged in devices:
            is_default = name == default_name
            if is_default:
                current_label = label

            # Every device gets a tick box in the manage submenu.
            toggle = Gtk.CheckMenuItem(
                label=f"{label} (unplugged)" if unplugged else label
            )
            toggle.set_active(name not in self.hidden)
            toggle.connect("toggled", self.on_toggle_hidden, name)
            manage.append(toggle)

            # The main list only has devices that can actually be used:
            # not hidden by the user and not an empty jack. The current
            # default is always listed so the menu never lies about it.
            if (unplugged or name in self.hidden) and not is_default:
                continue
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group, label)
            group = group or item
            item.set_active(is_default)
            item.connect("activate", self.on_pick, callback, name)
            menu.append(item)
            shown += 1

        if not shown:
            empty = Gtk.MenuItem(label="  (none available)")
            empty.set_sensitive(False)
            menu.append(empty)
        return current_label

    def on_toggle_hidden(self, item, name):
        if item.get_active():
            self.hidden.discard(name)
        else:
            self.hidden.add(name)
        save_hidden(self.hidden)
        self.schedule_rebuild()

    def on_pick(self, item, callback, name):
        # Radio items also fire "activate" when they get deselected.
        if item.get_active():
            callback(name)
            self.schedule_rebuild()

    # --- actions ----------------------------------------------------------

    def set_sink(self, name):
        pactl("set-default-sink", name)
        # Carry over anything already playing.
        for line in pactl("list", "short", "sink-inputs").splitlines():
            stream_id = line.split("\t", 1)[0]
            if stream_id.isdigit():
                pactl("move-sink-input", stream_id, name)

    def set_source(self, name):
        # Recording streams are left alone: some are deliberately capturing a
        # monitor (screen recorders, meters) and should not be moved to a mic.
        pactl("set-default-source", name)

    # --- live updates -----------------------------------------------------

    def schedule_rebuild(self):
        if not self.rebuild_pending:
            self.rebuild_pending = GLib.timeout_add(300, self.rebuild)

    def start_subscription(self):
        try:
            proc = subprocess.Popen(
                ["pactl", "subscribe"], stdout=subprocess.PIPE, text=True
            )
        except OSError:
            GLib.timeout_add_seconds(5, self.restart_subscription)
            return
        GLib.io_add_watch(
            proc.stdout,
            GLib.PRIORITY_DEFAULT,
            GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
            self.on_event,
            proc,
        )

    def restart_subscription(self):
        self.start_subscription()
        self.schedule_rebuild()
        return False

    def on_event(self, source, condition, proc):
        line = source.readline() if condition & GLib.IO_IN else ""
        if not line:
            # Audio server went away (e.g. PipeWire restart); reconnect.
            proc.kill()
            proc.wait()
            GLib.timeout_add_seconds(2, self.restart_subscription)
            return False
        if any(event in line for event in WATCHED_EVENTS):
            self.schedule_rebuild()
        return True


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    AudioTray()
    Gtk.main()


if __name__ == "__main__":
    main()
