"""Contracts for the read-only dependency profile command family."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ops/dependencies/profilectl.py"
SPEC = importlib.util.spec_from_file_location("dependency_profilectl", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")
PROFILECTL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROFILECTL
SPEC.loader.exec_module(PROFILECTL)
EXAMPLE = ROOT / "config/homelab.example.json"


class DependencyProfileCliTests(unittest.TestCase):
    def test_current_example_status_is_redacted_and_truthful(self):
        status = PROFILECTL.status_data(EXAMPLE, allow_documentation_addresses=True)
        self.assertEqual("none", status["mutation"])
        self.assertEqual("external", status["dependencies"]["postgresql"]["selectedMode"])
        self.assertEqual("internal", status["dependencies"]["s3"]["selectedMode"])
        self.assertTrue(status["dependencies"]["s3"]["ready"])
        self.assertNotIn("address", str(status).lower())
        self.assertNotIn("password", str(status).lower())

    def test_unsupported_internal_profiles_fail_during_plan_not_mutation(self):
        for dependency in ("postgresql", "redis", "kafka", "elasticsearch"):
            with self.subTest(dependency=dependency):
                plan = PROFILECTL.plan_data(
                    EXAMPLE,
                    dependency,
                    "internal",
                    allow_documentation_addresses=True,
                )
                self.assertFalse(plan["deployable"])
                self.assertEqual("complete-production-profile-acceptance", plan["nextAction"])
                self.assertEqual("none", plan["mutation"])

    def test_supported_modes_are_explicit(self):
        readiness = PROFILECTL.load_readiness()
        self.assertEqual(
            {"postgresql", "redis", "elasticsearch", "kafka", "s3"},
            set(readiness),
        )
        for dependency in readiness.values():
            self.assertEqual({"internal", "external"}, set(dependency))
        self.assertTrue(readiness["s3"]["internal"]["ready"])
        self.assertTrue(all(readiness[name]["external"]["ready"] for name in readiness))

    def test_command_source_has_no_deployment_or_deletion_primitive(self):
        source = MODULE_PATH.read_text(encoding="utf-8").lower()
        for forbidden in ("kubectl apply", "kubectl delete", "argocd app sync", "docker compose up"):
            self.assertNotIn(forbidden, source)
        self.assertIn("mutation: none", source)


if __name__ == "__main__":
    unittest.main()
