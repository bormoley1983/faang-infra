"""Static contract tests for the DEP-042D Phase 3 Redis boundary."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
VALUES = (ROOT / "ops" / "redis" / "canary-values.yaml").read_text(encoding="utf-8")
APPLICATION = (ROOT / "ops" / "argocd" / "redis-canary-application.yaml").read_text(encoding="utf-8")
PROJECT = (ROOT / "ops" / "argocd" / "redis-project.yaml").read_text(encoding="utf-8")
OCI_REPOSITORY = (ROOT / "ops" / "argocd" / "redis-oci-repository.yaml").read_text(encoding="utf-8")
KUSTOMIZATION = (ROOT / "ops" / "argocd" / "kustomization.yaml").read_text(encoding="utf-8")
README = (ROOT / "ops" / "redis" / "README.md").read_text(encoding="utf-8")


class RedisPersistentProfileTests(unittest.TestCase):
    def test_single_canary_application_is_manual_and_pinned(self):
        self.assertIn("chart: redis", APPLICATION)
        self.assertIn("targetRevision: 27.0.17", APPLICATION)
        self.assertIn("path: ops/redis/canary", APPLICATION)
        self.assertIn("ServerSideApply=true", APPLICATION)
        self.assertNotIn("automated:", APPLICATION)
        self.assertNotIn("prune:", APPLICATION)

    def test_public_oci_repository_is_credential_free_and_declared(self):
        self.assertIn("argocd.argoproj.io/secret-type: repository", OCI_REPOSITORY)
        self.assertIn("url: registry-1.docker.io/bitnamicharts", OCI_REPOSITORY)
        self.assertIn('enableOCI: "true"', OCI_REPOSITORY)
        self.assertIn("- 'registry-1.docker.io/bitnamicharts'", PROJECT)

    def test_project_is_restricted_to_canary_namespace(self):
        self.assertIn("name: faang-redis", PROJECT)
        self.assertEqual(1, PROJECT.count("namespace: faang-redis-canary"))
        cluster_whitelist = PROJECT.split("namespaceResourceWhitelist:", maxsplit=1)[0]
        self.assertNotIn("group: '*'", cluster_whitelist)

    def test_canary_is_standalone_persistent_bounded_and_nonroot(self):
        for fragment in (
            "architecture: standalone",
            "enabled: false",
            "sha256:ffa455a3ad00bccc24dfde113ef55329dde687da242e9feb6ccd2b30eb93e8f3",
            "storageClass: longhorn-production-retain",
            "size: 10Gi",
            "cpu: 100m",
            "memory: 256Mi",
            "cpu: 500m",
            "memory: 1Gi",
            "runAsNonRoot: true",
            "node-role.kubernetes.io/control-plane",
            "operator: DoesNotExist",
        ):
            self.assertIn(fragment, VALUES)

    def test_boundary_has_no_credentials_or_application_routing(self):
        tracked = "\n".join((VALUES, APPLICATION, PROJECT, OCI_REPOSITORY))
        for forbidden in ("password:", "existingSecret", "REDIS_PASSWORD", "redis-main"):
            self.assertNotIn(forbidden.lower(), tracked.lower())
        self.assertEqual(1, len(re.findall(r"(?m)^kind:\s*Secret$", tracked)))
        self.assertIn("no application routing or credential in Git", README)

    def test_resources_are_registered_in_argocd_kustomization(self):
        for name in ("redis-oci-repository.yaml", "redis-project.yaml", "redis-canary-application.yaml"):
            self.assertIn(f"- {name}", KUSTOMIZATION)


if __name__ == "__main__":
    unittest.main()
