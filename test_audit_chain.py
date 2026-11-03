#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - NIST SP 800-92 (log integrity checking):
#   https://csrc.nist.gov/pubs/sp/800/92/final
# - Hash chain tamper-evident pattern:
#   https://auditbuffet.com/patterns/ab-001387
# - tempfile.TemporaryDirectory (self-cleaning):
#   https://docs.python.org/3/library/tempfile.html#tempfile.TemporaryDirectory
# ==============================================================================
# BEHAVIOUR:
#   Exit 0 = tamper-detection works.
#   Exit 2 = tamper was NOT detected or initial chain was invalid.
# ==============================================================================

import json
import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        os.environ["AUDIT_LOG_PATH"] = str(Path(td) / "audit_trail.log")
        import audit_logger
        audit_logger.LOG_FILE = Path(os.environ["AUDIT_LOG_PATH"])

        audit_logger.append_event("T1", {"i": 1})
        audit_logger.append_event("T2", {"i": 2})
        audit_logger.append_event("T3", {"i": 3})

        rc = audit_logger.verify_chain()
        if rc != 0:
            print("[TEST] FAIL: initial chain did not verify", file=sys.stderr)
            return 2
        print("[TEST] initial chain verified")

        # Tamper with the middle entry's payload without touching entry_hash.
        lines = audit_logger.LOG_FILE.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[1])
        entry["details"]["i"] = 999
        lines[1] = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        audit_logger.LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

        rc = audit_logger.verify_chain()
        if rc == 0:
            print("[TEST] FAIL: tamper was not detected", file=sys.stderr)
            return 2
        print("[TEST] tamper detected (verify returned non-zero)")

        # Delete the middle entry and re-verify; the chain must also break.
        lines = audit_logger.LOG_FILE.read_text(encoding="utf-8").splitlines()
        del lines[1]
        audit_logger.LOG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rc = audit_logger.verify_chain()
        if rc == 0:
            print("[TEST] FAIL: deletion was not detected", file=sys.stderr)
            return 2
        print("[TEST] deletion detected (verify returned non-zero)")

    print("[TEST] PASS: audit chain is tamper-evident")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
