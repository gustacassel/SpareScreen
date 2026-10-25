# Changelog

All notable changes to SpareScreen are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- "Disconnected" screen: after 30 seconds without data the dashboard says so (with the
  time of the last data) instead of showing old numbers; it goes away when data returns.
- The PC's name instead of its IP: opened by IP, the page tests the PC's names from the
  phone (`name.local` over mDNS, `name` through the router) and moves to the first that
  works, keeping the pairing, so it survives the router changing the PC's IP. The
  SpareScreen window shows the address that worked.

### Fixed

- Quitting SpareScreen from the tray also closes the SpareScreen window.
- The app icon (the .exe, the tray and the iPhone home screen) was drawn wrong: the dark
  tile showed up small in a corner. Icons are now rendered from the logo by
  `packaging/make_icons.py`, with a multi-size .ico for Windows.

## [0.6.0] - 2026-10-25

### Added

- The SpareScreen window on the PC: phone address and pairing code (big, when a new
  device asks to pair), connected devices (USB phones with battery, the paired Wi-Fi
  device, open dashboards) and checks with fixes: install or open LibreHardwareMonitor
  (turning on its web server), install adb, GPU, Wi-Fi, AI tools, now playing. Opens as an
  app window (Edge/Chrome) when SpareScreen starts and from the tray icon.

### Changed

- One paired Wi-Fi device at a time: pairing a new one disconnects the previous one.
- LibreHardwareMonitor's port is read from its settings instead of assuming 8085.

### Security

- Requests sent by other websites through the PC's browser (POSTs with a foreign
  Origin) and pages reached under another hostname (DNS rebinding) are refused.

## [0.5.1] - 2026-10-24

### Changed

- Game screen: the GPU card shows the fan speed; without store art, the game's icon
  fills the art area (icons are now extracted at 256 px).
- Without LibreHardwareMonitor on Windows, the CPU cards say what to do instead of
  "no temperature sensor": open it, or turn on its web server when it's open.

### Fixed

- Game art with newer Steam versions, which keep the library images in hashed folders.

## [0.5.0] - 2026-10-24

### Added

- Tray icon: double-clicking the Windows executable runs SpareScreen in the background
  with an icon next to the clock (open the dashboard, phone address and pairing code,
  Start with Windows, Quit) instead of a console window that had to stay open. Also in
  `--background` mode (autostart); on Linux/macOS when `pystray` is installed.

### Changed

- The PC screen no longer repeats the game and now playing while they have their own
  screens (game mode on, Music screen on).
- Bigger player name and icon on the Music screen.
- Top apps shows 6 programs instead of 4.
- `--demo` has an album cover and game art (original drawings), and its game comes and
  goes so game mode can be seen.
- Devices set to reduce motion get no animations.

### Fixed

- Starting at login with the Windows executable no longer leaves a console window open.

## [0.4.0] - 2026-10-24

### Added

- Music screen: album cover, title, artist, album, the player and its icon, and the
  progress. It joins the rotation only while something plays. Covers come from the PC
  (Windows media controls, local MPRIS art on Linux, `media-control` on macOS), never
  from the internet.
- Game mode (on by default, in the settings): while a game runs, only a Game screen shows,
  with the game's art (Steam's own library cache), its icon (Windows), the play time and
  GPU/CPU usage, temperature, clock and power, VRAM and RAM.
- Screens added in a new version start on, even with an older saved config.

## [0.3.0] - 2026-10-24

### Added

- Downloadable executables for Windows, Linux and macOS (Apple Silicon), built with
  PyInstaller and attached to every release. No Python needed.
- Start with the PC: `--autostart on|off|status` (Windows Run entry, Linux XDG autostart,
  macOS LaunchAgent; no admin rights) and `--background` (no window, output to
  `~/.sparescreen/sparescreen.log`).
- Settings opened on the PC show the phone address, the pairing code and the version.
- Now playing on the PC screen: title, artist, player and progress from the system's media
  session (Windows media controls, MPRIS on Linux, `media-control`/`nowplaying-cli` on macOS).
- Burn-in protection (the page shifts a few pixels every minute, on by default) and night
  mode (dim, or a wandering clock only, during chosen hours; a tap wakes the dashboard).
- The status line can wrap an existing one: `sparescreen-statusline -- your command`
  (or `SPARESCREEN_STATUSLINE_CMD`), keeping its output while still capturing the limits.
- "In focus" on Linux (X11 via xdotool/xprop, Sway, Hyprland) and macOS (`lsappinfo`).
- CPU temperature on macOS when `smctemp`, `macmon` or `osx-cpu-temp` is installed.
- `--version`, and `sparescreen statusline` as a subcommand (used by the executables).

### Changed

- The command line moved to `sparescreen/cli.py` so it can be bundled; `python -m sparescreen`
  and the `sparescreen` command work as before.
- A busy port now gives a clear message (SpareScreen may already be running).
- Desktops without a battery no longer show a "100%" phone battery.

## [0.2.0] - 2026-10-24

### Added

- Pairing: devices on the network type a 6-digit code once before they get any data or
  can change settings. The PC itself and phones on USB are trusted. New options
  `--no-pairing` and `--reset-pairing`.
- AI screen (formerly "Claude"): one card per AI coding tool installed on the PC.
  Codex CLI support: sessions, tokens and its 5-hour and weekly usage limits, read from
  `~/.codex/sessions`. Saved settings that used the old `claude` screen name keep working.
- Claude Code limits without the terminal: *Settings > Check Claude limits* runs a tiny
  headless `claude -p` request every 10 minutes while Claude Code is in use and reads the
  `rate_limit_event` it reports. Works with the desktop app and IDEs. Off by default.
- Model-specific weekly limits (e.g. "Week · Opus") are shown when Claude Code reports them.
- Phone battery in the top bar: level and temperature over USB (via `adb`), level only over
  Wi-Fi. Turns yellow from 38 °C; from 42 °C or an Android "overheat" report it turns red
  and shows a "Phone battery is hot" alert.

### Changed

- "Fable · week" became "This week" tokens per model, for every tool.

## [0.1.0] - 2026-10-24

First public version.

### Added

- Python agent for Windows, Linux and macOS that serves a dashboard page to any device
  with a browser, over Wi-Fi or USB (`adb reverse`, Android).
- **Hardware screen:** CPU and GPU usage, temperature, power and clock, per-core load,
  VRAM, RAM and swap.
- **Claude screen:** Claude Code 5-hour and weekly limits (through a status line
  command), tokens today, Fable tokens this week, open sessions and an alert with a
  chime when a session finishes.
- **PC screen:** running game, app in focus, top apps, fans, network, disk space and
  drive temperatures.
- GPUs: NVIDIA via `nvidia-smi`; NVIDIA, AMD and Intel via LibreHardwareMonitor on
  Windows; AMD via `amdgpu` on Linux.
- Settings screen on the phone (theme, screens, rotation, alerts, sound, fan names,
  fan on the CPU card), saved on the PC in `~/.sparescreen/config.json`.
- Six themes: Graphite, OLED, Terracotta, Neon, Terminal and Light.
- Works on old browsers (Chrome 49 / iOS 10 and newer).
- `--demo` mode with made-up data, and `--dev` mode that restarts the agent and reloads
  the page while developing.
- Tests (standard library `unittest`) running on GitHub Actions on Windows, Linux and macOS.

[0.6.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.6.0
[0.5.1]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.5.1
[0.5.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.5.0
[0.4.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.4.0
[0.3.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.3.0
[0.2.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.2.0
[0.1.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.1.0
