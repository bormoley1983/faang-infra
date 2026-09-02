import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from update_image_digest import (
    DigestUpdateError,
    RetryableDigestUpdateError,
    _replace_digest,
    load_allowed_services,
    update_image_digest,
)


ACCOUNT = "faang-account-service"
USER = "faang-user-service"
OLD_ACCOUNT = "sha256:" + "1" * 64
NEW_ACCOUNT = "sha256:" + "2" * 64
OLD_USER = "sha256:" + "3" * 64
NEW_USER = "sha256:" + "4" * 64


class UpdateImageDigestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent
        unique_id = uuid.uuid4().hex
        self.kustomization = self.root / f".test-kustomization-{unique_id}.yaml"
        self.inventory = self.root / f".test-service-images-{unique_id}.json"
        self.addCleanup(self._remove_test_files)
        self.original = (
            "namespace: faang\n"
            "images:\n"
            f"  - name: registry.example/{ACCOUNT}\n"
            f"    digest: {OLD_ACCOUNT}\n"
            f"  - name: registry.example/{USER}\n"
            f"    digest: {OLD_USER}\n"
        )
        self.kustomization.write_text(self.original, encoding="utf-8", newline="")
        self.inventory.write_text(
            json.dumps([{"image": ACCOUNT}, {"image": USER}]),
            encoding="utf-8",
        )

    def _remove_test_files(self) -> None:
        paths = [
            self.kustomization,
            self.inventory,
            self.kustomization.with_name(f"{self.kustomization.name}.digest-update.lock"),
        ]
        paths.extend(self.root.glob(f".{self.kustomization.name}.*.tmp"))
        for path in paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def update(
        self,
        service: str = ACCOUNT,
        digest: str = NEW_ACCOUNT,
        expected: str | None = None,
    ):
        return update_image_digest(
            self.kustomization,
            self.inventory,
            service,
            digest,
            expected,
        )

    def test_updates_exactly_one_allowlisted_digest(self) -> None:
        result = self.update(expected=OLD_ACCOUNT)

        self.assertTrue(result.changed)
        content = self.kustomization.read_text(encoding="utf-8")
        self.assertIn(f"digest: {NEW_ACCOUNT}", content)
        self.assertIn(f"digest: {OLD_USER}", content)
        self.assertNotIn(OLD_ACCOUNT, content)

    def test_repeating_the_same_update_is_idempotent(self) -> None:
        self.update()
        result = self.update()

        self.assertFalse(result.changed)
        self.assertEqual(1, self.kustomization.read_text(encoding="utf-8").count(NEW_ACCOUNT))

    def test_sequential_service_updates_preserve_both_changes(self) -> None:
        self.update()
        self.update(USER, NEW_USER)

        content = self.kustomization.read_text(encoding="utf-8")
        self.assertIn(f"digest: {NEW_ACCOUNT}", content)
        self.assertIn(f"digest: {NEW_USER}", content)

    def test_rejects_unknown_service_without_writing(self) -> None:
        with self.assertRaises(DigestUpdateError):
            self.update("faang-unknown-service")

        self.assertEqual(self.original, self.kustomization.read_text(encoding="utf-8"))

    def test_rejects_malformed_digest_without_writing(self) -> None:
        with self.assertRaises(DigestUpdateError):
            self.update(digest="sha256:not-a-digest")

        self.assertEqual(self.original, self.kustomization.read_text(encoding="utf-8"))

    def test_expected_digest_mismatch_is_retryable_and_does_not_write(self) -> None:
        with self.assertRaises(RetryableDigestUpdateError):
            self.update(expected="sha256:" + "9" * 64)

        self.assertEqual(self.original, self.kustomization.read_text(encoding="utf-8"))

    def test_workspace_lock_contention_is_retryable(self) -> None:
        lock_path = self.kustomization.with_name(
            f"{self.kustomization.name}.digest-update.lock"
        )
        lock_path.write_text("held\n", encoding="ascii")

        with self.assertRaises(RetryableDigestUpdateError):
            self.update()

        self.assertEqual(self.original, self.kustomization.read_text(encoding="utf-8"))

    def test_atomic_write_failure_preserves_original_file_and_releases_lock(self) -> None:
        with patch("update_image_digest.os.replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(RetryableDigestUpdateError):
                self.update()

        self.assertEqual(self.original, self.kustomization.read_text(encoding="utf-8"))
        self.assertFalse(
            self.kustomization.with_name(
                f"{self.kustomization.name}.digest-update.lock"
            ).exists()
        )
        self.assertEqual([], list(self.root.glob(f".{self.kustomization.name}.*.tmp")))

    def test_rejects_duplicate_target_mapping(self) -> None:
        duplicate = self.original + (
            f"  - name: another.example/{ACCOUNT}\n"
            f"    digest: {OLD_ACCOUNT}\n"
        )
        self.kustomization.write_text(duplicate, encoding="utf-8", newline="")

        with self.assertRaises(DigestUpdateError):
            self.update()

        self.assertEqual(duplicate, self.kustomization.read_text(encoding="utf-8"))

    def test_rejects_target_mapping_outside_images_block(self) -> None:
        outside_images = (
            "namespace: faang\n"
            f"- name: registry.example/{ACCOUNT}\n"
            f"  digest: {OLD_ACCOUNT}\n"
            "images:\n"
            f"  - name: registry.example/{USER}\n"
            f"    digest: {OLD_USER}\n"
        )
        self.kustomization.write_text(outside_images, encoding="utf-8", newline="")

        with self.assertRaises(DigestUpdateError):
            self.update()

        self.assertEqual(outside_images, self.kustomization.read_text(encoding="utf-8"))

    def test_rejects_duplicate_top_level_images_blocks(self) -> None:
        duplicate_images = self.original + "images: []\n"
        self.kustomization.write_text(duplicate_images, encoding="utf-8", newline="")

        with self.assertRaises(DigestUpdateError):
            self.update()

        self.assertEqual(duplicate_images, self.kustomization.read_text(encoding="utf-8"))

    def test_preserves_crlf_line_endings(self) -> None:
        crlf_content = self.original.replace("\n", "\r\n")
        self.kustomization.write_bytes(crlf_content.encode("utf-8"))

        self.update()

        raw = self.kustomization.read_bytes()
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_repository_overlay_has_exactly_one_mapping_for_every_inventory_service(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        overlay = repository_root / "k8s" / "overlays" / "homelab" / "kustomization.yaml"
        inventory = repository_root / "ops" / "images" / "service-images.json"
        original = overlay.read_text(encoding="utf-8")

        for index, service in enumerate(sorted(load_allowed_services(inventory)), start=5):
            replacement = "sha256:" + format(index, "x") * 64
            updated, result = _replace_digest(original, service, replacement, None)

            self.assertTrue(result.changed)
            self.assertEqual(1, updated.count(replacement))
            original_lines = original.splitlines()
            updated_lines = updated.splitlines()
            self.assertEqual(1, sum(a != b for a, b in zip(original_lines, updated_lines)))


if __name__ == "__main__":
    unittest.main()
