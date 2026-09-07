"""DEP-051 staged Argo child-boundary contracts; none are live-registered."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STAGED = ROOT / "ops" / "argocd" / "staged-boundaries"
REGISTERED = (ROOT / "ops" / "argocd" / "kustomization.yaml").read_text(encoding="utf-8")


class StagedBoundaryTests(unittest.TestCase):
    def test_staged_projects_are_least_privilege_and_manual(self):
        expected = {
            "runtime-foundation": ("30", "runtime-foundation"),
            "selected-dependencies": ("10", "selected-dependencies"),
            "bootstrap": ("40", "bootstrap"),
            "workloads": ("50", "workloads"),
        }
        for boundary, (wave, source) in expected.items():
            project = (STAGED / f"{boundary}-project.yaml").read_text(encoding="utf-8")
            application = (STAGED / f"{boundary}-application.yaml").read_text(encoding="utf-8")
            self.assertIn("namespace: faang", project)
            self.assertIn(f'argocd.argoproj.io/sync-wave: "{wave}"', application)
            self.assertIn(f"path: k8s/overlays/homelab/boundaries/{source}", application)
            self.assertNotIn("automated:", application)
            self.assertNotIn("prune:", application)
            self.assertNotIn("selfHeal:", application)
            self.assertNotIn(f"{boundary}-application.yaml", REGISTERED)
            self.assertNotIn(f"{boundary}-project.yaml", REGISTERED)

    def test_staged_manual_root_only_targets_argo_objects(self):
        project = (ROOT / "ops" / "argocd" / "staged-gitops-root-project.yaml").read_text(encoding="utf-8")
        application = (ROOT / "ops" / "argocd" / "staged-gitops-root-application.yaml").read_text(encoding="utf-8")
        self.assertIn("namespace: argocd", project)
        self.assertIn("kind: Application", project)
        self.assertIn("kind: AppProject", project)
        self.assertIn("path: ops/argocd/staged-boundaries", application)
        self.assertIn("namespace: argocd", application)
        self.assertNotIn("automated:", application)
        self.assertNotIn("prune:", application)
        self.assertNotIn("selfHeal:", application)
        self.assertNotIn("staged-gitops-root-project.yaml", REGISTERED)
        self.assertNotIn("staged-gitops-root-application.yaml", REGISTERED)


if __name__ == "__main__":
    unittest.main()
