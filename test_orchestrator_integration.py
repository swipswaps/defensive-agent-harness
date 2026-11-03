#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - Python subprocess.Popen + communicate:
#   https://docs.python.org/3/library/subprocess.html#subprocess.Popen
# - Linux CPU affinity:
#   https://man7.org/linux/man-pages/man2/sched_setaffinity.2.html
# - Python tempfile.TemporaryDirectory:
#   https://docs.python.org/3/library/tempfile.html#tempfile.TemporaryDirectory
# ==============================================================================
# BEHAVIOUR:
#   End-to-end host test of the orchestrator's guards and audit events:
#   1. populated target -> PROBE_START/PROBE_END, exit 0
#   2. empty target -> PROBE_DENIED, exit 2
#   Skips when taskset is unavailable.
# ==============================================================================

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            env=env, cwd=str(REPO_ROOT),
                            start_new_session=True)
    out, err = proc.communicate(timeout=30)
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


@unittest.skipUnless(shutil.which("taskset"), "taskset not available")
class OrchestratorIntegrationTests(unittest.TestCase):
    def _workspace(self, td: Path) -> Path:
        ws = td / "workspace"
        ws.mkdir()
        for name in ("harness_orchestrator.py", "audit_logger.py"):
            shutil.copy2(REPO_ROOT / name, ws / name)
        sums = ws / "SHA256SUMS"
        sums.write_text(
            f"{sha256(ws / 'harness_orchestrator.py')}  harness_orchestrator.py\n"
            f"{sha256(ws / 'audit_logger.py')}  audit_logger.py\n",
            encoding="utf-8",
        )
        return ws

    def test_populated_target_runs_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = self._workspace(root)
            target = root / "target"
            target.mkdir()
            (target / "sample.txt").write_text("sample\n", encoding="utf-8")
            log = root / "audit.log"
            cpu = sorted(os.sched_getaffinity(0))[0]
            env = dict(os.environ)
            env.update({
                "HARNESS_WORKSPACE": str(ws),
                "HARNESS_TARGET": str(target),
                "AUDIT_LOG_PATH": str(log),
            })
            proc = run([sys.executable, str(REPO_ROOT / "harness_orchestrator.py"),
                        "--target", str(target), "--pin-cpu", str(cpu)], env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            text = log.read_text(encoding="utf-8")
            self.assertIn("PROBE_START", text)
            self.assertIn("PROBE_END", text)

    def test_empty_target_is_denied_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ws = self._workspace(root)
            target = root / "target"
            target.mkdir()
            log = root / "audit.log"
            env = dict(os.environ)
            env.update({
                "HARNESS_WORKSPACE": str(ws),
                "HARNESS_TARGET": str(target),
                "AUDIT_LOG_PATH": str(log),
            })
            proc = run([sys.executable, str(REPO_ROOT / "harness_orchestrator.py"),
                        "--target", str(target)], env)
            self.assertEqual(proc.returncode, 2)
            text = log.read_text(encoding="utf-8")
            self.assertIn("PROBE_DENIED", text)
            self.assertNotIn("PROBE_START", text)


if __name__ == "__main__":
    unittest.main()
