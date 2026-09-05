"""Static contract tests for the DEP-042C PostgreSQL operator boundary."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
OPERATOR_VALUES = (ROOT / "ops" / "database" / "postgresql" / "operator-values.yaml").read_text(encoding="utf-8")
PLUGIN_VALUES = (ROOT / "ops" / "database" / "postgresql" / "barman-plugin-values.yaml").read_text(encoding="utf-8")
APPLICATION = (ROOT / "ops" / "argocd" / "postgresql-operator-application.yaml").read_text(encoding="utf-8")
CANARY_APPLICATION = (ROOT / "ops" / "argocd" / "postgresql-canary-application.yaml").read_text(encoding="utf-8")
FOUNDATION_APPLICATION = (ROOT / "ops" / "argocd" / "postgresql-canary-foundation-application.yaml").read_text(encoding="utf-8")
PROJECT = (ROOT / "ops" / "argocd" / "postgresql-project.yaml").read_text(encoding="utf-8")
README = (ROOT / "ops" / "database" / "postgresql" / "README.md").read_text(encoding="utf-8")
NAMESPACE = (ROOT / "ops" / "database" / "postgresql" / "manifests" / "namespace.yaml").read_text(encoding="utf-8")
CANARY = (ROOT / "ops" / "database" / "postgresql" / "canary" / "cluster.yaml").read_text(encoding="utf-8")
BACKUP_VALIDATOR = (ROOT / "validate-postgresql-backup.ps1").read_text(encoding="utf-8")
BACKUP_CONFIGURER = (ROOT / "configure-postgresql-backup.ps1").read_text(encoding="utf-8")
GITIGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8")


class PostgresqlPersistentProfileTests(unittest.TestCase):
    def test_operator_and_plugin_charts_are_manual_and_pinned(self):
        self.assertIn("chart: cloudnative-pg", APPLICATION)
        self.assertIn("targetRevision: 0.29.0", APPLICATION)
        self.assertIn("chart: plugin-barman-cloud", APPLICATION)
        self.assertIn("targetRevision: 0.8.0", APPLICATION)
        self.assertIn("path: ops/database/postgresql/manifests", APPLICATION)
        self.assertIn("ServerSideApply=true", APPLICATION)
        self.assertNotIn("automated:", APPLICATION)
        self.assertNotIn("prune:", APPLICATION)

    def test_all_operator_images_are_immutable_multiarch_indexes(self):
        self.assertIn("1.30.0@sha256:a2701eb97cdd2a34b1fdb2cb51987f544b706e40bec72ae7146cd8580efefebb", OPERATOR_VALUES)
        self.assertIn("v0.15.0@sha256:563c680fe7fda3466ca2b1f55a1397ed2ddc9e760360107dd7724f1959c1a536", PLUGIN_VALUES)
        self.assertIn("v0.15.0@sha256:06c78deca670525daa35fb1e5323159092785d11cf87b86217bdd5c679a41a84", PLUGIN_VALUES)

    def test_operator_is_clusterwide_but_not_control_plane_scheduled(self):
        self.assertIn("clusterWide: true", OPERATOR_VALUES)
        for values in (OPERATOR_VALUES, PLUGIN_VALUES):
            self.assertIn("node-role.kubernetes.io/control-plane", values)
            self.assertIn("operator: DoesNotExist", values)

    def test_project_allows_only_required_operator_cluster_resources(self):
        self.assertIn("name: faang-postgresql", PROJECT)
        self.assertIn("namespace: cnpg-system", PROJECT)
        self.assertNotIn("namespace: faang\n", PROJECT)
        cluster_whitelist = PROJECT.split("namespaceResourceWhitelist:", maxsplit=1)[0]
        self.assertNotIn("group: '*'", cluster_whitelist)
        for kind in ("CustomResourceDefinition", "ClusterRole", "ClusterRoleBinding", "MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"):
            self.assertIn(f"kind: {kind}", PROJECT)

    def test_boundary_has_no_database_or_credential_configuration(self):
        tracked = "\n".join((OPERATOR_VALUES, PLUGIN_VALUES, APPLICATION, PROJECT))
        for forbidden in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "postgres-main"):
            self.assertNotIn(forbidden, tracked)
        self.assertIsNone(re.search(r"(?m)^kind:\s*(?:Secret|ObjectStore|Cluster)$", tracked))
        self.assertIn("intentionally does **not** create a CloudNativePG `Cluster`", README)

    def test_operator_namespace_is_declared_before_chart_resources(self):
        self.assertIn("kind: Namespace", NAMESPACE)
        self.assertIn("name: cnpg-system", NAMESPACE)

    def test_canary_is_manual_pinned_and_uses_retained_storage(self):
        self.assertIn("name: faang-postgresql-canary", CANARY)
        self.assertIn("instances: 1", CANARY)
        self.assertIn("postgresql:18.4@sha256:6138f19539304b585c6cafd1af82ca407f184139459a8e06f0880df4556d3588", CANARY)
        self.assertIn("storageClass: longhorn-production-retain", CANARY)
        self.assertIn("isWALArchiver: true", CANARY)
        self.assertIn("barmanObjectName: faang-postgresql-backup", CANARY)
        self.assertIn("path: ops/database/postgresql/canary", CANARY_APPLICATION)
        self.assertIn("path: ops/database/postgresql/canary/foundation", FOUNDATION_APPLICATION)
        self.assertNotIn("automated:", CANARY_APPLICATION + FOUNDATION_APPLICATION)

    def test_backup_configuration_is_private_and_separate_from_existing_s3_identities(self):
        self.assertIn("/config/postgresql-backup.local.json", GITIGNORE)
        self.assertIn("PostgreSQL must not reuse Longhorn's backup bucket", BACKUP_VALIDATOR)
        self.assertIn("PostgreSQL must not reuse an application S3 bucket", BACKUP_VALIDATOR)
        self.assertIn("runtime and provisioning identity files must be distinct", BACKUP_VALIDATOR)
        self.assertIn("[switch]$Apply", BACKUP_CONFIGURER)
        self.assertIn("aws --endpoint-url", BACKUP_CONFIGURER)
        self.assertIn("kind: ObjectStore", BACKUP_CONFIGURER)


if __name__ == "__main__":
    unittest.main()
