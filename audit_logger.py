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
# - Python fcntl advisory locking:
#   https://docs.python.org/3/library/fcntl.html
# - Python os.replace atomic rename:
#   https://docs.python.org/3/library/os.html#os.replace
# ==============================================================================
# DESIGN:
#   entry_hash = SHA256(prev_hash || canonical_json(payload))
#   GENESIS = 64 zeroes. Each new entry records seq (1-based position) and
#   instance (per-process nonce). verify_chain() replays the chain and returns
#   the first line number at which the recomputation diverges from the claimed
#   hash, detects deleted/reordered entries, and checks seq when present.
#
#   The chain is tamper-EVIDENT, not tamper-PROOF. A writer with access to the
#   log can rewrite the whole chain from genesis. write_anchor() exports the
#   current count and last hash so the operator can store that value off-box.
#   verify_chain(anchor_path) then detects any rewrite that does not also
#   reproduce the anchored count and hash.
# ==============================================================================

import argparse
import fcntl
import hashlib
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path(os.environ.get("AUDIT_LOG_PATH", "/app/workspace/audit_trail.log"))
GENESIS = "0" * 64
INSTANCE = os.environ.get("AUDIT_INSTANCE_ID", uuid.uuid4().hex)


def _default_anchor() -> Path:
    explicit = os.environ.get("AUDIT_ANCHOR_PATH")
    if explicit:
        return Path(explicit)
    return Path(str(LOG_FILE) + ".anchor")


def canonical(obj: dict) -> bytes:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _die(msg: str, code: int = 2) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    raise SystemExit(code)


@contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(path) + ".lock")
    fh = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def _read_entries(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    entries: list[dict] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            _die(f"malformed JSON at {path}:{lineno}: {exc}")
        if not isinstance(entry, dict):
            _die(f"non-object entry at {path}:{lineno}")
        entries.append(entry)
    return entries


def append_event(event_type: str, details: dict) -> dict:
    """Append one hash-chained entry to LOG_FILE; return the entry."""
    with _exclusive_lock(LOG_FILE):
        entries = _read_entries(LOG_FILE)
        if entries:
            try:
                prev_hash = entries[-1]["entry_hash"]
            except KeyError:
                _die(f"last entry has no entry_hash: {LOG_FILE}")
            try:
                seq = int(entries[-1].get("seq", len(entries))) + 1
            except (TypeError, ValueError):
                _die(f"last entry has invalid seq: {LOG_FILE}")
        else:
            prev_hash = GENESIS
            seq = 1

        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "details": details,
            "prev_hash": prev_hash,
            "seq": seq,
            "instance": INSTANCE,
        }
        entry_hash = hashlib.sha256(
            prev_hash.encode("ascii") + canonical(payload)
        ).hexdigest()
        entry = {**payload, "entry_hash": entry_hash}

        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return entry


def _check_anchor(anchor_path: Path, count: int, last_hash: str) -> int:
    if not anchor_path.is_file():
        print(f"[BROKEN] anchor missing: {anchor_path}", file=sys.stderr)
        return 2
    try:
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[BROKEN] anchor unreadable: {anchor_path}: {exc}", file=sys.stderr)
        return 2
    if anchor.get("count") != count or anchor.get("last_hash") != last_hash:
        print(f"[BROKEN] anchor mismatch: {anchor_path}", file=sys.stderr)
        print(f"  anchor count={anchor.get('count')} hash={anchor.get('last_hash')}",
              file=sys.stderr)
        print(f"  actual count={count} hash={last_hash}", file=sys.stderr)
        return 2
    print(f"[OK] Anchor matches ({anchor_path}).")
    return 0


def verify_chain(anchor_path: Path | str | None = None) -> int:
    """
    Replay the chain and report the first break.
    Exit 0 = intact; 2 = broken or anchor mismatch.
    """
    if not LOG_FILE.is_file():
        print("[WARN] No audit log yet; nothing to verify.")
        if anchor_path is None:
            return 0
        return _check_anchor(Path(anchor_path), 0, GENESIS)

    prev_hash = GENESIS
    lineno = 0
    for lineno, line in enumerate(LOG_FILE.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"[BROKEN] line {lineno}: malformed JSON: {exc}", file=sys.stderr)
            return 2
        if not isinstance(entry, dict):
            print(f"[BROKEN] line {lineno}: non-object entry", file=sys.stderr)
            return 2
        claimed = entry.pop("entry_hash", None)
        payload_prev = entry.get("prev_hash")
        if payload_prev != prev_hash:
            print(f"[BROKEN] line {lineno}: prev_hash mismatch", file=sys.stderr)
            return 2
        if "seq" in entry:
            try:
                seq = int(entry["seq"])
            except (TypeError, ValueError):
                print(f"[BROKEN] line {lineno}: invalid seq", file=sys.stderr)
                return 2
            if seq != lineno:
                print(f"[BROKEN] line {lineno}: seq mismatch (got {seq})", file=sys.stderr)
                return 2
        recomputed = hashlib.sha256(prev_hash.encode("ascii") + canonical(entry)).hexdigest()
        if recomputed != claimed:
            print(f"[BROKEN] line {lineno}: entry_hash mismatch", file=sys.stderr)
            return 2
        prev_hash = claimed

    print(f"[OK] Hash chain intact ({lineno} entries).")
    if anchor_path is None:
        return 0
    return _check_anchor(Path(anchor_path), lineno, prev_hash)


def write_anchor(path: Path | str | None = None) -> Path:
    """Write the current chain tip to a separate anchor file (0444)."""
    anchor_path = Path(path) if path is not None else _default_anchor()
    with _exclusive_lock(LOG_FILE):
        entries = _read_entries(LOG_FILE)
    last_hash = entries[-1]["entry_hash"] if entries else GENESIS
    payload = {
        "count": len(entries),
        "last_hash": last_hash,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "instance": INSTANCE,
        "log_file": str(LOG_FILE),
    }
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(anchor_path) + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.chmod(tmp, 0o444)
    if anchor_path.exists():
        os.chmod(anchor_path, 0o644)
    os.replace(tmp, anchor_path)
    print(f"[OK] anchor written: {anchor_path} (count={payload['count']}, "
          f"last_hash={last_hash})")
    return anchor_path


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--anchor", nargs="?", const="__default__", default=None,
                          help="verify against an anchor file")

    p_anchor = sub.add_parser("anchor")
    p_anchor.add_argument("--path", default=None,
                          help="anchor output path (default: LOG_FILE.anchor)")

    args = ap.parse_args()

    if args.cmd == "verify":
        anchor = _default_anchor() if args.anchor == "__default__" else args.anchor
        return verify_chain(anchor)
    if args.cmd == "anchor":
        write_anchor(args.path)
        return 0

    append_event("INITIALIZATION", {"msg": "hash-chained audit logger ready"})
    print("Logged initialization event.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
