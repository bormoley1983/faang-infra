"""Prevent copied DEP-051 boundary sources drifting from their current inputs."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOMELAB = ROOT / "k8s" / "overlays" / "homelab"
BOUNDARIES = HOMELAB / "boundaries"


def content(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


class BoundarySourceEquivalenceTests(unittest.TestCase):
    def assert_same(self, original: Path, copied: Path) -> None:
        self.assertEqual(content(original), content(copied), f"source drift: {original.relative_to(ROOT)}")

    def test_homelab_patches_and_namespace_are_copied_exactly(self):
        pairs = (
            (HOMELAB / "namespace.yaml", BOUNDARIES / "runtime-foundation/resources/namespace.yaml"),
            (HOMELAB / "configmap.yaml", BOUNDARIES / "runtime-foundation/configmap.yaml"),
            (HOMELAB / "ingress-patch.yaml", BOUNDARIES / "workloads/ingress-patch.yaml"),
            (ROOT / "k8s/base/configmap.yaml", BOUNDARIES / "runtime-foundation/resources/configmap.yaml"),
            (ROOT / "k8s/base/ingress.yaml", BOUNDARIES / "workloads/resources/ingress.yaml"),
            (ROOT / "k8s/base/application-deployment-defaults.yaml", BOUNDARIES / "workloads/application-deployment-defaults.yaml"),
        )
        for original, copied in pairs:
            with self.subTest(original=original.name):
                self.assert_same(original, copied)

    def test_workload_and_bootstrap_sources_are_copied_exactly(self):
        for original in sorted((ROOT / "k8s/base").glob("*-service.yaml")):
            with self.subTest(original=original.name):
                self.assert_same(original, BOUNDARIES / "workloads/resources" / original.name)
        for original in sorted((ROOT / "k8s/bootstrap").rglob("*")):
            if original.is_file() and original.name != "kustomization.yaml":
                with self.subTest(original=original.name):
                    self.assert_same(original, BOUNDARIES / "bootstrap" / original.relative_to(ROOT / "k8s/bootstrap"))

    def test_selected_dependency_sources_are_copied_exactly(self):
        for dependency in ("postgresql", "redis", "elasticsearch", "kafka"):
            source = ROOT / "k8s/components/dependencies" / dependency / "external"
            for original in sorted(source.rglob("*")):
                if original.is_file():
                    with self.subTest(dependency=dependency, original=original.name):
                        self.assert_same(
                            original,
                            BOUNDARIES / "selected-dependencies" / dependency / original.relative_to(source),
                        )
        self.assert_same(
            ROOT / "k8s/components/dependencies/s3/internal/s3.yaml",
            BOUNDARIES / "retained-s3-main/s3.yaml",
        )


if __name__ == "__main__":
    unittest.main()
