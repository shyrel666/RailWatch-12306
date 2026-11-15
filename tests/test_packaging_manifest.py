"""Every runtime module must be declared, or source installs silently miss it."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def declared_modules():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^py-modules\s*=\s*\[(.*?)^\]", text, re.MULTILINE | re.DOTALL)
    if not block:
        raise AssertionError("pyproject.toml 缺少 [tool.setuptools] py-modules")
    return re.findall(r'"([^"]+)"', block.group(1))


class PackagingManifestTests(unittest.TestCase):
    def test_py_modules_match_top_level_sources(self):
        declared = declared_modules()
        self.assertEqual(len(declared), len(set(declared)), "py-modules 存在重复项")
        sources = {path.stem for path in ROOT.glob("*.py")}
        self.assertEqual(set(declared), sources)


if __name__ == "__main__":
    unittest.main()
