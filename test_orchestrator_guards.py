#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - Fail-closed design (avoid vacuous success):
#   https://csrc.nist.gov/pubs/sp/800/160/v1/r1/final
# - Python pathlib:
#   https://docs.python.org/3/library/pathlib.html
# - Python tempfile.TemporaryDirectory:
#   https://docs.python.org/3/library/tempfile.html#tempfile.TemporaryDirectory
# ==============================================================================
# BEHAVIOUR:
#   Proves that an absent or empty target is rejected before a probe, and
#   that --allow-empty-target is the only way to proceed with an empty target.
# ==============================================================================

import tempfile
import unittest
from pathlib import Path

import harness_orchestrator as ho


class TargetGuardTests(unittest.TestCase):
    def test_missing_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing"
            with self.assertRaises(SystemExit) as cm:
                ho.verify_target(missing)
            self.assertEqual(cm.exception.code, 2)

    def test_empty_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty"
            empty.mkdir()
            with self.assertRaises(SystemExit) as cm:
                ho.verify_target(empty)
            self.assertEqual(cm.exception.code, 2)

    def test_gitkeep_only_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty"
            empty.mkdir()
            (empty / ".gitkeep").write_text("", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                ho.verify_target(empty)
            self.assertEqual(cm.exception.code, 2)

    def test_allow_empty_target_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            empty = Path(td) / "empty"
            empty.mkdir()
            entries = ho.verify_target(empty, allow_empty=True)
            self.assertEqual(entries, [])

    def test_populated_target_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.mkdir()
            (target / "artifact.txt").write_text("x\n", encoding="utf-8")
            entries = ho.verify_target(target)
            self.assertEqual([p.name for p in entries], ["artifact.txt"])


if __name__ == "__main__":
    unittest.main()
