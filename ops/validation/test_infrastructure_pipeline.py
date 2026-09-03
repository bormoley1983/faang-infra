import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JENKINSFILE = ROOT / "ops" / "jenkins" / "Jenkinsfile"
INSTALLER_PATH = Path(__file__).with_name("install_kubectl.py")
SPEC = importlib.util.spec_from_file_location("install_kubectl", INSTALLER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {INSTALLER_PATH}")
INSTALLER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INSTALLER
SPEC.loader.exec_module(INSTALLER)


class InfrastructurePipelineTests(unittest.TestCase):
    def test_pipeline_uses_a_bounded_credential_free_kubernetes_agent(self):
        script = JENKINSFILE.read_text(encoding="utf-8")
        self.assertIn("podTemplate(yaml:", script)
        self.assertIn("node(POD_LABEL)", script)
        self.assertIn("automountServiceAccountToken: false", script)
        self.assertIn("activeDeadlineSeconds: 900", script)
        self.assertIn("readOnlyRootFilesystem: true", script)
        self.assertIn('drop: ["ALL"]', script)
        self.assertRegex(script, r"image: python:[^\s]+@sha256:[0-9a-f]{64}")
        for forbidden in (
            "agent any",
            "timestamps()",
            "withCredentials",
            "credentialsId",
            "checkout scm",
            "REGISTRY_PASSWORD",
            "COSIGN_KEY",
            "argocd",
            "kubectl apply",
        ):
            self.assertNotIn(forbidden, script)

        self.assertIn("env.BRANCH_NAME != 'dev-local'", script)
        self.assertIn("branches: [[name: 'refs/heads/dev-local']]", script)
        self.assertIn("+refs/heads/dev-local:refs/remotes/origin/dev-local", script)
        self.assertIn("https://github.com/bormoley1983/faang-infra.git", script)

    def test_pipeline_archives_revision_and_both_validation_logs(self):
        script = JENKINSFILE.read_text(encoding="utf-8")
        self.assertIn("dir('.ci-evidence')", script)
        self.assertIn("writeFile(file: 'revision.txt'", script)
        self.assertIn("git ls-files", script)
        self.assertIn("writeFile(file: 'tracked-manifests.txt'", script)
        self.assertIn("--tracked-source-list .ci-evidence/tracked-manifests.txt", script)
        self.assertIn(".ci-evidence/tests.log", script)
        self.assertIn(".ci-evidence/deployment-validation.log", script)
        self.assertIn("archiveArtifacts(", script)
        self.assertIn("--strict", script)

    def test_kubectl_download_is_version_and_checksum_pinned(self):
        self.assertEqual("1.36.0", INSTALLER.KUBECTL_VERSION)
        self.assertRegex(INSTALLER.KUBECTL_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            "https://dl.k8s.io/v1.36.0/bin/linux/amd64/kubectl",
            INSTALLER.KUBECTL_URL,
        )


if __name__ == "__main__":
    unittest.main()
