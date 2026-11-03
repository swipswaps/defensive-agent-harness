#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - OpenZFS zfs-hold prevents destroy (EBUSY):
#   https://openzfs.github.io/openzfs-docs/man/8/zfs-hold.8.html
# - OpenZFS rollback is destructive; -r/-R destroy intermediate snapshots
#   and dependent clones:
#   https://openzfs.github.io/openzfs-docs/man/8/zfs-rollback.8.html
# - Safe restore: clone first, verify, rollback last.
#   https://github.com/serversathome/homelabhero
# - zfs-fuse is deprecated and must not be used under any circumstance:
#   https://openzfs.github.io/openzfs-docs/Getting%20Started/Fedora/
# - tar(1) as a portable, non-destructive snapshot primitive:
#   https://www.gnu.org/software/tar/manual/
# - Python Popen(start_new_session=True):
#   https://docs.python.org/3/library/subprocess.html#subprocess.Popen
# ==============================================================================
# DESIGN:
#   Two backends. 'tar' is the default and always available; it produces a
#   read-only archive directory that acts as a hold-equivalent (the archive
#   is never modified in place). 'zfs' is used only when kernel OpenZFS is
#   present; it applies a hold immediately and defaults to clone, not
#   rollback.
# ==============================================================================

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

TAR_ROOT = Path("./snapshots")
ZFS_DATASET = "tank/sandbox/target_env"


def die(msg: str, code: int = 2) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    raise SystemExit(code)


def _run(argv: list[str], timeout: int = 120) -> str:
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        die(f"timeout: {' '.join(argv)}", 3)
    if proc.returncode != 0:
        die(f"rc={proc.returncode}: {' '.join(argv)}\n{err}")
    return out


def zfs_available() -> bool:
    try:
        _run(["zfs", "list"], timeout=10)
        return True
    except SystemExit:
        return False


def tar_create(name: str) -> None:
    TAR_ROOT.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = TAR_ROOT / f"{name}_{stamp}.tar"
    src = Path("./target_environment")
    if not src.is_dir():
        die(f"source directory missing: {src}")
    with tarfile.open(archive, "w") as tf:
        tf.add(src, arcname="target_environment")
    os.chmod(archive, 0o444)  # read-only: hold-equivalent
    print(f"[OK] tar snapshot: {archive} (read-only)")


def tar_clone(name: str, dest: str) -> None:
    matches = sorted(TAR_ROOT.glob(f"{name}_*.tar"))
    if not matches:
        die(f"no snapshot matching {name}_*.tar")
    archive = matches[-1]
    out = TAR_ROOT / dest
    out.mkdir(exist_ok=False)
    with tarfile.open(archive, "r") as tf:
        tf.extractall(out)
    print(f"[OK] extracted to {out} (inspect read-only)")


def zfs_create(name: str) -> None:
    full = f"{ZFS_DATASET}@{name}"
    _run(["zfs", "snapshot", full])
    _run(["zfs", "hold", "defensive-harness", full])
    print(f"[OK] zfs snapshot held: {full}")


def zfs_clone(name: str, dest: str) -> None:
    src = f"{ZFS_DATASET}@{name}"
    parent = ZFS_DATASET.rsplit("/", 1)[0]
    _run(["zfs", "clone", src, f"{parent}/{dest}"])
    print(f"[OK] zfs clone: {parent}/{dest} (mount read-only)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["tar", "zfs"], default=None)
    ap.add_argument("--zfs-dataset", default=ZFS_DATASET)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create"); p_create.add_argument("name")
    p_clone  = sub.add_parser("clone");  p_clone.add_argument("name"); p_clone.add_argument("dest")
    p_list   = sub.add_parser("list")

    args = ap.parse_args()

    if args.cmd == "list":
        for p in sorted(TAR_ROOT.glob("*.tar")):
            print(p)
        if zfs_available():
            _run(["zfs", "list", "-t", "snapshot", "-o", "name", "-r", args.zfs_dataset], timeout=30)
        return

    backend = args.backend
    if backend is None:
        backend = "zfs" if zfs_available() else "tar"
    print(f"[INFO] backend={backend}")

    if args.cmd == "create":
        (zfs_create if backend == "zfs" else tar_create)(args.name)
    elif args.cmd == "clone":
        (zfs_clone if backend == "zfs" else tar_clone)(args.name, args.dest)


if __name__ == "__main__":
    main()
