"""Static contract tests for the DEP-042D Phase 1 Kafka operator boundary."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
OPERATOR_VALUES = (ROOT / "ops" / "kafka" / "operator-values.yaml").read_text(encoding="utf-8")
APPLICATION = (ROOT / "ops" / "argocd" / "kafka-canary-application.yaml").read_text(encoding="utf-8")
PROJECT = (ROOT / "ops" / "argocd" / "kafka-project.yaml").read_text(encoding="utf-8")
OCI_REPOSITORY = (ROOT / "ops" / "argocd" / "strimzi-oci-repository.yaml").read_text(encoding="utf-8")
README = (ROOT / "ops" / "kafka" / "README.md").read_text(encoding="utf-8")
NAMESPACE = (ROOT / "ops" / "kafka" / "manifests" / "namespace.yaml").read_text(encoding="utf-8")
CANARY = (ROOT / "ops" / "kafka" / "canary" / "cluster.yaml").read_text(encoding="utf-8")
NODE_POOL = (ROOT / "ops" / "kafka" / "canary" / "node-pool.yaml").read_text(encoding="utf-8")
CANARY_KUSTOMIZATION = (ROOT / "ops" / "kafka" / "canary" / "kustomization.yaml").read_text(encoding="utf-8")
CANARY_NAMESPACE = (ROOT / "ops" / "kafka" / "canary" / "namespace.yaml").read_text(encoding="utf-8")
KUSTOMIZATION = (ROOT / "ops" / "argocd" / "kustomization.yaml").read_text(encoding="utf-8")


class KafkaPersistentProfileTests(unittest.TestCase):
    def test_single_canary_application_is_manual_and_pinned(self):
        self.assertIn("repoURL: 'quay.io/strimzi-helm'", APPLICATION)
        self.assertIn("chart: strimzi-kafka-operator", APPLICATION)
        self.assertIn("targetRevision: 1.2.0", APPLICATION)
        self.assertIn("path: ops/kafka/manifests", APPLICATION)
        self.assertIn("path: ops/kafka/canary", APPLICATION)
        self.assertIn("ServerSideApply=true", APPLICATION)
        self.assertNotIn("automated:", APPLICATION)
        self.assertNotIn("prune:", APPLICATION)

    def test_operator_watches_all_namespaces_and_avoids_control_plane(self):
        self.assertIn("watchAnyNamespace: true", OPERATOR_VALUES)
        self.assertIn("node-role.kubernetes.io/control-plane", OPERATOR_VALUES)
        self.assertIn("operator: DoesNotExist", OPERATOR_VALUES)

    def test_project_allows_only_required_operator_cluster_resources(self):
        self.assertIn("name: faang-kafka", PROJECT)
        self.assertIn("namespace: faang-kafka-system", PROJECT)
        self.assertIn("namespace: faang-kafka-canary", PROJECT)
        self.assertNotIn("namespace: faang\n", PROJECT)
        cluster_whitelist = PROJECT.split("namespaceResourceWhitelist:", maxsplit=1)[0]
        self.assertNotIn("group: '*'", cluster_whitelist)
        for kind in ("CustomResourceDefinition", "ClusterRole", "ClusterRoleBinding", "MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"):
            self.assertIn(f"kind: {kind}", PROJECT)

    def test_public_oci_repository_is_declared_for_argocd(self):
        self.assertIn("argocd.argoproj.io/secret-type: repository", OCI_REPOSITORY)
        self.assertIn("url: quay.io/strimzi-helm", OCI_REPOSITORY)
        self.assertIn('enableOCI: "true"', OCI_REPOSITORY)
        self.assertIn("- 'quay.io/strimzi-helm'", PROJECT)

    def test_boundary_has_no_credential_or_application_routing(self):
        tracked = "\n".join((OPERATOR_VALUES, APPLICATION, PROJECT))
        for forbidden in ("KAFKA_BOOTSTRAP_SERVERS", "kafka-main", "password", "secret"):
            self.assertNotIn(forbidden.lower(), tracked.lower())
        self.assertIsNone(re.search(r"(?m)^kind:\s*(?:Secret|Topic)$", tracked))
        self.assertIn("intentionally does **not** create a production Kafka", README)

    def test_operator_namespace_is_declared_before_chart_resources(self):
        self.assertIn("kind: Namespace", NAMESPACE)
        self.assertIn("name: faang-kafka-system", NAMESPACE)

    def test_canary_is_manual_pinned_and_uses_retained_storage(self):
        self.assertRegex(CANARY, r"(?m)^apiVersion: kafka\.strimzi\.io/v1$")
        self.assertNotRegex(CANARY, r"(?m)^apiVersion: kafka\.strimzi\.io/v1beta2$")
        self.assertIn("name: faang-kafka-canary", CANARY)
        self.assertIn("version: 4.3.1", CANARY)
        self.assertIn("port: 9092", CANARY)
        self.assertIn("tls: false", CANARY)
        self.assertIn("- namespace.yaml", CANARY_KUSTOMIZATION)
        self.assertIn("- node-pool.yaml", CANARY_KUSTOMIZATION)
        self.assertIn("- cluster.yaml", CANARY_KUSTOMIZATION)
        self.assertIn("name: faang-kafka-canary", CANARY_NAMESPACE)
        self.assertIn('argocd.argoproj.io/sync-wave: "2"', CANARY)

    def test_canary_is_kraft_only_no_zookeeper(self):
        self.assertNotIn("zookeeper:", CANARY)
        self.assertNotIn("ZookeeperCluster", CANARY)

    def test_canary_has_bounded_resources_and_anti_affinity(self):
        self.assertIn("kind: KafkaNodePool", NODE_POOL)
        self.assertIn("strimzi.io/cluster: faang-kafka-canary", NODE_POOL)
        self.assertIn("replicas: 1", NODE_POOL)
        self.assertIn("- controller", NODE_POOL)
        self.assertIn("- broker", NODE_POOL)
        self.assertIn("class: longhorn-production-retain", NODE_POOL)
        self.assertIn("kraftMetadata: shared", NODE_POOL)
        self.assertIn("size: 10Gi", NODE_POOL)
        self.assertIn("cpu: 250m", NODE_POOL)
        self.assertIn("memory: 512Mi", NODE_POOL)
        self.assertIn('cpu: "1"', NODE_POOL)
        self.assertIn("memory: 2Gi", NODE_POOL)
        self.assertIn("runAsNonRoot: true", NODE_POOL)
        self.assertIn("node-role.kubernetes.io/control-plane", NODE_POOL)
        self.assertIn("operator: DoesNotExist", NODE_POOL)
        self.assertIn('argocd.argoproj.io/sync-wave: "1"', NODE_POOL)

    def test_kafka_resources_are_registered_in_argocd_kustomization(self):
        self.assertIn("- kafka-project.yaml", KUSTOMIZATION)
        self.assertIn("- strimzi-oci-repository.yaml", KUSTOMIZATION)
        self.assertIn("- kafka-canary-application.yaml", KUSTOMIZATION)
        self.assertFalse((ROOT / "ops" / "argocd" / "kafka-operator-application.yaml").exists())


if __name__ == "__main__":
    unittest.main()
