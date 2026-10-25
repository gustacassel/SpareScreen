"""Entry point: python -m sparescreen (the code lives in cli.py, which PyInstaller can bundle)."""

import sys

from .cli import main

sys.exit(main())
