import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "ops" / "jenkins" / "tests" / "Jenkinsfile.service-delivery"


class ServiceDeliveryGitOpsHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pipeline = PIPELINE.read_text(encoding="utf-8")

    def test_handoff_runs_only_after_both_native_checks(self):
        amd64 = self.pipeline.index("stage('Native amd64 verification')")
        arm64 = self.pipeline.index("stage('Native arm64 verification')")
        proposal = self.pipeline.index("stage('Propose GitOps update')")
        success = self.pipeline.index('echo "SERVICE DELIVERY PASS')

        self.assertLess(amd64, arm64)
        self.assertLess(arm64, proposal)
        self.assertLess(proposal, success)

    def test_handoff_passes_only_archived_publication_identity(self):
        start = self.pipeline.index("stage('Propose GitOps update')")
        handoff = self.pipeline[start : self.pipeline.index('echo "SERVICE DELIVERY PASS')]

        self.assertIn("job: 'gitops-proposal'", handoff)
        self.assertIn("string(name: 'SERVICE_IMAGE', value: '__SERVICE_IMAGE__')", handoff)
        self.assertIn("string(name: 'SERVICE_REVISION', value: env.OCI_REVISION)", handoff)
        self.assertIn("string(name: 'PUBLICATION_DIGEST', value: publishedDigest)", handoff)
        self.assertIn("wait: true", handoff)
        self.assertIn("propagate: false", handoff)

        for forbidden in ("withCredentials", "kubectl", "argocd", "COSIGN_KEY", "REGISTRY_PASSWORD"):
            self.assertNotIn(forbidden, handoff)

    def test_failed_proposal_is_actionable_after_publication(self):
        self.assertIn("if (proposalBuild.result != 'SUCCESS')", self.pipeline)
        self.assertIn("Image publication and native verification succeeded", self.pipeline)
        self.assertIn("Retry gitops-proposal with the archived publication-digest", self.pipeline)


if __name__ == "__main__":
    unittest.main()
