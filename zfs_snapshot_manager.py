#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - OpenZFS zfs-hold prevents destroy (EBUSY):
#   https://openzfs.github.io/openzfs-docs/man/8/zfs-hold.8.html
# - OpenZFS rollback is destructive; -r/-R destroy intermediate snapshots
#   and dependent clones:
#   https://openzfs.github.io/openzfs-docs/man/8/zfs-rollback.8.html
# - Safe restore practice: clone first, verify, rollback last.
#   https://github.com/serversathome/homelabhero
# ==============================================================================
# COMPATIBILITY SHIM:
#   This filename is retained for operators who already call it. All logic
#   now lives in snapshot_manager.py with an explicit --backend zfs. New
#   deployments should call:
#
#       python3 snapshot_manager.py --backend zfs create NAME
#
#   This shim emits a deprecation warning on stderr and then delegates.
# ==============================================================================

import argparse
import sys

import snapshot_manager as sm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=sm.ZFS_DATASET)
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
    print("[WARN] zfs_snapshot_manager.py is deprecated; use "
          "snapshot_manager.py --backend zfs", file=sys.stderr)

    if not sm.zfs_available():
        sm.die("zfs backend requested but 'zfs list' failed")

    if args.cmd == "create":
        sm.zfs_create(args.dataset, args.snapshot)
    elif args.cmd == "hold":
        sm.zfs_hold(args.dataset, args.snapshot)
    elif args.cmd == "clone":
        sm.zfs_clone(args.dataset, args.snapshot, args.clone_name)
    elif args.cmd == "rollback":
        sm.zfs_rollback(args.dataset, args.snapshot, args.confirm)


if __name__ == "__main__":
    main()
