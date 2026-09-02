import unittest
from pathlib import Path


class GitOpsPipelineContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        cls.pipeline = (
            repository_root / "ops" / "jenkins" / "tests" / "Jenkinsfile.gitops-proposal"
        ).read_text(encoding="utf-8")

    def test_serializes_all_digest_proposals(self) -> None:
        self.assertIn("disableConcurrentBuilds()", self.pipeline)
        self.assertIn("gitops/promotions", self.pipeline)
        self.assertNotIn("--force", self.pipeline)

    def test_has_no_deployment_or_publication_capability(self) -> None:
        lowered = self.pipeline.lower()
        for forbidden in (
            "kubectl",
            "argocd",
            "faang-registry-push",
            "faang-cosign-key",
            "faang-cosign-password",
        ):
            self.assertNotIn(forbidden, lowered)
        self.assertEqual(4, self.pipeline.count("faang-gitops-proposer"))
        self.assertIn("automountServiceAccountToken: false", self.pipeline)

    def test_executes_mutation_code_from_protected_base(self) -> None:
        self.assertIn("stash(\n                            name: 'protected-gitops-tools'", self.pipeline)
        self.assertIn(
            '"$WORKSPACE/protected-gitops-tools/ops/gitops/update_image_digest.py"',
            self.pipeline,
        )
        self.assertIn(
            '"$WORKSPACE/protected-gitops-tools/ops/gitops/create_or_reuse_pull_request.py"',
            self.pipeline,
        )

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
