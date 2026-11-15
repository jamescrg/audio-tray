# audio-tray

A small system tray widget for Linux that switches the default audio output
and input device. Works with PipeWire or PulseAudio through `pactl`.

- Pick an output and anything already playing moves to it.
- Pick an input to change the default microphone.
- Jacks with nothing plugged in are hidden automatically.
- Hide devices you never use from the "Show / hide devices" submenu.
- The list updates as devices are plugged in and removed.

## Install

```sh
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 pulseaudio-utils
git clone https://github.com/jamescrg/audio-tray.git && cd audio-tray
./install.sh
```

`install.sh` adds a login autostart entry pointing at this folder and starts
the widget. To run it without installing: `./audio-tray.py`.

## Notes

- Hidden devices are stored per machine in
  `~/.config/audio-device-tray/hidden.json`.
- The menu puts outputs last, which is the shortest reach from a bottom panel.
- Built on Cinnamon; it should work on any desktop whose tray supports
  AppIndicator/StatusNotifier icons.
