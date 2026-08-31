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
        documents = VALIDATOR.split_documents(rendered)
        identities = [VALIDATOR.resource_identity(document) for document in documents]
        self.assertEqual(1, identities.count(("ConfigMap", "faang-config")))
        self.assertEqual(1, identities.count(("Ingress", "faang-ingress")))
        application_documents = [
            document for document in documents
            if VALIDATOR.resource_identity(document) != ("ConfigMap", "faang-bootstrap-scripts-v1")
        ]
        self.assertNotIn("${", "\n---\n".join(application_documents))
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


class BootstrapContractTests(unittest.TestCase):
    def render_homelab(self) -> str:
        result = subprocess.run(
            ["kubectl", "kustomize", str(ROOT / "k8s" / "overlays" / "homelab")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def test_bootstrap_is_four_versioned_ordered_jobs(self):
        rendered = self.render_homelab()
        documents = VALIDATOR.split_documents(rendered)
        jobs = {
            VALIDATOR.resource_identity(document)[1]: document
            for document in documents
            if VALIDATOR.resource_identity(document)[0] == "Job"
        }
        expected_waves = {
            "faang-bootstrap-postgres-v1": 'argocd.argoproj.io/sync-wave: "-40"',
            "faang-bootstrap-kafka-v1": 'argocd.argoproj.io/sync-wave: "-39"',
            "faang-bootstrap-elasticsearch-v1": 'argocd.argoproj.io/sync-wave: "-38"',
            "faang-bootstrap-minio-v1": 'argocd.argoproj.io/sync-wave: "-37"',
        }
        self.assertEqual(set(expected_waves), set(jobs))
        for name, wave in expected_waves.items():
            self.assertIn(wave, jobs[name])
            self.assertRegex(jobs[name], r"image:\s+[^\s]+@sha256:[0-9a-f]{64}")
            self.assertIn("automountServiceAccountToken: false", jobs[name])
            self.assertIn("serviceAccountName: faang-bootstrap", jobs[name])
        self.assertIn(
            "apache/kafka:4.3.1@sha256:77e3df9054047a88b520d0cc46e16696d3b22022e1d580aeccd2632df6532837",
            jobs["faang-bootstrap-kafka-v1"],
        )
        self.assertIn(
            "curlimages/curl:8.21.0@sha256:7c12af72ceb38b7432ab85e1a265cff6ae58e06f95539d539b654f2cfa64bb13",
            jobs["faang-bootstrap-elasticsearch-v1"],
        )

    def test_bootstrap_scripts_are_bounded_and_idempotent(self):
        scripts = ROOT / "k8s" / "bootstrap" / "scripts"
        postgres = (scripts / "init-postgres.sh").read_text(encoding="utf-8")
        kafka = (scripts / "init-kafka.sh").read_text(encoding="utf-8")
        elasticsearch = (scripts / "init-elasticsearch.sh").read_text(encoding="utf-8")
        minio = (scripts / "init-minio.sh").read_text(encoding="utf-8")
        self.assertIn("CREATE SCHEMA IF NOT EXISTS", postgres)
        self.assertIn("--if-not-exists", kafka)
        self.assertIn("--head", elasticsearch)
        self.assertIn("--ignore-existing", minio)
        for script in (postgres, kafka, elasticsearch, minio):
            self.assertIn('attempt" -ge 60', script)

    def test_legacy_local_bootstrap_paths_are_removed(self):
        for relative_path in (
            "Dockerfile.init",
            "init-postgres.sh",
            "init-kafka.sh",
            "init-elastic.sh",
            "k8s/init-job.yaml",
        ):
            self.assertFalse((ROOT / relative_path).exists(), relative_path)
        for script_name in ("deploy.ps1", "deploy.sh"):
            script = (ROOT / script_name).read_text(encoding="utf-8")
            self.assertNotIn("faang-init-utils", script)
            self.assertNotIn("k8s/init-job.yaml", script)
            self.assertNotIn("secret.yaml", script)
        setup_script = (ROOT / "setup-infra.ps1").read_text(encoding="utf-8")
        self.assertNotIn("faang-init-utils", setup_script)
        self.assertNotIn("k8s/init-job.yaml", setup_script)
        self.assertNotIn("secret.yaml", setup_script)
        self.assertNotIn("kubectl apply", setup_script)


if __name__ == "__main__":
    unittest.main()
