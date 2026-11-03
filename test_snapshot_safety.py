#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - tarfile extraction security:
#   https://docs.python.org/3/library/tarfile.html#tarfile.TarFile.extractall
# - OWASP path traversal:
#   https://owasp.org/www-community/attacks/Path_Traversal
# - Python tempfile.TemporaryDirectory:
#   https://docs.python.org/3/library/tempfile.html#tempfile.TemporaryDirectory
# ==============================================================================
# BEHAVIOUR:
#   Proves that safe_extract() rejects traversal, symlinks, and empty
#   snapshots. A regression that reintroduces extractall() should fail here.
# ==============================================================================

import io
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import snapshot_manager as sm

REPO_ROOT = Path(__file__).resolve().parent


def make_tar(path: Path, members: list[tuple[str, bytes, str]]) -> None:
    with tarfile.open(path, "w") as tf:
        for name, payload, kind in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                info.size = 0
                tf.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = payload.decode("utf-8")
                info.size = 0
                tf.addfile(info)
            else:
                raise ValueError(kind)


def run_cli(argv: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            cwd=str(REPO_ROOT), start_new_session=True)
    out, err = proc.communicate(timeout=30)
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


class SnapshotSafetyTests(unittest.TestCase):
    def test_cli_tar_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target"
            target.mkdir()
            (target / "artifact.txt").write_text("payload\n", encoding="utf-8")
            snapshots = root / "snapshots"
            common = [sys.executable, str(REPO_ROOT / "snapshot_manager.py"),
                      "--root", str(snapshots)]
            create = run_cli(common + ["create", "baseline", "--target", str(target)])
            self.assertEqual(create.returncode, 0, create.stderr)
            hold = run_cli(common + ["hold", "baseline"])
            self.assertEqual(hold.returncode, 0, hold.stderr)
            clone = run_cli(common + ["clone", "baseline", "recovery"])
            self.assertEqual(clone.returncode, 0, clone.stderr)
            recovered = snapshots / "recovery" / "target" / "artifact.txt"
            self.assertEqual(recovered.read_text(), "payload\n")

    def test_clone_rejects_traversal_destination(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(SystemExit) as cm:
                sm.tar_clone("baseline", "../escape", root=root)
            self.assertEqual(cm.exception.code, 2)

    def test_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "evil.tar"
            dest = root / "out"
            make_tar(archive, [("../escape.txt", b"owned", "file")])
            with self.assertRaises(SystemExit) as cm:
                sm.safe_extract(archive, dest)
            self.assertEqual(cm.exception.code, 2)
            self.assertFalse((root / "escape.txt").exists())
            self.assertFalse(dest.exists())

    def test_rejects_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "evil.tar"
            dest = root / "out"
            make_tar(archive, [("/tmp/escape.txt", b"owned", "file")])
            with self.assertRaises(SystemExit) as cm:
                sm.safe_extract(archive, dest)
            self.assertEqual(cm.exception.code, 2)
            self.assertFalse(dest.exists())

    def test_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "evil.tar"
            dest = root / "out"
            make_tar(archive, [("link", b"/etc/passwd", "symlink")])
            with self.assertRaises(SystemExit) as cm:
                sm.safe_extract(archive, dest)
            self.assertEqual(cm.exception.code, 2)
            self.assertFalse(dest.exists())

    def test_extracts_regular_tree(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "good.tar"
            dest = root / "out"
            make_tar(archive, [
                ("target", b"", "dir"),
                ("target/file.txt", b"hello\n", "file"),
            ])
            count = sm.safe_extract(archive, dest)
            self.assertEqual(count, 1)
            self.assertEqual((dest / "target" / "file.txt").read_text(), "hello\n")

    def test_tar_create_refuses_symlink_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target"
            target.mkdir()
            (target / "ok.txt").write_text("ok\n", encoding="utf-8")
            os.symlink("ok.txt", target / "link")
            with self.assertRaises(SystemExit) as cm:
                sm.tar_create("baseline", target=target, root=root / "snapshots")
            self.assertEqual(cm.exception.code, 2)

    def test_tar_create_refuses_placeholder_only_target(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "target"
            target.mkdir()
            (target / ".gitkeep").write_text("", encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                sm.tar_create("baseline", target=target, root=root / "snapshots")
            self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
