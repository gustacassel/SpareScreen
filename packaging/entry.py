"""PyInstaller entry point: the packaged app runs the same main() as `python -m sparescreen`.

Build (see .github/workflows/release.yml):
    pyinstaller --onefile --name sparescreen --add-data "sparescreen/web<sep>sparescreen/web" \
        --icon assets/icon.ico packaging/entry.py
where <sep> is ";" on Windows and ":" elsewhere.
"""

from __future__ import annotations

import sys

from sparescreen.cli import main

sys.exit(main())
