import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "ops" / "argocd" / "storage-application.yaml"
PROJECT = ROOT / "ops" / "argocd" / "storage-project.yaml"
VALUES = ROOT / "ops" / "storage" / "longhorn" / "values.yaml"
STORAGE_CLASS = ROOT / "ops" / "storage" / "longhorn" / "manifests" / "storageclass.yaml"
NODE_BOOTSTRAP = ROOT / "configure-longhorn-storage.ps1"
BACKUP_EXAMPLE = ROOT / "config" / "longhorn-backup.example.json"
BACKUP_VALIDATOR = ROOT / "validate-longhorn-backup.ps1"


class LonghornStorageContractTests(unittest.TestCase):
    def test_argocd_boundary_kustomize_parses_all_resources(self):
        result = subprocess.run(
            ["kubectl", "kustomize", str(ROOT / "ops" / "argocd")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(5, result.stdout.count("kind: Application\n"))
        self.assertEqual(3, result.stdout.count("kind: AppProject\n"))

    def test_application_is_manual_exact_and_no_prune(self):
        text = APPLICATION.read_text(encoding="utf-8")
        self.assertIn("project: faang-storage", text)
        self.assertIn("repoURL: 'https://charts.longhorn.io'", text)
        self.assertIn("targetRevision: 1.12.1", text)
        self.assertIn("$values/ops/storage/longhorn/values.yaml", text)
        self.assertIn("path: ops/storage/longhorn/manifests", text)
        self.assertIn("namespace: longhorn-system", text)
        self.assertIn("kind: ConfigMap", text)
        self.assertIn("name: longhorn-default-resource", text)
        self.assertIn("- /data/default-resource.yaml", text)
        self.assertIn("- RespectIgnoreDifferences=true", text)
        self.assertNotIn("automated:", text)
        self.assertNotIn("prune:", text)

    def test_runtime_backup_target_drift_is_narrowly_ignored(self):
        text = APPLICATION.read_text(encoding="utf-8")
        self.assertEqual(1, text.count("ignoreDifferences:"))
        self.assertEqual(1, text.count("kind: ConfigMap"))
        self.assertEqual(1, text.count("name: longhorn-default-resource"))
        self.assertEqual(1, text.count("- /data/default-resource.yaml"))
        self.assertNotIn("kind: Secret", text)

    def test_project_isolated_to_storage_sources_and_destination(self):
        text = PROJECT.read_text(encoding="utf-8")
        self.assertIn("name: faang-storage", text)
        self.assertIn("https://charts.longhorn.io", text)
        self.assertIn("https://github.com/bormoley1983/faang-infra.git", text)
        self.assertEqual(1, text.count("namespace: longhorn-system"))
        self.assertNotIn("namespace: faang\n", text)

    def test_values_pin_v1_and_safe_disk_creation(self):
        text = VALUES.read_text(encoding="utf-8")
        for fragment in (
            "createStorageClass: false",
            'storage.faang.io/longhorn-node: "true"',
            "createDefaultDiskLabeledNodes: true",
            "replicaSoftAntiAffinity: false",
            "replicaAutoBalance: least-effort",
            "allowVolumeCreationWithDegradedAvailability: false",
            "v1DataEngine: true",
            "v2DataEngine: false",
            "deletingConfirmationFlag: false",
            'systemManagedComponentsNodeSelector: "storage.faang.io/longhorn-node:true"',
        ):
            self.assertIn(fragment, text)
        self.assertNotIn("backupTarget:", text)
        self.assertNotIn("backupTargetCredentialSecret:", text)

    def test_storage_class_is_retained_non_default_and_tag_restricted(self):
        text = STORAGE_CLASS.read_text(encoding="utf-8")
        for fragment in (
            "name: longhorn-production-retain",
            'storageclass.kubernetes.io/is-default-class: "false"',
            "provisioner: driver.longhorn.io",
            "allowVolumeExpansion: true",
            "reclaimPolicy: Retain",
            'numberOfReplicas: "3"',
            "fsType: ext4",
            "dataLocality: best-effort",
            'replicaSoftAntiAffinity: "disabled"',
            "replicaAutoBalance: least-effort",
            "nodeSelector: longhorn-storage",
            "diskSelector: longhorn-primary",
            "dataEngine: v1",
        ):
            self.assertIn(fragment, text)
        self.assertNotIn('storageclass.kubernetes.io/is-default-class: "true"', text)

    def test_no_private_or_secret_bootstrap_material_is_tracked(self):
        tracked = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (APPLICATION, PROJECT, VALUES, STORAGE_CLASS)
        )
        for forbidden in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_ENDPOINTS",
            "kind: Secret",
            "K3S_TOKEN",
        ):
            self.assertNotIn(forbidden, tracked)

    def test_node_bootstrap_is_private_validated_and_explicitly_guarded(self):
        script = NODE_BOOTSTRAP.read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        example = (ROOT / "config" / "longhorn-storage.example.json").read_text(encoding="utf-8")
        self.assertIn("/config/longhorn-storage.local.json", gitignore)
        self.assertIn('"nodes": []', example)
        self.assertIn("exactly four private node mappings are required", script)
        self.assertIn('$RequiredNodeTag = "longhorn-storage"', script)
        self.assertIn('$RequiredDiskTag = "longhorn-primary"', script)
        self.assertIn("storage.faang.io/longhorn-node=true", script)
        self.assertIn("node.longhorn.io/create-default-disk=config", script)
        self.assertIn("node.longhorn.io/default-node-tags", script)
        self.assertIn("node.longhorn.io/default-disks-config", script)
        self.assertIn("DEP-042A-NODE-MAPPING-APPROVED", script)
        self.assertIn("Private identities and mappings: suppressed", script)
        self.assertNotIn("kubectl apply", script)

    def test_backup_target_is_pinned_private_and_validation_only(self):
        example = BACKUP_EXAMPLE.read_text(encoding="utf-8")
        validator = BACKUP_VALIDATOR.read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn('"provider": "seaweedfs"', example)
        self.assertIn('"version": "4.45"', example)
        self.assertIn(
            '"sha256": "c408894668aeaa74d4f251e20b350fd72195cbe596ddc3f48658709714f7be36"',
            example,
        )
        self.assertIn('"endpoint": ""', example)
        self.assertIn('"bucket": ""', example)
        self.assertIn("/config/longhorn-backup.local.json", gitignore)
        self.assertIn("endpoint must be an HTTPS origin", validator)
        self.assertIn("Private endpoint and credential material: suppressed", validator)
        self.assertIn("Mutation: none (validation only)", validator)
        self.assertNotIn("kubectl", validator)


if __name__ == "__main__":
    unittest.main()
