"""Guards for the page: old-browser rules and element ids used by the script."""

import re
import unittest
from pathlib import Path

WEB = Path(__file__).parent.parent / "sparescreen" / "web"


def _without_comments(code):
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"(^|[^:\\])//.*", r"\1", code)


class OldBrowserRulesTest(unittest.TestCase):
    """The page must run on old phones (Chrome 49 / iOS 10): no modern syntax."""

    def test_javascript(self):
        code = _without_comments((WEB / "app.js").read_text(encoding="utf-8"))
        forbidden = {
            "arrow function": r"=>",
            "template literal": r"`",
            "let/const": r"(^|[;{(\s])(let|const)\s",
            "optional chaining": r"\?\.[\w(\[]",
            "nullish coalescing": r"\?\?",
            "class syntax": r"(^|\s)class\s+\w+\s*[{e]",
            "async/await": r"\basync\s+function|\bawait\s",
        }
        for rule, pattern in forbidden.items():
            match = re.search(pattern, code, flags=re.M)
            self.assertIsNone(match, f"{rule} found: {match and match.group(0)!r}")

    def test_css(self):
        css = _without_comments((WEB / "style.css").read_text(encoding="utf-8"))
        for rule, pattern in {
            "flexbox/grid gap": r"(^|[;{\s])gap\s*:",
            "inset": r"(^|[;{\s])inset\s*:",
            "aspect-ratio": r"aspect-ratio\s*:",
            "CSS grid": r"display\s*:\s*grid",
        }.items():
            match = re.search(pattern, css, flags=re.M)
            self.assertIsNone(match, f"{rule} found: {match and match.group(0)!r}")


class ElementIdsTest(unittest.TestCase):
    def test_every_id_used_by_the_script_exists(self):
        html = (WEB / "app.html").read_text(encoding="utf-8")
        js = (WEB / "app.js").read_text(encoding="utf-8")
        ids = set(re.findall(r'id="([\w-]+)"', html))
        used = set(re.findall(r'\$\("([\w-]+)"\)', js))
        self.assertTrue(used)
        self.assertEqual(used - ids, set())


if __name__ == "__main__":
    unittest.main()
