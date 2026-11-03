#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - NIST SP 800-92, Guide to Computer Security Log Management:
#   integrity checking of log archives is required.
#   https://csrc.nist.gov/pubs/sp/800/92/final
# - Hash chain tamper-evident logging:
#   https://auditbuffet.com/patterns/ab-001387
# - Python datetime timezone-aware guidance:
#   https://docs.python.org/3/library/datetime.html#datetime.datetime.now
# ==============================================================================
# DESIGN:
#   entry_hash = SHA256(prev_hash || canonical_json(payload))
#   GENESIS = 64 zeroes. verify_chain() replays the chain and returns the
#   first line number at which the recomputation diverges from the claimed
#   hash — i.e. it detects a modified, deleted, or reordered middle entry.
# ==============================================================================

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path(os.environ.get("AUDIT_LOG_PATH", "/app/workspace/audit_trail.log"))
GENESIS = "0" * 64


def canonical(obj: dict) -> bytes:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def append_event(event_type: str, details: dict) -> dict:
    """Append one hash-chained entry to LOG_FILE; return the entry."""
    prev_hash = GENESIS
    if LOG_FILE.is_file():
        lines = [ln for ln in LOG_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if lines:
            prev_hash = json.loads(lines[-1])["entry_hash"]

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "details": details,
        "prev_hash": prev_hash,
    }
    entry_hash = hashlib.sha256(prev_hash.encode("ascii") + canonical(payload)).hexdigest()
    entry = {**payload, "entry_hash": entry_hash}

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
    return entry


def verify_chain() -> int:
    """
    Replay the chain and report the first break.
    Exit 0 = intact; 2 = broken.
    """
    if not LOG_FILE.is_file():
        print("[WARN] No audit log yet; nothing to verify.")
        return 0
    prev_hash = GENESIS
    lineno = 0
    for lineno, line in enumerate(LOG_FILE.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        entry = json.loads(line)
        claimed = entry.pop("entry_hash", None)
        payload_prev = entry.get("prev_hash")
        if payload_prev != prev_hash:
            print(f"[BROKEN] line {lineno}: prev_hash mismatch", file=sys.stderr)
            return 2
        recomputed = hashlib.sha256(prev_hash.encode("ascii") + canonical(entry)).hexdigest()
        if recomputed != claimed:
            print(f"[BROKEN] line {lineno}: entry_hash mismatch", file=sys.stderr)
            return 2
        prev_hash = claimed
    print(f"[OK] Hash chain intact ({lineno} entries).")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "verify":
        raise SystemExit(verify_chain())
    append_event("INITIALIZATION", {"msg": "hash-chained audit logger ready"})
    print("Logged initialization event.")
