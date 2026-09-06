import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "ops" / "argocd" / "secrets-project.yaml"
APPLICATION = ROOT / "ops" / "argocd" / "secrets-application.yaml"


class SecretDeliveryContractTests(unittest.TestCase):
    def test_project_is_private_repo_and_secret_only(self):
        text = PROJECT.read_text(encoding="utf-8")
        self.assertIn("name: faang-secrets", text)
        self.assertIn("https://github.com/bormoley1983/faang-infra-env-homelab.git", text)
        self.assertIn("namespace: faang", text)
        self.assertIn("kind: Secret", text)
        self.assertIn("clusterResourceWhitelist: []", text)
        self.assertNotIn("kind: '*'", text)

    def test_application_is_manual_private_overlay(self):
        text = APPLICATION.read_text(encoding="utf-8")
        self.assertIn("project: faang-secrets", text)
        self.assertIn("targetRevision: main", text)
        self.assertIn("path: overlays/homelab", text)
        self.assertIn("name: ksops-v1", text)
        self.assertIn("namespace: faang", text)
        self.assertIn("CreateNamespace=false", text)
        self.assertIn("ServerSideApply=true", text)
        self.assertNotIn("automated:", text)
        self.assertNotIn("prune:", text)
