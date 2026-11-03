#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - OpenZFS zfs-hold: hold prevents destroy; destroy returns EBUSY.
#   https://openzfs.github.io/openzfs-docs/man/8/zfs-hold.8.html
# - OpenZFS zfs rollback: -r/-R destroy intermediate snapshots and clones.
#   https://openzfs.github.io/openzfs-docs/man/8/zfs-rollback.8.html
# - Safe restore practice: clone first, verify, rollback last.
#   https://github.com/serversathome/homelabhero
# ==============================================================================
# DESIGN NOTES (verbose):
#   create() applies a hold IMMEDIATELY after snapshot creation. A held
#   snapshot cannot be destroyed by `zfs destroy` until the hold is
#   released; this makes accidental destruction of the baseline fail with
#   EBUSY instead of silently succeeding.
#
#   clone() is the DEFAULT recovery path. It creates a NEW dataset from
#   the snapshot, leaving the original snapshot and ALL newer snapshots
#   untouched. The user mounts the clone read-only, inspects it, and only
#   then decides whether to promote it or accept destructive rollback.
#
#   rollback() requires --confirm. It deliberately does NOT pass -r or -R:
#   those flags destroy intermediate snapshots and dependent clones, which
#   is exactly the behaviour a defensive harness must prevent by default.
# ==============================================================================

import argparse
import subprocess
import sys

DEFAULT_DATASET = "tank/sandbox/target_env"


def _popen(argv: list[str]) -> subprocess.Popen:
    """All ZFS calls via Popen, never subprocess.run."""
    return subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True)


def _check(argv: list[str], what: str) -> None:
    """Run one ZFS command with a 60s timeout; fail closed on non-zero."""
    proc = _popen(argv)
    try:
        out, err = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        print(f"[FATAL] {what} timed out", file=sys.stderr)
        raise SystemExit(3)
    if proc.returncode != 0:
        print(f"[FATAL] {what} failed rc={proc.returncode}\n{err}", file=sys.stderr)
        raise SystemExit(proc.returncode)
    if out:
        print(out, end="")


def create(dataset: str, snap: str) -> None:
    full = f"{dataset}@{snap}"
    _check(["zfs", "snapshot", full], f"snapshot {full}")
    _check(["zfs", "hold", "defensive-harness", full], f"hold {full}")
    print(f"[OK] Created and held {full}")


def hold(dataset: str, snap: str) -> None:
    full = f"{dataset}@{snap}"
    _check(["zfs", "hold", "defensive-harness", full], f"hold {full}")


def clone(dataset: str, snap: str, clone_name: str) -> None:
    """Non-destructive recovery: clone to a new dataset for read-only review."""
    src = f"{dataset}@{snap}"
    dst = f"{dataset.rsplit('/', 1)[0]}/{clone_name}"
    _check(["zfs", "clone", src, dst], f"clone {src} -> {dst}")
    print(f"[OK] Clone ready: {dst}  (mount read-only and inspect)")


def rollback(dataset: str, snap: str, confirm: bool) -> None:
    if not confirm:
        print("[REFUSED] rollback is destructive. Re-run with --confirm after "
              "cloning and inspecting. See README.txt Step 7.", file=sys.stderr)
        raise SystemExit(2)
    full = f"{dataset}@{snap}"
    _check(["zfs", "rollback", full], f"rollback {full}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=DEFAULT_DATASET)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("snapshot")

    p_hold = sub.add_parser("hold")
    p_hold.add_argument("snapshot")

    p_clone = sub.add_parser("clone")
    p_clone.add_argument("snapshot")
    p_clone.add_argument("clone_name")

    p_rb = sub.add_parser("rollback")
    p_rb.add_argument("snapshot")
    p_rb.add_argument("--confirm", action="store_true")

    args = ap.parse_args()
    if args.cmd == "create":
        create(args.dataset, args.snapshot)
    elif args.cmd == "hold":
        hold(args.dataset, args.snapshot)
    elif args.cmd == "clone":
        clone(args.dataset, args.snapshot, args.clone_name)
    elif args.cmd == "rollback":
        rollback(args.dataset, args.snapshot, args.confirm)


if __name__ == "__main__":
    main()
