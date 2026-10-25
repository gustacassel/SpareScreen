# Changelog

All notable changes to SpareScreen are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Game art, icons and names beyond Steam: Xbox / Game Pass (splash screen, logo and name
  from the game's MicrosoftGame.config), GOG (the game's own .ico and name), Epic (display
  name from the launcher's manifests), and the window icon for "your games".

### Changed

- The "Disconnected" screen is redone: truly centered on any screen (it could end up in a
  corner on larger phones), black, with a big clock so it stays useful while waiting.
- Under the hood: the dashboard script is split into one file per part (`web/app/`), and
  game detection moved into its own module (`games.py`).
- The Python code is fully typed and checked with mypy in CI (Windows, Linux and macOS
  code paths); shared data shapes in `sparescreen/shapes.py`.

### Fixed

- The SpareScreen window failed in `--demo` mode (its Games tab needed things the demo
  didn't have).

## [0.10.0] - 2026-10-25

### Added

- Credits in the README: every project SpareScreen uses or talks to, with links and licenses.
- Heat alerts: temperatures turn yellow and red relative to each part's own limit (NVIDIA
  through `nvidia-smi`, Intel's TjMax, NVMe warning temperature, Linux hwmon "high", a
  table by family for AMD CPUs), and a part that stays in the red for 30 s raises an alert
  with a chime (setting: Heat alerts).
- Phone screen over USB (setting, off by default): while the PC is locked, or at night
  with night mode on, dim the phone's real brightness or turn its screen off, and put it
  back afterwards (also when SpareScreen closes).

### Changed

- `--demo` keeps its own settings and paired devices (`~/.sparescreen/demo`) instead of
  changing yours.
- The version lives only in `sparescreen/__init__.py`; `packaging/bump.py` starts a release.

## [0.9.0] - 2026-10-25

### Added

- Your games: mark any running program as a game in the SpareScreen window ("It's a
  game"), for games installed outside the store folders, emulators, Minecraft Java...
  And "Not a game" for anything taken for a game by mistake.
- Automatic game detection where FPS is set up (Windows): the full-screen app in front
  counts as a game when PresentMon sees it drawing steadily for a few seconds. It stays
  a game while it runs (also in the background) and shows its window's icon (e.g.
  Minecraft's block instead of Java's cup).

### Changed

- The SpareScreen window has tabs (Phone, Games, Status) instead of one long page, with a
  dot on a tab that needs attention; it jumps to Phone when a device asks to pair.

### Fixed

- Game FPS never showed: PresentMon only writes frame rows to a file (to a pipe it writes
  the header and stops), and `--no_track_display` made it write nothing. It now records
  2-second stretches to a file, read as each one ends (FPS updates every ~2 s).
- Some program names came out with garbage after them (e.g. "NVIDIA App"), from reading
  the .exe description past its end.

## [0.8.0] - 2026-10-25

### Added

- Game FPS on Windows: current FPS, 1% low and frame time over the game art. Turned on
  from the SpareScreen window, which downloads Intel's PresentMon (pinned version,
  checksum verified) and asks Windows once to add the user to "Performance Log Users";
  SpareScreen then runs PresentMon only while a game is open.

## [0.7.0] - 2026-10-25

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

[0.10.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.10.0
[0.9.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.9.0
[0.8.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.8.0
[0.7.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.7.0
[0.6.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.6.0
[0.5.1]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.5.1
[0.5.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.5.0
[0.4.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.4.0
[0.3.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.3.0
[0.2.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.2.0
[0.1.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.1.0
