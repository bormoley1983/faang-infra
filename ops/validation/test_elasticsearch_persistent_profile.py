"""Static contract tests for the DEP-042D Phase 2 ECK boundary."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
VALUES = (ROOT / "ops" / "elasticsearch" / "operator-values.yaml").read_text(encoding="utf-8")
APPLICATION = (ROOT / "ops" / "argocd" / "elasticsearch-canary-application.yaml").read_text(encoding="utf-8")
PROJECT = (ROOT / "ops" / "argocd" / "elasticsearch-project.yaml").read_text(encoding="utf-8")
CANARY = (ROOT / "ops" / "elasticsearch" / "canary" / "cluster.yaml").read_text(encoding="utf-8")
CANARY_KUSTOMIZATION = (ROOT / "ops" / "elasticsearch" / "canary" / "kustomization.yaml").read_text(encoding="utf-8")
KUSTOMIZATION = (ROOT / "ops" / "argocd" / "kustomization.yaml").read_text(encoding="utf-8")
README = (ROOT / "ops" / "elasticsearch" / "README.md").read_text(encoding="utf-8")


class ElasticsearchPersistentProfileTests(unittest.TestCase):
    def test_single_canary_application_is_manual_and_pinned(self):
        self.assertIn("chart: eck-operator", APPLICATION)
        self.assertIn("targetRevision: 3.4.1", APPLICATION)
        self.assertIn("path: ops/elasticsearch/manifests", APPLICATION)
        self.assertIn("path: ops/elasticsearch/canary", APPLICATION)
        self.assertIn("ServerSideApply=true", APPLICATION)
        self.assertNotIn("automated:", APPLICATION)
        self.assertNotIn("prune:", APPLICATION)

    def test_operator_is_bounded_pinned_and_restricted_to_canary_namespace(self):
        for fragment in (
            "installCRDs: true",
            "tag: 3.4.1",
            "sha256:8190b4c57156a3f7a8da86db9d474c238a517738368fe18c4762100d73af5d01",
            "- faang-elasticsearch-canary",
            "cpu: 100m",
            "memory: 256Mi",
            "cpu: 500m",
            "memory: 512Mi",
            "telemetry:\n  disabled: true",
            "node-role.kubernetes.io/control-plane",
            "operator: DoesNotExist",
        ):
            self.assertIn(fragment, VALUES)

    def test_project_allows_only_required_operator_cluster_resources(self):
        self.assertIn("name: faang-elasticsearch", PROJECT)
        self.assertIn("namespace: faang-elasticsearch-system", PROJECT)
        self.assertIn("namespace: faang-elasticsearch-canary", PROJECT)
        cluster_whitelist = PROJECT.split("namespaceResourceWhitelist:", maxsplit=1)[0]
        self.assertNotIn("group: '*'", cluster_whitelist)
        for kind in ("CustomResourceDefinition", "ClusterRole", "ClusterRoleBinding", "MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"):
            self.assertIn(f"kind: {kind}", PROJECT)

    def test_canary_is_one_node_persistent_nonroot_and_immutable(self):
        for fragment in (
            "apiVersion: elasticsearch.k8s.elastic.co/v1",
            "kind: Elasticsearch",
            "name: faang-elasticsearch-canary",
            "version: 9.5.2",
            "sha256:9c1e1afc2bda921b35025e21c72ec6e392266995aa35ad6a47887363592718be",
            "count: 1",
            "volumeClaimDeletePolicy: DeleteOnScaledownOnly",
            "name: elasticsearch-data",
            "storageClassName: longhorn-production-retain",
            "storage: 20Gi",
            "runAsNonRoot: true",
            "cpu: 250m",
            "memory: 1Gi",
            'cpu: "1"',
            "memory: 2Gi",
            'argocd.argoproj.io/sync-wave: "2"',
        ):
            self.assertIn(fragment, CANARY)
        self.assertIn("- namespace.yaml", CANARY_KUSTOMIZATION)
        self.assertIn("- cluster.yaml", CANARY_KUSTOMIZATION)

    def test_boundary_has_no_credentials_or_application_routing(self):
        tracked = "\n".join((VALUES, APPLICATION, PROJECT, CANARY))
        for forbidden in ("ELASTICSEARCH_PASSWORD", "ELASTICSEARCH_USERNAME", "elasticsearch-main"):
            self.assertNotIn(forbidden, tracked)
        self.assertIsNone(re.search(r"(?m)^kind:\s*Secret$", tracked))
        self.assertIn("intentionally does **not** create `elasticsearch-main`", README)

    def test_resources_are_registered_in_argocd_kustomization(self):
        self.assertIn("- elasticsearch-project.yaml", KUSTOMIZATION)
        self.assertIn("- elasticsearch-canary-application.yaml", KUSTOMIZATION)


if __name__ == "__main__":
    unittest.main()
