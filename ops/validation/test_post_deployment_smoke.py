import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "k8s" / "preflight" / "post-deployment" / "smoke-job.yaml"
RUNNER = ROOT / "run-post-deployment-smoke.ps1"


class PostDeploymentSmokeTests(unittest.TestCase):
    def test_smoke_job_is_bounded_tokenless_and_non_destructive(self):
        source = MANIFEST.read_text(encoding="utf-8")
        for required in (
            "automountServiceAccountToken: false", "backoffLimit: 0",
            "activeDeadlineSeconds: 180", "ttlSecondsAfterFinished: 600",
            "runAsNonRoot: true", "readOnlyRootFilesystem: true",
            "allowPrivilegeEscalation: false", "- ALL", "--connect-timeout 5",
            "--max-time 10", "http://faang-user-service/",
        ):
            self.assertIn(required, source)
        for service in ("account", "achievement", "analytics", "notification", "payment", "post", "project", "url-shortener"):
            self.assertIn("faang-$service-service", source)
        for forbidden in ("POST", "PUT", "DELETE", "kubectl", "hostPath:", "privileged: true"):
            self.assertNotIn(forbidden, source)

    def test_smoke_manifest_renders_and_runner_requires_explicit_confirmation(self):
        self.assertFalse((MANIFEST.parent / "kustomization.yaml").exists(), "The active probe must not be implicitly kustomized into Argo.")
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("[Parameter(Mandatory)][switch]$ConfirmActiveProbe", runner)
        self.assertIn("Explicit -ConfirmActiveProbe is required.", runner)
        self.assertIn("$createdJobUid", runner)
        self.assertIn("$currentJobUid -eq $createdJobUid", runner)
        self.assertIn("finally", runner)
        self.assertIn("delete job", runner)
        self.assertNotIn("argocd", runner.lower())

    def test_probe_uses_the_stable_service_port(self):
        workloads = ROOT / "k8s" / "overlays" / "homelab" / "boundaries" / "workloads"
        result = subprocess.run(["kubectl", "kustomize", str(workloads)], text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        services = ("account", "achievement", "analytics", "notification", "payment", "post", "project", "url-shortener", "user")
        documents = result.stdout.split("---\n")
        for service in services:
            document = next(item for item in documents if f"name: faang-{service}-service" in item and "kind: Service" in item)
            self.assertIn("port: 80", document, service)


if __name__ == "__main__":
    unittest.main()
