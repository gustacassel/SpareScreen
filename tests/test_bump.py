"""packaging/bump.py: the version lives in one place and the changelog entry gets dated."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("bump", ROOT / "packaging" / "bump.py")
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)


class BumpTest(unittest.TestCase):
    def test_sets_version_and_dates_the_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sparescreen").mkdir()
            (root / "sparescreen" / "__init__.py").write_text('__version__ = "0.9.0"\n', encoding="utf-8")
            (root / "CHANGELOG.md").write_text(
                "## [Unreleased]\n\n- New thing.\n\n## [0.9.0] - 2026-10-25\n\n"
                "[0.9.0]: https://example/v0.9.0\n", encoding="utf-8")
            bump.bump("0.10.0", today="2026-11-01", root=root)
            init = (root / "sparescreen" / "__init__.py").read_text(encoding="utf-8")
            changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(init, '__version__ = "0.10.0"\n')
        self.assertIn("## [0.10.0] - 2026-11-01\n\n- New thing.", changelog)
        self.assertIn("[0.10.0]: https://github.com/gustacassel/SpareScreen/releases/tag/v0.10.0\n"
                      "[0.9.0]: https://example/v0.9.0", changelog)

    def test_refuses_bad_input(self):
        with self.assertRaises(ValueError):
            bump.bump("v1.0", root=Path("."))

    def test_the_package_reads_the_same_version(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('dynamic = ["version"]', pyproject)
        self.assertIn('attr = "sparescreen.__version__"', pyproject)


if __name__ == "__main__":
    unittest.main()
