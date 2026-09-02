import re
import unittest
from pathlib import Path


class ControllerHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.values = (
            Path(__file__).resolve().parents[1] / "values" / "controller-hardening.yaml"
        ).read_text(encoding="utf-8")

    def test_shared_library_uses_current_git_source_symbol(self) -> None:
        self.assertRegex(
            self.values,
            re.compile(r"^\s+modernSCM:\s*$\n^\s+scm:\s*$\n^\s+gitSource:\s*$", re.MULTILINE),
        )
        self.assertNotRegex(self.values, re.compile(r"^\s+git:\s*$", re.MULTILINE))

    def test_exact_plugin_lock_remains_unchanged(self) -> None:
        plugin_block = self.values.split("installPlugins:", 1)[1].split("JCasC:", 1)[0]
        pinned_plugins = re.findall(r"^\s+- [a-z0-9-]+:\S+\s*$", plugin_block, re.MULTILINE)
        self.assertEqual(74, len(pinned_plugins))


if __name__ == "__main__":
    unittest.main()
