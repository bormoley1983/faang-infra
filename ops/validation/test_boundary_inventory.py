from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))
import check_boundary_inventory as INVENTORY


class BoundaryInventoryTests(unittest.TestCase):
    def test_children_are_an_exact_non_overlapping_partition(self):
        total, counts = INVENTORY.check()
        self.assertEqual(38, total)
        self.assertEqual(
            {
                "runtime-foundation": 2,
                "selected-dependencies": 9,
                "retained-s3-main": 2,
                "bootstrap": 6,
                "workloads": 19,
            },
            counts,
        )


if __name__ == "__main__":
    unittest.main()
