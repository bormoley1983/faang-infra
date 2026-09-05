"""Static contract tests for the DEP-042B SeaweedFS application boundary."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
VALUES = (ROOT / "ops" / "object-storage" / "seaweedfs" / "values.yaml").read_text(encoding="utf-8")
RESTORE_VALUES = (ROOT / "ops" / "object-storage" / "seaweedfs" / "restore-values.yaml").read_text(encoding="utf-8")
APPLICATION = (ROOT / "ops" / "argocd" / "object-storage-application.yaml").read_text(encoding="utf-8")
PROJECT = (ROOT / "ops" / "argocd" / "object-storage-project.yaml").read_text(encoding="utf-8")
VALIDATOR = (ROOT / "validate-seaweedfs-app-s3.ps1").read_text(encoding="utf-8")
CONFIGURER = (ROOT / "configure-seaweedfs-app-s3.ps1").read_text(encoding="utf-8")
GITIGNORE = (ROOT / ".gitignore").read_text(encoding="utf-8")


class SeaweedFsObjectStorageContractTests(unittest.TestCase):
    def test_each_component_has_nonroot_identity_and_volume_group(self):
        # The image defaults to root; runAsNonRoot alone prevents startup.
        # fsGroup supplies write access to PVC data and emptyDir logs.
        for component in ("master", "volume", "filer", "s3"):
            with self.subTest(component=component):
                block = re.search(rf"(?ms)^{component}:\n(.*?)(?=^\S|\Z)", VALUES).group(1)
                pod = re.search(r"(?ms)^  podSecurityContext:\n(.*?)(?=^  \S|\Z)", block).group(1)
                self.assertRegex(pod, r"runAsNonRoot: true")
                identity = {}
                for field in ("runAsUser", "runAsGroup", "fsGroup"):
                    match = re.search(rf"(?m)^    {field}: ([1-9][0-9]*)$", pod)
                    self.assertIsNotNone(match, f"{component} needs numeric non-root {field}")
                    identity[field] = int(match.group(1))
                self.assertEqual(identity["runAsGroup"], identity["fsGroup"])

    def test_application_is_manual_and_pinned(self):
        self.assertIn("chart: seaweedfs", APPLICATION)
        self.assertIn("targetRevision: 4.45.0", APPLICATION)
        self.assertNotIn("automated:", APPLICATION)
        self.assertNotIn("prune:", APPLICATION)

    def test_project_is_restricted_to_the_object_storage_namespace(self):
        self.assertIn("namespace: faang-object-storage", PROJECT)
        self.assertIn("https://seaweedfs.github.io/seaweedfs/helm", PROJECT)

    def test_all_persistent_state_uses_nondefault_longhorn(self):
        self.assertEqual(3, VALUES.count("storageClass: longhorn-production-retain"))
        self.assertIn('tag: 4.45@sha256:fc9f76fa993ad69966ffeb2f65d0318fcae39c6f8e20cf68ef7b3a5cb97769e5', VALUES)
        self.assertIn("name: chrislusf/seaweedfs", VALUES)
        self.assertNotIn("repository: chrislusf", VALUES)
        self.assertNotIn("storageClass: local-path", VALUES)

    def test_all_components_exclude_the_csi_less_control_plane(self):
        selector = "key: node-role.kubernetes.io/control-plane\n                operator: DoesNotExist"
        for component in ("master", "volume", "filer", "s3"):
            with self.subTest(component=component):
                block = re.search(rf"(?ms)^{component}:\n(.*?)(?=^\S|\Z)", VALUES).group(1)
                self.assertIn(selector, block)

    def test_s3_is_authenticated_internal_only_and_runtime_secret_backed(self):
        self.assertIn("enableAuth: true", VALUES)
        self.assertIn("existingConfigSecret: seaweedfs-app-s3-identity", VALUES)
        self.assertIn("port: 9000", VALUES)
        self.assertIn("networkPolicy:", VALUES)
        self.assertNotIn("ingress:", VALUES)

    def test_unneeded_and_privileged_chart_features_are_disabled(self):
        self.assertIn("createClusterRole: false", VALUES)
        self.assertIn("automountServiceAccountToken: false", VALUES)
        self.assertIn("resizeHook:\n    enabled: false", VALUES)
        for component in ("admin", "sftp", "worker", "cosi", "allInOne"):
            self.assertIn(f"{component}:\n  enabled: false", VALUES)

    def test_runtime_identity_is_ignored_validated_and_explicitly_guarded(self):
        self.assertIn("/config/seaweedfs-app-s3.local.json", GITIGNORE)
        self.assertIn("Credential and bucket values: suppressed", VALIDATOR)
        self.assertIn("[switch]$Apply", CONFIGURER)
        self.assertIn("pass -Apply only after owner approval", CONFIGURER)
        self.assertIn("--from-file=\"seaweedfs_s3_config=$temporaryFile\"", CONFIGURER)

    def test_restored_filer_claim_is_explicitly_mounted_at_data(self):
        self.assertIn("claimName: restore-filer", RESTORE_VALUES)
        self.assertIn("name: restored-filer-data", RESTORE_VALUES)
        self.assertIn("mountPath: /data", RESTORE_VALUES)


if __name__ == "__main__":
    unittest.main()
