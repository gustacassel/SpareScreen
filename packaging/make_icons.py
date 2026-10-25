"""Renders the app icons from assets/logo.svg (run by hand when the logo changes).

    python packaging/make_icons.py

Uses a Chromium browser (Edge or Chrome) in headless mode to draw the SVG at 512 px
with a transparent background, then Pillow to make the sizes:
- assets/icon.ico: every size Windows uses (16-256 px), for the .exe (PyInstaller --icon);
- assets/icon-256.png: README and social images;
- sparescreen/web/icon-180.png: the tray icon and the iPhone home screen icon.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sparescreen.appwindow import find_browser  # noqa: E402

ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def render(svg, size=512):
    browser = find_browser()
    if not browser:
        sys.exit("Needs Edge or Chrome to draw the SVG.")
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "icon.html"
        page.write_text(
            "<!doctype html><style>html,body{margin:0;background:transparent}"
            f"img{{display:block;width:{size}px;height:{size}px}}</style>"
            f'<img src="{svg.as_uri()}">', encoding="utf-8")
        out = Path(tmp) / "icon.png"
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--default-background-color=00000000", f"--window-size={size},{size}",
                        f"--user-data-dir={tmp}/profile", f"--screenshot={out}", page.as_uri()],
                       check=True, timeout=60, capture_output=True)
        return Image.open(out).convert("RGBA").copy()


def main():
    big = render(ROOT / "assets" / "logo.svg")
    if big.getpixel((256, 20))[3] == 0 or big.getpixel((2, 2))[3] != 0:
        sys.exit("The render looks wrong (tile missing or corners not transparent).")
    big.resize((256, 256), Image.LANCZOS).save(ROOT / "assets" / "icon-256.png", optimize=True)
    big.resize((180, 180), Image.LANCZOS).save(ROOT / "sparescreen" / "web" / "icon-180.png", optimize=True)
    big.resize((256, 256), Image.LANCZOS).save(ROOT / "assets" / "icon.ico",
                                               sizes=[(s, s) for s in ICO_SIZES])
    print("Icons written.")


if __name__ == "__main__":
    main()
