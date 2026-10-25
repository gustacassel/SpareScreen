# SpareScreen roadmap

Use an old phone (or any device with a browser), connected to the computer over USB or
Wi-Fi, as a programmable side display: Claude Code usage, CPU/GPU usage and
temperature, photos, scrolling text, a clock, and so on.

**Goals:** run on any OS (Windows, Linux, macOS), be free and open source, work with
any phone or device, and be **generic**: nothing tied to the developer's own PC or
phone (see the guideline in [CLAUDE.md](CLAUDE.md)).

## Prior art (researched on 2026-10-24)

| Project | What it does | Why it doesn't cover everything |
|---|---|---|
| Remote System Monitor (Trigone) | Android app + PC server showing sensors over Wi-Fi | Windows-only server, closed source, ads; hardware only |
| AIDA64 RemoteSensor / Remote Panel | AIDA64 serves a sensor page; the phone opens it in a browser or an app over ADB | Paid, Windows only, hardware only |
| HWMonitor PRO (CPUID) | Monitors machines over the network, including on Android | Paid, hardware focused |
| zvocrljen/HWMonitor (GitHub) | Android app + PC service using OpenHardwareMonitor, USB or Wi-Fi | Windows only, hardware only |
| turing-smart-screen-python | Themed system monitor for cheap USB screens (Turing/XuanFang) | Cross-platform, but for specific hardware, not phones. Good theme reference |
| Clawdmeter, ClaudeGauge, TokenMonitor | Show Claude Code usage on ESP32 boards with a screen | Require buying/building hardware |
| Dashkiosk, kiFOSSk, Fully Kiosk | Full-screen (kiosk) browsers for Android | Only display a page; collect nothing from the PC |
| spacedesk, Duet, linux-second-screen | Phone as a second monitor (desktop extension) | Different idea: mirrors/extends the desktop, not a widget dashboard |

**Conclusion:** the pieces exist separately, but there was no open, cross-platform tool
combining generic widgets (hardware + Claude + photos + text) on an old phone, over USB
and with no mandatory app. That's this project's niche.

## Architecture

```
 PC (Windows/Linux/macOS)                         Old phone / any browser
 ┌──────────────────────────────┐                 ┌─────────────────────┐
 │ agent                         │  HTTP +         │ full-screen browser │
 │  ├─ data sources              │  Server-Sent    │ (or a tiny kiosk    │
 │  │   hardware, claude, apps   │  Events         │ app later)          │
 │  ├─ config (~/.sparescreen)   │ ──────────────► │                     │
 │  └─ web server + page         │  USB: adb       │ renders the screens │
 │                               │  reverse        │                     │
 │                               │  Wi-Fi: IP:port │                     │
 └──────────────────────────────┘                 └─────────────────────┘
```

- **Agent on the PC:** collects data and serves the page. Pushes updates through
  Server-Sent Events (PC → phone only, no extra dependency); settings changes go back
  with a simple POST.
- **Phone:** no app needed. It just opens the page in the browser.
  - **USB:** the agent runs `adb reverse tcp:PORT tcp:PORT` and the phone opens
    `http://localhost:PORT`. Works the same on all three OSes, no root. Bonus:
    `localhost` is a secure context, so the Wake Lock API works on newer browsers.
  - **Wi-Fi:** open `http://PC-IP:PORT`. To keep the screen on, use the phone's
    "Stay awake" developer option while charging.

## Old devices

- Minimum target for the page: Chrome 49 / iOS 10 (browsers from ~2016 onward).
- Current test device: Galaxy J5 Prime (Android 8.0, browser older than Chrome 84: no
  flexbox `gap`, no Wake Lock). It's a test device, not the target.
- Consequence: conservative HTML/CSS/JS and testing in portrait and landscape.

## Done so far

- Agent serving the page; CPU/RAM and clock; Wi-Fi.
- Automatic USB with `adb reverse` (detects the phone, sets it up, opens the page).
  Built, but not yet tested on a real phone (needs a micro-USB data cable).
- Three screens that rotate on their own or with a tap: Hardware, Claude, PC.
- Temperatures: NVIDIA via `nvidia-smi`; CPU, fans, drives and AMD/Intel GPUs via
  LibreHardwareMonitor on Windows; hwmon and `amdgpu` on Linux.
- Claude Code: 5-hour and weekly limits through the status line (terminal sessions
  only), tokens today and this week, open sessions, alert when a session finishes.
- Component names, icons, 6 themes (long press switches), settings screen saved on the PC.
- PC screen: running game, app in focus, top apps, fans, network and disks.
- User-defined fan names and CPU-card fan, CPU/GPU clocks, per-core grid.
- `--dev` mode: restarts the agent and reloads the page, without leaving full screen.
- MIT license, public repository, everything in English.
- Pairing: a 6-digit code for new devices on the network; the PC and USB are trusted.
- AI screen: one card per installed tool (Claude Code, Codex), with limits, tokens and
  sessions; Codex limits come straight from its session files.
- Claude Code limits for desktop/IDE users: optional headless check (`claude -p`) every
  10 minutes while Claude Code is in use.

## Gaps, by priority

1. ✅ **Local network security.** Devices must pair with a 6-digit code before they
   get any data or can change settings (done after 0.1.0).
2. **Install for non-programmers.** Today it needs Python + venv. Idea: one executable
   per OS (PyInstaller) and start with the system.
3. **Generic AI data.** ✅ "Tokens this week per model" replaced the Fable-only row, and
   the AI screen shows Claude Code and Codex. Still to do: a status line that coexists
   with one the user already has; more tools that keep local data (e.g. Gemini CLI).
4. **Complete macOS and Linux.** Temperature/fans on macOS; "app in focus" on Linux;
   Intel GPUs on Linux.
5. **Translations.** The interface is English only; maybe add other languages later.
6. **Test real devices:** iPhone/iPad over Wi-Fi, very old Android, tablets; USB with a
   data cable; AMD and Intel GPUs on real machines.
7. **More widgets:** photos and scrolling text (the original idea), history charts, FPS.
   - **Now playing:** whatever the PC is playing (Spotify, YouTube, any player), not tied
     to one app: Windows' media controls (the ones in the volume flyout), MPRIS on Linux,
     the Now Playing info on macOS.
8. Optional: a tiny Android app (WebView kiosk, minSdk 23) that opens by itself, full
   screen, screen always on.

## To think about

- **Screen burn-in.** A dashboard showing the same thing in the same place for hours can
  burn in the screen, like the "always on display" complaints on phones. It's a real
  risk on **AMOLED/OLED** screens (many older Samsung phones); on **LCD** the risk is
  lower (at most temporary image retention), but the backlight ages too.
  Ideas:
  - Shift the content a few pixels every now and then (pixel shift), invisible to the viewer.
  - Screen rotation already helps; avoid bright fixed elements (top bar, titles).
  - Dark theme by default on OLED, lower brightness and a "night mode" that turns the
    screen off or only shows a clock that moves around.
  - Dim or turn off when the PC is idle or locked.
  - A setting to turn this on/off, since it depends on the screen type.

## Decisions

- Agent language: Python (psutil, quick to build, cross-platform).
- Name: SpareScreen.
- License: MIT.
- Distribution: GitHub only (clone and run); not published on PyPI for now.
- Language: English everywhere (code, docs and interface) for wider reach.

## Sources

- https://www.pcgamesn.com/android/remote-system-monitor
- https://www.tomsguide.com/computing/i-turned-an-old-phone-into-a-system-monitor-for-my-computer-and-the-results-blew-me-away
- https://forum.manjaro.org/t/remote-system-monitor-trigone-pitikapp-remote-dashboard-for-manjaro-android-temps-and-stats-dashboard/143613
- https://forums.aida64.com/topic/2636-remotesensor-lcd-for-smartphones-and-tablets/
- https://forums.aida64.com/topic/2776-display-pc-sensor-values-on-android-device-connected-via-usb-odospace-remote-panel/page/4
- https://cpuid.com/softwares/hwmonitor-pro-android.html
- https://github.com/zvocrljen/HWMonitor
- https://github.com/mathoudebine/turing-smart-screen-python
- https://www.cnx-software.com/2026/05/14/clawdmeter-a-diy-esp32-s3-desk-dashboard-for-claude-code-token-usage-monitoring/
- https://www.hackster.io/dorofino/claudegauge-real-time-ai-usage-monitor-on-esp32-s3-with-a-a82d4b
- https://www.cnx-software.com/2026/08/07/token-monitor-an-esp32-s3-desktop-display-that-tracks-ai-coding-assistant-usage/
- https://dashkiosk.readthedocs.io/en/v2.5.0/android.html
- https://f-droid.org/en/packages/com.shinydiscoballsdev.kifossk/
- https://gittrend.io/repo/brunodles/linux-second-screen
- https://blog.grio.com/2015/07/android-tip-adb-reverse.html
- https://en.wikipedia.org/wiki/Samsung_Galaxy_J5_Prime
- https://9to5google.com/2025/06/26/google-chrome-android-versions-no-longer-supported-2025/
