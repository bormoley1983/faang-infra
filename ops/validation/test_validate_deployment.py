import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("validate_deployment.py")
SPEC = importlib.util.spec_from_file_location("validate_deployment", MODULE_PATH)
VALIDATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)
FIXTURES = Path(__file__).with_name("fixtures")
ROOT = MODULE_PATH.parents[2]


class DeploymentPolicyTests(unittest.TestCase):
    def issues_for(self, fixture: str):
        rendered = (FIXTURES / fixture).read_text(encoding="utf-8")
        return VALIDATOR.validate_rendered(rendered, {})

    def assert_has_code(self, fixture: str, code: str):
        issues = self.issues_for(fixture)
        self.assertIn(code, {issue.code for issue in issues}, [issue.fingerprint for issue in issues])

    def test_unresolved_token_is_rejected(self):
        self.assert_has_code("unresolved-token.yaml", "POL001")

    def test_mutable_image_is_rejected(self):
        self.assert_has_code("mutable-image.yaml", "POL002")

    def test_missing_reference_is_rejected(self):
        self.assert_has_code("missing-reference.yaml", "REF002")

    def test_persistent_emptydir_is_rejected(self):
        self.assert_has_code("persistent-emptydir.yaml", "POL003")

    def test_plaintext_secret_is_rejected(self):
        fixture = FIXTURES / "plaintext-secret.yaml"
        issues = VALIDATOR.validate_source_text(Path("secret.yaml"), fixture.read_text(encoding="utf-8"))
        self.assertIn("SEC001", {issue.code for issue in issues})

    def test_missing_required_environment_is_rejected(self):
        rendered = (FIXTURES / "mutable-image.yaml").read_text(encoding="utf-8")
        contracts = {"services": {"broken-image": {"containerPort": 8080, "requiredEnv": ["REQUIRED_VALUE"]}}}
        issues = VALIDATOR.validate_rendered(rendered, contracts)
        codes = {issue.code for issue in issues}
        self.assertIn("CON002", codes)
        self.assertIn("CON003", codes)
        self.assertIn("CON004", codes)


class ConfigurationOwnershipTests(unittest.TestCase):
    def render(self, path: Path) -> str:
        result = subprocess.run(
            ["kubectl", "kustomize", str(path)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def test_base_has_only_portable_configuration(self):
        rendered = self.render(ROOT / "k8s" / "base")
        forbidden = (
            "office.aviv.com.ua",
            "postgres-main",
            "redis-main",
            "kafka-main",
            "elasticsearch-main",
            "minio-main",
            "smtp.gmail.com",
            "${",
        )
        for value in forbidden:
            self.assertNotIn(value, rendered)

    def test_homelab_has_one_configmap_and_all_ingress_hosts(self):
        rendered = self.render(ROOT / "k8s" / "overlays" / "homelab")
        identities = [VALIDATOR.resource_identity(document) for document in VALIDATOR.split_documents(rendered)]
        self.assertEqual(1, identities.count(("ConfigMap", "faang-config")))
        self.assertEqual(1, identities.count(("Ingress", "faang-ingress")))
        self.assertNotIn("${", rendered)
        services = (
            "account",
            "achievement",
            "analytics",
            "notification",
            "payment",
            "post",
            "project",
            "url-shortener",
            "user",
        )
        for service in services:
            self.assertIn(f"host: faang-{service}.office.aviv.com.ua", rendered)

    def test_manual_scripts_apply_the_argocd_overlay_without_substitution(self):
        for script_name in ("deploy.ps1", "deploy.sh"):
            script = (ROOT / script_name).read_text(encoding="utf-8")
            self.assertIn("kubectl apply -k k8s/overlays/homelab", script)
            self.assertNotIn("BASE_DOMAIN", script)


if __name__ == "__main__":
    unittest.main()
