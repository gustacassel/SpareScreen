# SpareScreen

Free and open source tool that turns an old phone (or any device with a browser) into
a dashboard for the PC: hardware, what's running and Claude Code usage.
Vision, roadmap and research in [ROADMAP.md](ROADMAP.md); usage in [README.md](README.md).

## Main guideline: generic, never "someone's PC"

This tool is for anyone, on any PC, with any device. The developer's own PC and phone
are only test environments.

- **Nothing machine-specific in the code or the defaults.** Don't assume a motherboard
  model, header order ("Fan 1 is the CPU"), GPU brand, core count, drive letters,
  user name, local paths or the test device.
- **Discover at runtime.** Show whatever that person's system reports. If a value doesn't
  exist, hide the row or show "no data"; never make it up.
- **Customization belongs to the user, not the code.** Fan names, which fan shows on the
  CPU card, theme, screens, etc. live in each person's config
  (`~/.sparescreen/config.json`, editable from the settings screen), with neutral defaults.
- **Examples in the docs** may mention real hardware, but always as an example.

## Other principles

- **Cross-platform (Windows, Linux, macOS).** A feature that only exists on one OS must
  degrade without errors on the others and be documented in the README (what works where).
- **Any device with a browser.** The page (`sparescreen/web/`) runs on old browsers:
  minimum target Chrome 49 / iOS 10 (CSS variables, URLSearchParams, EventSource).
  No flexbox `gap`, `inset`, `aspect-ratio`, optional chaining (`?.`), `??`, `let`/`const`,
  arrow functions, template literals, ES modules or other recent syntax.
  Test in portrait and landscape (360x640).
- **Free and open.** Only free, open dependencies; nothing that requires an account or payment.
- **Local and private.** Data stays on the local network; nothing is sent elsewhere.
- **Third-party internal formats** (e.g. Claude Code's files) are read defensively:
  missing fields must never crash the agent.
- **English everywhere:** code, comments, messages, interface and docs.

## Development

- `sparescreen --dev`: restarts the agent when a `.py` file changes and reloads the page.
- Follow the existing style: short, practical comments that explain the "why".
