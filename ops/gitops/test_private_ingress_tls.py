import unittest
from pathlib import Path


RUNBOOK = Path(__file__).with_name("private-ingress-tls.md")


class PrivateIngressTlsRunbookTests(unittest.TestCase):
    def test_wildcard_scope_and_private_source_boundaries_are_explicit(self):
        source = RUNBOOK.read_text(encoding="utf-8")
        for required in (
            "*.faang.<internal-zone>", "`argo.<internal-zone>`", "does not** cover",
            "kubernetes.io/tls", "SOPS/age", "namespace-scoped",
            "Automated sync, prune, self-heal, force, and replace",
            "do not patch their `repoURL` or `targetRevision` live",
        ):
            self.assertIn(required, source)
        for forbidden in ("office.aviv.com.ua", "homelab.local"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
