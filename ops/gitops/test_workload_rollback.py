import unittest
from pathlib import Path


RUNBOOK = Path(__file__).with_name("workload-rollback.md")


class WorkloadRollbackRunbookTests(unittest.TestCase):
    def test_runbook_is_workload_only_and_requires_no_prune_manual_sync(self):
        source = RUNBOOK.read_text(encoding="utf-8")
        for required in (
            "faang-workloads", "--prune=false", "Eligibility gate",
            "Mandatory stops", "argocd app diff", "argocd app wait",
            "s3-main", "Git revert cannot undo",
        ):
            self.assertIn(required, source)
        for forbidden in ("--force", "--replace"):
            self.assertNotIn(forbidden, source.lower())


if __name__ == "__main__":
    unittest.main()
