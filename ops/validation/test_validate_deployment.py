import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("validate_deployment.py")
SPEC = importlib.util.spec_from_file_location("validate_deployment", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")
VALIDATOR = importlib.util.module_from_spec(SPEC)
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

    def test_bounded_scratch_is_allowed_when_state_is_persistent(self):
        rendered = """apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: s3-main
spec:
  template:
    spec:
      volumes:
        - name: tmp
          emptyDir:
            sizeLimit: 128Mi
  volumeClaimTemplates:
    - metadata:
        name: data
"""
        issues = VALIDATOR.validate_rendered(rendered, {})
        self.assertNotIn("POL003", {issue.code for issue in issues})

    def test_plaintext_secret_is_rejected(self):
        fixture = FIXTURES / "plaintext-secret.yaml"
        issues = VALIDATOR.validate_source_text(Path("secret.yaml"), fixture.read_text(encoding="utf-8"))
        self.assertIn("SEC001", {issue.code for issue in issues})

    def test_supplied_tracked_source_list_rejects_unsafe_paths(self):
        with self.assertRaises(RuntimeError):
            VALIDATOR.validate_tracked_sources(["../secret.yaml"])

    def test_supplied_tracked_source_list_works_without_git(self):
        issues = VALIDATOR.validate_tracked_sources([
            "k8s/overlays/homelab/namespace.yaml",
            "k8s/overlays/homelab/secret.example.yaml",
        ])
        self.assertEqual([], issues)

    def test_missing_required_environment_is_rejected(self):
        rendered = (FIXTURES / "mutable-image.yaml").read_text(encoding="utf-8")
        contracts = {"services": {"broken-image": {"containerPort": 8080, "requiredEnv": ["REQUIRED_VALUE"]}}}
        issues = VALIDATOR.validate_rendered(rendered, contracts)
        codes = {issue.code for issue in issues}
        self.assertIn("CON002", codes)
        self.assertIn("CON003", codes)
        self.assertIn("CON004", codes)


class ConfigurationOwnershipTests(unittest.TestCase):
    IMAGE_DIGESTS = {
        "faang-account-service": "e798f0fe66b559eaa2a677058b495b559f9fd9f1239c8587c2b7f144ce43cbb5",
        "faang-achievement-service": "c1af5cb2a6b989cf9f8fb6637c95b67108f267bfd7ae43faee4bba1370639f5b",
        "faang-analytics-service": "cee9071971a94f44bbeaee27155118d0a0ac0e65f0c3670624528a651cb617e2",
        "faang-notification-service": "09bf7e990fca2e506052109b072a968658d2be8ed98d2daae1b9a5e659c80f8b",
        "faang-payment-service": "d82cafd7736a2f0267f285a44a20f93749a5656c29ecb331eb255cace81c5f86",
        "faang-post-service": "8c7a22a115da9ea907714a0e1b8e1294a30b2e543bf58c8a3c50f1e51bb83989",
        "faang-project-service": "285bd0c3e9699b35fa9c78b44ed3a7083c8d1d76e53908a47e406957a7b63afa",
        "faang-url-shortener-service": "342dea20b24a4a14286a2d6b54cf0472094d77d5135c0d247b3ad667e1d88ba5",
        "faang-user-service": "aa68174163ae0f5117f7be541ec04d2f3b2e4314467baedf814a7ed7a1d02d5d",
    }

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
            "home.arpa",
            "postgres-main",
            "redis-main",
            "kafka-main",
            "elasticsearch-main",
            "s3-main",
            "smtp.gmail.com",
            "${",
        )
        for value in forbidden:
            self.assertNotIn(value, rendered)

    def test_local_dependency_mapping_contract_is_safe_and_complete(self):
        example = json.loads((ROOT / "config" / "homelab.example.json").read_text(encoding="utf-8"))
        expected = {"postgresql", "redis", "elasticsearch", "kafka", "s3"}
        self.assertEqual(expected, set(example["dependencies"]))
        self.assertEqual("internal", example["dependencies"]["s3"]["mode"])
        for name, dependency in example["dependencies"].items():
            self.assertIn(dependency["mode"], {"external", "internal"})
            self.assertIn("mode", dependency["tls"])
            self.assertIn("mode", dependency["credentials"])
            if dependency["mode"] == "internal":
                self.assertNotIn("address", dependency)
                self.assertNotIn("port", dependency)
                continue
            self.assertIn(dependency["address"].split(".")[0:3], (["192", "0", "2"], ["198", "51", "100"], ["203", "0", "113"]))
            self.assertGreater(dependency["port"], 0)
            self.assertLessEqual(dependency["port"], 65535)

        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/config/homelab.local.json", gitignore)
        installer = (ROOT / "install-external-dependencies.ps1").read_text(encoding="utf-8")
        for service in ("postgres-main", "redis-main", "elasticsearch-main", "kafka-main", "s3-main"):
            self.assertIn(service, installer)
        self.assertIn('kind = "EndpointSlice"', installer)
        self.assertIn('"IgnoreExtraneous"', installer)
        self.assertIn("validate_dependency_selection.py", installer)

        external_service_ports = {
            "postgresql": ("postgres-main", "postgresql"),
            "redis": ("redis-main", "redis"),
            "elasticsearch": ("elasticsearch-main", "https"),
            "kafka": ("kafka-main", "broker"),
            "s3": ("s3-main", "api"),
        }
        for dependency, (service, port_name) in external_service_ports.items():
            self.assertIn(
                f'ConfigKey = "{dependency}"; ServiceName = "{service}"; PortName = "{port_name}"',
                installer,
            )
            service_manifest = (
                ROOT / "k8s" / "components" / "dependencies" / dependency / "external" / "service.yaml"
            ).read_text(encoding="utf-8")
            self.assertIn(f"- name: {port_name}", service_manifest)

        secret_example = (ROOT / "k8s" / "overlays" / "homelab" / "secret.example.yaml").read_text(encoding="utf-8")
        self.assertIn("namespace: faang", secret_example)

    def test_internal_s3_profile_is_persistent_pinned_and_secret_driven(self):
        rendered = self.render(ROOT / "k8s" / "components" / "dependencies" / "s3" / "internal")
        self.assertIn("kind: StatefulSet", rendered)
        self.assertIn("storageClassName: local-path", rendered)
        self.assertIn("storage: 20Gi", rendered)
        self.assertIn("chrislusf/seaweedfs:4.45@sha256:", rendered)
        self.assertIn("key: S3_ACCESS_KEY", rendered)
        self.assertIn("key: S3_SECRET_KEY", rendered)
        self.assertNotIn("value: password", rendered)

    def test_external_elasticsearch_bootstrap_has_auth_and_explicit_tls_policy(self):
        rendered = self.render(ROOT / "k8s" / "overlays" / "homelab")
        self.assertIn("ELASTICSEARCH_URL: https://elasticsearch-main:9200", rendered)
        self.assertIn('ELASTICSEARCH_TLS_INSECURE: "true"', rendered)
        self.assertIn("key: ELASTICSEARCH_USERNAME", rendered)
        self.assertIn("key: ELASTICSEARCH_PASSWORD", rendered)
        script = (ROOT / "k8s" / "bootstrap" / "scripts" / "init-elasticsearch.sh").read_text(encoding="utf-8")
        self.assertIn('--user "$ELASTICSEARCH_USERNAME:$ELASTICSEARCH_PASSWORD"', script)
        self.assertIn('true) set -- "$@" --insecure', script)

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
            self.assertIn(f"host: faang-{service}.home.arpa", rendered)

    def test_manual_scripts_apply_the_argocd_overlay_without_substitution(self):
        for script_name in ("deploy.ps1", "deploy.sh"):
            script = (ROOT / script_name).read_text(encoding="utf-8")
            self.assertIn("kubectl apply -k k8s/overlays/homelab", script)
            self.assertNotIn("BASE_DOMAIN", script)

    def test_all_application_images_render_at_verified_digests(self):
        rendered = self.render(ROOT / "k8s" / "overlays" / "homelab")
        documents = {
            VALIDATOR.resource_identity(document): document
            for document in VALIDATOR.split_documents(rendered)
        }
        for service, digest in self.IMAGE_DIGESTS.items():
            deployment = documents[("Deployment", service)]
            self.assertIn(
                f"image: docker-registry:5000/{service}@sha256:{digest}",
                deployment,
            )

    def test_changing_one_digest_changes_only_its_deployment(self):
        original = self.render(ROOT / "k8s" / "overlays" / "homelab")
        old_digest = self.IMAGE_DIGESTS["faang-account-service"]
        new_digest = "f" * 64
        temporary_root = ROOT / ".cache" / "validation-tests"
        temporary_root.mkdir(parents=True, exist_ok=True)
        test_directory = temporary_root / f"one-service-diff-{os.getpid()}"
        if test_directory.exists():
            shutil.rmtree(test_directory)
        try:
            copied_root = test_directory / "k8s"
            shutil.copytree(ROOT / "k8s", copied_root)
            kustomization = copied_root / "overlays" / "homelab" / "kustomization.yaml"
            text = kustomization.read_text(encoding="utf-8")
            self.assertEqual(1, text.count(old_digest))
            kustomization.write_text(text.replace(old_digest, new_digest), encoding="utf-8")
            changed = self.render(copied_root / "overlays" / "homelab")
        finally:
            if test_directory.exists():
                shutil.rmtree(test_directory)

        original_documents = {
            VALIDATOR.resource_identity(document): document
            for document in VALIDATOR.split_documents(original)
        }
        changed_documents = {
            VALIDATOR.resource_identity(document): document
            for document in VALIDATOR.split_documents(changed)
        }
        changed_resources = {
            identity
            for identity in original_documents
            if original_documents[identity] != changed_documents[identity]
        }
        self.assertEqual({("Deployment", "faang-account-service")}, changed_resources)

    def test_all_application_deployments_have_safe_runtime_defaults(self):
        rendered = self.render(ROOT / "k8s" / "overlays" / "homelab")
        deployments = [
            document
            for document in VALIDATOR.split_documents(rendered)
            if VALIDATOR.resource_identity(document)[0] == "Deployment"
        ]
        self.assertEqual(9, len(deployments))
        required_fragments = (
            "automountServiceAccountToken: false",
            "imagePullSecrets:\n      - name: faang-registry-pull",
            "terminationGracePeriodSeconds: 60",
            "runAsNonRoot: true",
            "runAsUser: 10001",
            "readOnlyRootFilesystem: true",
            "allowPrivilegeEscalation: false",
            "type: RuntimeDefault",
            "drop:\n            - ALL",
            "requests:\n            cpu: 250m\n            memory: 512Mi",
            'limits:\n            cpu: "1"\n            memory: 2Gi',
            "startupProbe:",
            "maxUnavailable: 0",
            "topologySpreadConstraints:",
            "name: SERVER_SHUTDOWN\n          value: graceful",
            "name: SPRING_LIFECYCLE_TIMEOUT_PER_SHUTDOWN_PHASE\n          value: 45s",
            "mountPath: /tmp",
            "sizeLimit: 256Mi",
        )
        for deployment in deployments:
            for fragment in required_fragments:
                self.assertIn(fragment, deployment, VALIDATOR.resource_identity(deployment))

        documents = {
            VALIDATOR.resource_identity(document): document
            for document in deployments
        }
        user = documents[("Deployment", "faang-user-service")]
        self.assertEqual(3, user.count("tcpSocket:"))
        for service in self.IMAGE_DIGESTS.keys() - {"faang-user-service"}:
            self.assertEqual(3, documents[("Deployment", service)].count("httpGet:"), service)

    def test_redis_consumers_receive_optional_secret_backed_authentication(self):
        rendered = self.render(ROOT / "k8s" / "overlays" / "homelab")
        consumers = [
            document
            for document in VALIDATOR.split_documents(rendered)
            if VALIDATOR.resource_identity(document)[0] == "Deployment"
            and "name: REDIS_URL" in document
        ]
        self.assertEqual(6, len(consumers))
        credential_reference = (
            "name: SPRING_DATA_REDIS_PASSWORD\n"
            "          valueFrom:\n"
            "            secretKeyRef:\n"
            "              key: REDIS_PASSWORD\n"
            "              name: faang-secrets\n"
            "              optional: true"
        )
        for deployment in consumers:
            self.assertIn(
                credential_reference,
                deployment,
                VALIDATOR.resource_identity(deployment),
            )


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
            "faang-bootstrap-s3-v1": 'argocd.argoproj.io/sync-wave: "-37"',
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
        s3_job = jobs["faang-bootstrap-s3-v1"]
        self.assertRegex(s3_job, r"command:\s*\n\s*- sh\s*\n\s*- /scripts/init-s3\.sh")
        self.assertNotIn("entrypoint:", s3_job)

    def test_bootstrap_scripts_are_bounded_and_idempotent(self):
        scripts = ROOT / "k8s" / "bootstrap" / "scripts"
        postgres = (scripts / "init-postgres.sh").read_text(encoding="utf-8")
        kafka = (scripts / "init-kafka.sh").read_text(encoding="utf-8")
        elasticsearch = (scripts / "init-elasticsearch.sh").read_text(encoding="utf-8")
        s3 = (scripts / "init-s3.sh").read_text(encoding="utf-8")
        self.assertIn("CREATE SCHEMA IF NOT EXISTS", postgres)
        self.assertIn("--if-not-exists", kafka)
        self.assertIn("--head", elasticsearch)
        self.assertIn("head-bucket", s3)
        for script in (postgres, kafka, elasticsearch, s3):
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
