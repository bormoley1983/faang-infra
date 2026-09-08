import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("stage-private-tls-secret.ps1")


class StagePrivateTlsSecretTests(unittest.TestCase):
    def test_stager_uses_ephemeral_key_material_and_sops_only(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for required in (
            "Read-Host 'PFX password' -AsSecureString", "EphemeralKeySet", "Exportable",
            "kubernetes.io/tls", "--encrypt", "--config", ".sops.yaml", "--output",
            ".faang-tls-", ".sops.yaml')", "Remove-Item -LiteralPath $plainTempPath",
            "Refusing to overwrite an existing encrypted Secret.",
            "Output path must be relative to the private environment root.",
        ):
            self.assertIn(required, source)
        for forbidden in ("kubectl", "argocd", "WriteAllText($outputPath, $plainYaml"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
