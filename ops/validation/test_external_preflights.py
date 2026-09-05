import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT = ROOT / "k8s" / "preflight" / "external"
MODULE_PATH = Path(__file__).with_name("validate_deployment.py")
SPEC = importlib.util.spec_from_file_location("validate_deployment", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


class ExternalPreflightTests(unittest.TestCase):
    def render(self) -> str:
        result = subprocess.run(
            ["kubectl", "kustomize", str(PREFLIGHT)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def test_five_bounded_tokenless_jobs_render(self):
        documents = VALIDATOR.split_documents(self.render())
        jobs = [document for document in documents if VALIDATOR.resource_identity(document)[0] == "Job"]
        self.assertEqual(5, len(jobs))
        self.assertEqual(
            {"postgresql", "redis", "elasticsearch", "kafka", "s3"},
            {
                next(
                    line.split(":", 1)[1].strip()
                    for line in document.splitlines()
                    if line.strip().startswith("faang.io/dependency:")
                )
                for document in jobs
            },
        )
        for job in jobs:
            self.assertIn("automountServiceAccountToken: false", job)
            self.assertIn("backoffLimit: 0", job)
            self.assertIn("activeDeadlineSeconds: 330", job)
            self.assertIn("ttlSecondsAfterFinished: 600", job)
            self.assertIn("runAsNonRoot: true", job)
            self.assertIn("runAsUser: 10001", job)
            self.assertIn("runAsGroup: 10001", job)
            self.assertIn("readOnlyRootFilesystem: true", job)
            self.assertIn("allowPrivilegeEscalation: false", job)
            self.assertIn("drop:\n            - ALL", job)
            self.assertIn("requests:", job)
            self.assertIn("limits:", job)
            self.assertRegex(job, r"image:\s+[^\s]+@sha256:[0-9a-f]{64}")
            self.assertNotIn("hostPath:", job)
            self.assertNotIn("privileged: true", job)

    def test_scripts_are_read_only_and_check_bootstrap_state(self):
        scripts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((PREFLIGHT / "common" / "scripts").glob("*.sh"))
        )
        for forbidden in (
            "CREATE DATABASE",
            "CREATE SCHEMA",
            "--create",
            "--request PUT",
            "mc mb",
            "kubectl",
        ):
            self.assertNotIn(forbidden, scripts)
        for required in (
            "uuidv7()",
            "PING",
            "hashtags_index",
            "required_topics=13",
            "required_buckets=2",
            "PGCONNECT_TIMEOUT=10",
            "statement_timeout=15000",
            "--connect-timeout 10 --max-time 30",
            "-t 10",
            'REDISCLI_AUTH="$REDIS_PASSWORD"',
            "Redis authentication failed or conflicts with the declared credential policy",
            "Redis ACL denied the read-only PING command",
            "Redis TLS negotiation failed or conflicts with the declared TLS policy",
            "request.timeout.ms=10000",
            "default.api.timeout.ms=30000",
        ):
            self.assertIn(required, scripts)
        self.assertNotIn("--connect-timeout 10 --no-auth-warning", scripts)
        self.assertNotIn('-a "$REDIS_PASSWORD"', scripts)

    def test_shell_scripts_are_lf_only_for_configmap_execution(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.sh text eol=lf", attributes.splitlines())

        for path in sorted((PREFLIGHT / "common" / "scripts").glob("*.sh")):
            self.assertNotIn(b"\r\n", path.read_bytes(), str(path.relative_to(ROOT)))

    def test_runner_selects_only_external_modes_and_cleans_exact_resources(self):
        runner = (ROOT / "run-external-preflights.ps1").read_text(encoding="utf-8")
        self.assertIn('mode -eq "external"', runner)
        self.assertIn("validate_dependency_selection.py", runner)
        self.assertIn("concurrent runs are not allowed", runner)
        self.assertIn("Wait-PreflightJob", runner)
        self.assertIn('$trueConditions -contains "Failed"', runner)
        self.assertIn('"CreateContainerConfigError"', runner)
        self.assertIn("finally", runner)
        self.assertIn("delete job", runner)
        self.assertIn("delete configmap faang-external-preflight-scripts", runner)
        self.assertIn("delete serviceaccount faang-external-preflight", runner)
        self.assertNotIn("kubectl apply -k k8s/overlays/homelab", runner)
        self.assertNotIn("argocd", runner.lower())


if __name__ == "__main__":
    unittest.main()
