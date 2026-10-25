"""Starts a release: sets the new version and dates the changelog's "Unreleased" entry.

    python packaging/bump.py 0.10.0

The version lives only in sparescreen/__init__.py (pyproject.toml reads it from there).
Then commit, push and publish the GitHub release (tag v0.10.0); the release workflow
builds and attaches the executables.
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/gustacassel/SpareScreen"


def bump(version: str, today: str | None = None, root: Path = ROOT) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Not a version like 1.2.3: {version}")
    init = root / "sparescreen" / "__init__.py"
    init.write_text(re.sub(r'__version__ = "[^"]*"', f'__version__ = "{version}"',
                           init.read_text(encoding="utf-8")), encoding="utf-8")

    changelog = root / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    if "## [Unreleased]" not in text:
        raise ValueError('CHANGELOG.md has no "## [Unreleased]" entry to release.')
    today = today or datetime.date.today().isoformat()
    text = text.replace("## [Unreleased]", f"## [{version}] - {today}", 1)
    # The links at the bottom: newest first.
    link = f"[{version}]: {REPO}/releases/tag/v{version}\n"
    text = re.sub(r"^\[\d+\.\d+\.\d+\]: ", lambda match: link + match.group(0), text, count=1, flags=re.M)
    changelog.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    bump(sys.argv[1])
    print(f"Version {sys.argv[1]}: commit, push, then publish the release v{sys.argv[1]}.")
