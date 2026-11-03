#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - NIST SP 800-92 (log integrity checking):
#   https://csrc.nist.gov/pubs/sp/800/92/final
# - Hash chain tamper-evident pattern:
#   https://auditbuffet.com/patterns/ab-001387
# - Python tempfile.TemporaryDirectory:
#   https://docs.python.org/3/library/tempfile.html#tempfile.TemporaryDirectory
# ==============================================================================
# BEHAVIOUR:
#   Proves that an off-box anchor detects appends and rewrites that the
#   in-file hash chain alone would accept. Also proves legacy entries without
#   seq/instance still verify, so existing volumes remain readable.
# ==============================================================================

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import audit_logger


class AuditAnchorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory()
        self.log = Path(self.td.name) / "audit_trail.log"
        self.anchor = Path(self.td.name) / "audit.anchor"
        self._orig_log = audit_logger.LOG_FILE
        audit_logger.LOG_FILE = self.log

    def tearDown(self) -> None:
        audit_logger.LOG_FILE = self._orig_log
        self.td.cleanup()

    def test_seq_is_monotonic(self) -> None:
        audit_logger.append_event("T1", {"i": 1})
        audit_logger.append_event("T2", {"i": 2})
        entries = [json.loads(line) for line in
                   self.log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["seq"] for e in entries], [1, 2])

    def test_anchor_detects_append(self) -> None:
        audit_logger.append_event("T1", {"i": 1})
        audit_logger.append_event("T2", {"i": 2})
        self.assertEqual(audit_logger.verify_chain(), 0)
        audit_logger.write_anchor(self.anchor)
        self.assertEqual(audit_logger.verify_chain(self.anchor), 0)

        audit_logger.append_event("T3", {"i": 3})
        self.assertEqual(audit_logger.verify_chain(), 0)
        self.assertNotEqual(audit_logger.verify_chain(self.anchor), 0)

        audit_logger.write_anchor(self.anchor)
        self.assertEqual(audit_logger.verify_chain(self.anchor), 0)

    def test_anchor_detects_rewrite(self) -> None:
        audit_logger.append_event("T1", {"i": 1})
        audit_logger.append_event("T2", {"i": 2})
        audit_logger.write_anchor(self.anchor)

        lines = self.log.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[1])
        entry["details"]["i"] = 999
        lines[1] = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")

        self.assertNotEqual(audit_logger.verify_chain(self.anchor), 0)

    def test_missing_anchor_fails_closed(self) -> None:
        audit_logger.append_event("T1", {"i": 1})
        self.assertEqual(audit_logger.verify_chain(self.anchor), 2)

    def test_legacy_entries_without_seq_still_verify(self) -> None:
        prev = audit_logger.GENESIS
        lines = []
        for idx in (1, 2):
            payload = {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "event_type": f"LEGACY{idx}",
                "details": {"i": idx},
                "prev_hash": prev,
            }
            entry_hash = hashlib.sha256(
                prev.encode("ascii") + audit_logger.canonical(payload)
            ).hexdigest()
            entry = {**payload, "entry_hash": entry_hash}
            lines.append(json.dumps(entry, sort_keys=True, ensure_ascii=False))
            prev = entry_hash
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(audit_logger.verify_chain(), 0)

        audit_logger.append_event("T3", {"i": 3})
        self.assertEqual(audit_logger.verify_chain(), 0)


if __name__ == "__main__":
    unittest.main()
