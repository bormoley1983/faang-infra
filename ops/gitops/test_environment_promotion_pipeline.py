import re
import unittest
from pathlib import Path


class EnvironmentPromotionPipelineContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        cls.pipeline = (
            repository_root
            / "ops"
            / "jenkins"
            / "tests"
            / "Jenkinsfile.environment-promotion"
        ).read_text(encoding="utf-8")

    def test_has_no_user_parameters_or_automatic_trigger(self) -> None:
        self.assertIn("disableConcurrentBuilds()", self.pipeline)
        self.assertNotIn("parameters([", self.pipeline)
        self.assertNotIn("triggers {", self.pipeline)
        self.assertNotIn("pollSCM", self.pipeline)

    def test_uses_fixed_repository_and_branch_boundaries(self) -> None:
        self.assertIn(
            "https://github.com/bormoley1983/faang-infra.git", self.pipeline
        )
        self.assertIn(
            "https://github.com/bormoley1983/faang-infra-env-homelab.git",
            self.pipeline,
        )
        self.assertIn("def publicBranch = 'dev-local'", self.pipeline)
        self.assertIn("def privateBranch = 'main'", self.pipeline)
        self.assertIn("def proposalBranch = 'env/promotions'", self.pipeline)
        self.assertIn(
            "def targetFile = 'overlays/workloads/kustomization.yaml'",
            self.pipeline,
        )

    def test_has_no_deployment_or_secret_decryption_capability(self) -> None:
        lowered = self.pipeline.lower()
        for forbidden in (
            "kubectl apply",
            "kubectl delete",
            "argocd ",
            "sops ",
            "age-key",
            "faang-registry-push",
            "faang-cosign-key",
            "kubeconfig",
        ):
            self.assertNotIn(forbidden, lowered)
        self.assertIn("automountServiceAccountToken: false", self.pipeline)

    def test_scopes_private_checkout_and_proposal_to_one_file(self) -> None:
        self.assertIn("git sparse-checkout set overlays/workloads", self.pipeline)
        self.assertGreaterEqual(
            self.pipeline.count("overlays/workloads/kustomization.yaml"), 5
        )
        self.assertIn("git add -- overlays/workloads/kustomization.yaml", self.pipeline)
        self.assertIn("*secrets/*|*.sops.yaml|*.enc.yaml|.sops.yaml", self.pipeline)
        self.assertNotIn("git add -A", self.pipeline)
        self.assertNotIn("git add .", self.pipeline)

    def test_uses_only_the_environment_proposer_for_private_mutation(self) -> None:
        self.assertEqual(
            3,
            self.pipeline.count("credentialsId: 'faang-environment-proposer'"),
        )
        self.assertNotIn("faang-gitops-proposer", self.pipeline)
        self.assertNotIn("github-app-faang-ci", self.pipeline)

    def test_uses_protected_update_and_validation_code(self) -> None:
        helper = (
            '"$WORKSPACE/protected-environment-tools/ops/gitops/'
            'update_environment_revision.py"'
        )
        self.assertEqual(3, self.pipeline.count(helper))
        self.assertIn("update \\", self.pipeline)
        self.assertIn("validate-render \\", self.pipeline)
        self.assertIn("ensure-pr \\", self.pipeline)
        self.assertIn("ops/validation/install_kubectl.py", self.pipeline)
        self.assertIn("test_update_environment_revision.py", self.pipeline)
        self.assertIn("test_environment_promotion_pipeline.py", self.pipeline)
        self.assertIn("-p 'test_*environment*.py'", self.pipeline)

    def test_never_force_pushes_or_archives_private_render(self) -> None:
        self.assertNotIn("--force", self.pipeline)
        self.assertIn("rm -f", self.pipeline)
        archive_block = re.search(
            r"archiveArtifacts\((?P<body>.*?)\n\s*\)", self.pipeline, re.DOTALL
        )
        self.assertIsNotNone(archive_block)
        self.assertNotIn("rendered-workloads", archive_block.group("body"))

    def test_uses_digest_pinned_non_privileged_containers(self) -> None:
        image_lines = [
            line.strip()
            for line in self.pipeline.splitlines()
            if line.strip().startswith("image:")
        ]
        self.assertEqual(2, len(image_lines))
        for line in image_lines:
            self.assertRegex(line, r"@sha256:[0-9a-f]{64}$")
        self.assertEqual(2, self.pipeline.count("allowPrivilegeEscalation: false"))
        self.assertEqual(2, self.pipeline.count('drop: ["ALL"]'))
        self.assertNotIn("privileged:", self.pipeline)


if __name__ == "__main__":
    unittest.main()
