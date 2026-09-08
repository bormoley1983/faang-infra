import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "ops" / "validation" / "collect-post-deployment-verification.ps1"


class PostDeploymentVerificationTests(unittest.TestCase):
    def test_collector_is_read_only_and_redacts_live_topology(self):
        source = COLLECTOR.read_text(encoding="utf-8")
        for required in (
            "applications.argoproj.io", "endpointslice", "faang-bootstrap-postgres-v1",
            "faang-workloads", "mutationPerformed = $false", "not-probed",
            "failed-or-untrusted", "AllowAutoRedirect = $false",
            "Get-JenkinsBuildEvidence", "FAANG_JENKINS_API_TOKEN",
            "jenkins_read_only_credentials_unavailable", "jenkins_https_uri_required",
            "lastCompletedBuild", "ReadinessUri", "Get-ReadinessEvidence",
            "/actuator/health/readiness", "readiness", "contract = \"passed\"",
            "RequireReadiness", "readiness_contract_failed",
        ):
            self.assertIn(required, source)
        for forbidden in ("\"apply\"", "\"create\"", "\"delete\"", "\"patch\"", "\"sync\"", "\"rollout\"", "\"port-forward\""):
            self.assertNotIn(forbidden, source.lower())
        self.assertNotIn(".addresses", source.lower())
        self.assertNotIn("get secret", source.lower())
        self.assertNotIn("& argocd", source.lower())


if __name__ == "__main__":
    unittest.main()
