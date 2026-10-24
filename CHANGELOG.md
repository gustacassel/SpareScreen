# Changelog

All notable changes to SpareScreen are listed here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Pairing: devices on the network type a 6-digit code once before they get any data or
  can change settings. The PC itself and phones on USB are trusted. New options
  `--no-pairing` and `--reset-pairing`.

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

[0.1.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.1.0
