#!/usr/bin/env python3
# ==============================================================================
# CITATION & REFERENCES:
# - Python subprocess: Popen, communicate(timeout=), start_new_session:
#   https://docs.python.org/3/library/subprocess.html#subprocess.Popen
# - Process-group kill on timeout (killpg):
#   https://docs.python.org/3/library/os.html#os.killpg
# - taskset(1) CPU affinity:
#   https://man7.org/linux/man-pages/man1/taskset.1.html
# - Docker is not a virtual machine; it shares the host kernel:
#   https://docs.docker.com/engine/security/
# - Maurice et al. (2017), CROWDSATER, IEEE S&P,
#   ISBN 978-1-5090-5533-3, DOI 10.1109/SP.2017.31.
# - Arditi et al. (2024), arXiv:2406.11717.
# - GNU coreutils sha2 utilities (SHA256SUMS format):
#   https://www.gnu.org/software/coreutils/manual/html_node/sha2-utilities.html
# ==============================================================================
# DESIGN:
#   The harness fails closed before a probe if the target directory is
#   missing or empty. An empty target produces a vacuous "success" and is
#   therefore treated as a configuration error unless the operator opts in
#   with --allow-empty-target. Integrity is checked before the target guard
#   so a tampered code tree is reported first.
#
#   --require-checkpoint turns the snapshot step into an explicit gate: the
#   operator must record a checkpoint identifier (created by
#   snapshot_manager.py) before the probe may run.
# ==============================================================================
import argparse
import hashlib
import os
import signal
import subprocess
import sys
from pathlib import Path

import audit_logger

WORKSPACE = Path(os.environ.get("HARNESS_WORKSPACE", "/app/workspace"))
SUMS_FILE = WORKSPACE / "SHA256SUMS"
TARGET_DIR = Path(os.environ.get("HARNESS_TARGET", "/app/target"))


def die(msg: str, code: int = 2) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    raise SystemExit(code)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_integrity() -> None:
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


def target_entries(path: Path) -> list[Path]:
    if not path.is_dir():
        die(f"Target directory missing: {path}")
    return [p for p in path.iterdir() if p.name not in (".gitkeep", ".gitignore")]


def verify_target(path: Path | str | None = None, allow_empty: bool = False) -> list[Path]:
    target = Path(path) if path is not None else TARGET_DIR
    entries = target_entries(target)
    if not entries:
        if allow_empty:
            print(f"[WARN] Target is empty but --allow-empty-target was supplied: {target}")
            return entries
        die(f"Target directory is empty: {target}. Populate it or pass "
            f"--allow-empty-target for a deliberate dry run.")
    print(f"[OK] Target populated ({len(entries)} entries): {target}")
    return entries


def run_probe(argv: list[str], timeout_s: int, pin_cpu: str = "0") -> str:
    full_argv = ["taskset", "-c", pin_cpu] + argv
    print(f"[INFO] Executing: {' '.join(full_argv)} (timeout={timeout_s}s)")
    try:
        proc = subprocess.Popen(
            full_argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        die(f"Could not launch probe: {exc}")
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
    ap.add_argument("--target", default=str(TARGET_DIR),
                    help="Target directory exposed to the probe (default /app/target)")
    ap.add_argument("--allow-empty-target", action="store_true",
                    help="Permit a deliberately empty target (dry runs only)")
    ap.add_argument("--checkpoint-id", default=None,
                    help="Checkpoint identifier recorded in the audit event")
    ap.add_argument("--require-checkpoint", action="store_true",
                    help="Refuse to run unless --checkpoint-id is supplied")
    ap.add_argument("--audit-verify", action="store_true",
                    help="Replay and verify the hash-chained audit log, then exit")
    ap.add_argument("--audit-anchor", default=None,
                    help="With --audit-verify, also compare against this anchor file")
    ap.add_argument("--audit-event", default=None,
                    help="Append a manual audit event and exit")
    args = ap.parse_args()

    if args.audit_verify:
        raise SystemExit(audit_logger.verify_chain(args.audit_anchor))
    if args.audit_event is not None:
        audit_logger.append_event("MANUAL", {"msg": args.audit_event})
        print("[OK] audit event appended")
        return

    try:
        verify_integrity()
        verify_target(args.target, args.allow_empty_target)
        if args.require_checkpoint and not args.checkpoint_id:
            die("--require-checkpoint set but --checkpoint-id was not supplied")
    except SystemExit as exc:
        audit_logger.append_event("PROBE_DENIED", {
            "target": str(args.target),
            "allow_empty_target": args.allow_empty_target,
            "checkpoint_id": args.checkpoint_id,
            "exit": int(exc.code) if exc.code is not None else 0,
        })
        raise

    audit_logger.append_event("PROBE_START", {
        "probe": "python3 --version",
        "pin_cpu": args.pin_cpu,
        "max_runtime": args.max_runtime,
        "target": str(args.target),
        "checkpoint_id": args.checkpoint_id,
    })
    try:
        result = run_probe(["python3", "--version"], args.max_runtime, args.pin_cpu)
        audit_logger.append_event("PROBE_END", {
            "exit": 0,
            "stdout_prefix": result[:64],
        })
        print(result, end="")
    except SystemExit as e:
        audit_logger.append_event("PROBE_END", {
            "exit": int(e.code) if e.code is not None else 0,
        })
        raise


if __name__ == "__main__":
    main()
