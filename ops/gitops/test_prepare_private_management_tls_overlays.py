import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare-private-management-tls-overlays.ps1")


class PreparePrivateManagementTlsOverlaysTests(unittest.TestCase):
    def test_preparation_is_private_only_and_refuses_ambiguous_rules(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for required in (
            "Expected exactly one homelab secrets path", "argocd-management-tls",
            "jenkins-management-tls", "Refusing to alter existing private overlay",
            "overlays/(homelab|argocd|jenkins)/secrets",
            "overlays[\\\\/](homelab|argocd|jenkins)[\\\\/]secrets",
        ):
            self.assertIn(required, source)
        for forbidden in ("kubectl", "argocd app", "sops --encrypt"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
