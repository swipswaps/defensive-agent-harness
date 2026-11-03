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
# - tarfile extraction security (path traversal, links, devices):
#   https://docs.python.org/3/library/tarfile.html#tarfile.TarFile.extract
#   https://docs.python.org/3/library/tarfile.html#tarfile.TarFile.extractall
# - OpenZFS project documentation:
#   https://openzfs.github.io/openzfs-docs/
# - Python Popen(start_new_session=True):
#   https://docs.python.org/3/library/subprocess.html#subprocess.Popen
# ==============================================================================
# DESIGN:
#   Two backends. 'tar' is the default because it is portable and never
#   performs an in-place rollback. 'zfs' is opt-in and requires a working
#   kernel OpenZFS. There is no silent backend auto-selection: the operator
#   must know which storage primitive will be used.
#
#   tar_create() refuses symlinks and special files in the source tree and
#   writes a read-only archive (0444). tar_clone() never calls extractall();
#   it validates every member (regular file or directory), rejects absolute
#   paths, '..' traversal, links, devices, FIFOs, and oversized members, and
#   then copies file objects into a newly created destination.
#
#   zfs_create() applies a hold immediately. zfs_clone() is the default
#   recovery path. zfs_rollback() requires --confirm and never passes -r/-R.
# ==============================================================================

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

TAR_ROOT = Path(os.environ.get("SNAPSHOT_ROOT", "./snapshots"))
TARGET_DIR = Path(os.environ.get("SNAPSHOT_TARGET", "./target_environment"))
ZFS_DATASET = os.environ.get("SNAPSHOT_ZFS_DATASET", "tank/sandbox/target_env")
MAX_MEMBER_BYTES = int(os.environ.get("SNAPSHOT_MAX_MEMBER_BYTES", str(4 * 1024**3)))
MAX_TOTAL_BYTES = int(os.environ.get("SNAPSHOT_MAX_TOTAL_BYTES", str(8 * 1024**3)))


def die(msg: str, code: int = 2) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    raise SystemExit(code)


def _safe_component(value: str, what: str) -> str:
    if not value or value in (".", ".."):
        die(f"invalid {what}: {value!r}")
    if "/" in value or "\\" in value or value.startswith("-"):
        die(f"invalid {what}: {value!r}")
    return value


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


def _command_ok(argv: list[str], timeout: int = 10) -> bool:
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return False
    return proc.returncode == 0


def zfs_available() -> bool:
    return _command_ok(["zfs", "list"], timeout=10)


def _entries(path: Path) -> list[Path]:
    if not path.is_dir():
        die(f"target directory missing: {path}")
    return [p for p in path.iterdir() if p.name not in (".gitkeep", ".gitignore")]


def _check_source_tree(src: Path) -> int:
    if not src.is_dir():
        die(f"source directory missing: {src}")
    count = 0
    for root, dirs, files in os.walk(src, followlinks=False):
        root_path = Path(root)
        for name in dirs + files:
            p = root_path / name
            if p.is_symlink():
                die(f"source contains symlink, refusing snapshot: {p}")
            if p.is_file() or p.is_dir():
                if name not in (".gitkeep", ".gitignore"):
                    count += 1
                continue
            die(f"source contains special file, refusing snapshot: {p}")
    if count == 0:
        die(f"source directory is empty: {src}")
    return count


def _validate_member(member: tarfile.TarInfo, dest: Path) -> tuple[Path, int]:
    if member.issym() or member.islnk():
        die(f"archive contains link, refusing extraction: {member.name}")
    if member.ischr() or member.isblk() or member.isfifo():
        die(f"archive contains device/FIFO, refusing extraction: {member.name}")
    if not (member.isdir() or member.isfile()):
        die(f"archive contains unsupported member type: {member.name}")
    if member.size > MAX_MEMBER_BYTES:
        die(f"archive member too large: {member.name} ({member.size} bytes)")

    parts = [p for p in PurePosixPath(member.name).parts if p not in ("", ".")]
    if not parts:
        die(f"archive contains empty member name: {member.name!r}")
    if any(p == ".." for p in parts):
        die(f"archive member escapes destination: {member.name!r}")
    if PurePosixPath(member.name).is_absolute():
        die(f"archive member uses absolute path: {member.name!r}")

    target = dest.joinpath(*parts).resolve()
    dest_resolved = dest.resolve()
    try:
        target.relative_to(dest_resolved)
    except ValueError:
        die(f"archive member escapes destination: {member.name!r}")
    return target, member.size


def safe_extract(archive: Path, dest: Path) -> int:
    """Extract a tar archive without extractall() and without links/devices."""
    archive = Path(archive)
    dest = Path(dest)
    if dest.exists():
        die(f"destination already exists: {dest}")
    dest.mkdir(parents=True, exist_ok=False)

    extracted = 0
    total = 0
    try:
        with tarfile.open(archive, "r") as tf:
            for member in tf:
                target, size = _validate_member(member, dest)
                total += size
                if total > MAX_TOTAL_BYTES:
                    die(f"archive exceeds total size limit: {archive}")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    # Owner must retain execute so children can be created.
                    os.chmod(target, (member.mode & 0o777) | 0o700)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(member)
                if src is None:
                    die(f"cannot read archive member: {member.name}")
                with src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(target, (member.mode & 0o777) or 0o644)
                extracted += 1
    except SystemExit:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except (tarfile.TarError, OSError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        die(f"extraction failed: {archive}: {exc}")

    print(f"[OK] extracted {extracted} file(s) to {dest} (inspect read-only)")
    return extracted


def tar_create(name: str, target: Path | None = None, root: Path | None = None) -> Path:
    _safe_component(name, "snapshot name")
    src = Path(target) if target is not None else TARGET_DIR
    tar_root = Path(root) if root is not None else TAR_ROOT
    _check_source_tree(src)
    tar_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    archive = tar_root / f"{name}_{stamp}.tar"
    if archive.exists():
        die(f"archive already exists: {archive}")
    with tarfile.open(archive, "w") as tf:
        tf.add(src, arcname=src.name)
    os.chmod(archive, 0o444)
    print(f"[OK] tar snapshot: {archive} (read-only)")
    return archive


def _latest_tar(name: str, root: Path) -> Path:
    matches = sorted(root.glob(f"{name}_*.tar"))
    if not matches:
        die(f"no snapshot matching {name}_*.tar in {root}")
    return matches[-1]


def tar_clone(name: str, dest: str, root: Path | None = None) -> Path:
    _safe_component(name, "snapshot name")
    _safe_component(dest, "clone destination")
    tar_root = Path(root) if root is not None else TAR_ROOT
    archive = _latest_tar(name, tar_root)
    out = tar_root / dest
    safe_extract(archive, out)
    return out


def tar_hold(name: str, root: Path | None = None) -> Path:
    _safe_component(name, "snapshot name")
    tar_root = Path(root) if root is not None else TAR_ROOT
    archive = _latest_tar(name, tar_root)
    mode = stat.S_IMODE(archive.stat().st_mode)
    if mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        die(f"tar snapshot is writable, hold-equivalent failed: {archive}")
    print(f"[OK] tar snapshot is read-only (hold-equivalent): {archive}")
    return archive


def zfs_create(dataset: str, name: str) -> None:
    _safe_component(name, "snapshot name")
    full = f"{dataset}@{name}"
    _run(["zfs", "snapshot", full])
    _run(["zfs", "hold", "defensive-harness", full])
    print(f"[OK] zfs snapshot held: {full}")


def zfs_hold(dataset: str, name: str) -> None:
    _safe_component(name, "snapshot name")
    full = f"{dataset}@{name}"
    _run(["zfs", "hold", "defensive-harness", full])
    print(f"[OK] zfs hold applied: {full}")


def zfs_clone(dataset: str, name: str, dest: str) -> None:
    _safe_component(name, "snapshot name")
    _safe_component(dest, "clone destination")
    src = f"{dataset}@{name}"
    parent = dataset.rsplit("/", 1)[0]
    _run(["zfs", "clone", src, f"{parent}/{dest}"])
    print(f"[OK] zfs clone: {parent}/{dest} (mount read-only)")


def zfs_rollback(dataset: str, name: str, confirm: bool) -> None:
    _safe_component(name, "snapshot name")
    if not confirm:
        print("[REFUSED] rollback is destructive. Re-run with --confirm after "
              "cloning and inspecting. See README.txt Recovery.", file=sys.stderr)
        raise SystemExit(2)
    full = f"{dataset}@{name}"
    _run(["zfs", "rollback", full])
    print(f"[OK] zfs rollback complete: {full}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["tar", "zfs"], default="tar",
                    help="explicit backend; default tar (portable, non-destructive)")
    ap.add_argument("--zfs-dataset", default=ZFS_DATASET)
    ap.add_argument("--root", default=str(TAR_ROOT),
                    help="tar snapshot directory (default ./snapshots)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("name")
    p_create.add_argument("--target", default=str(TARGET_DIR))

    p_clone = sub.add_parser("clone")
    p_clone.add_argument("name")
    p_clone.add_argument("dest")

    p_list = sub.add_parser("list")

    p_hold = sub.add_parser("hold")
    p_hold.add_argument("name")

    p_rb = sub.add_parser("rollback")
    p_rb.add_argument("name")
    p_rb.add_argument("--confirm", action="store_true")

    args = ap.parse_args()
    root = Path(args.root)

    if args.cmd == "list":
        for p in sorted(root.glob("*.tar")):
            print(p)
        if zfs_available():
            _run(["zfs", "list", "-t", "snapshot", "-o", "name",
                  "-r", args.zfs_dataset], timeout=30)
        return

    if args.backend == "zfs":
        if not zfs_available():
            die("zfs backend requested but 'zfs list' failed")
        if args.cmd == "create":
            zfs_create(args.zfs_dataset, args.name)
        elif args.cmd == "clone":
            zfs_clone(args.zfs_dataset, args.name, args.dest)
        elif args.cmd == "hold":
            zfs_hold(args.zfs_dataset, args.name)
        elif args.cmd == "rollback":
            zfs_rollback(args.zfs_dataset, args.name, args.confirm)
        return

    if args.cmd == "create":
        tar_create(args.name, Path(args.target), root)
    elif args.cmd == "clone":
        tar_clone(args.name, args.dest, root)
    elif args.cmd == "hold":
        tar_hold(args.name, root)
    elif args.cmd == "rollback":
        print("[REFUSED] tar backend has no in-place rollback; use clone.", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
