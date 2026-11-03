HOW WE GOT HERE, WHERE WE ARE, AND HOW TO USE
==============================================

1. HOW WE GOT HERE
------------------
Autonomous coding agents backed by weight-ablated LLMs can automate
reconnaissance, version fingerprinting, package downgrades to CVE-bearing
releases, and lateral movement within minutes. Empirical work demonstrates
microarchitectural cache side-channels (Prime+Probe) crossing VM boundaries
without a network bridge.
(Arditi et al., arXiv:2406.11717; Maurice et al., IEEE S&P 2017,
ISBN 978-1-5090-5533-3, DOI 10.1109/SP.2017.31.)

2. WHERE WE ARE
---------------
This repository is a local-first, containerized adversarial-simulation
harness. Five invariants (the fifth is NEW in this revision):

  (a) Every probe runs in a capability-dropped, read-only-rootfs container.
  (b) CPU affinity is force-pinned INSIDE the orchestrator with taskset.
      (Docker Compose v3 rejects cpuset; deploy.resources is Swarm-only.
       See https://stackoverflow.com/questions/78757950 and
       cc-archive/wp-plugin-creativecommons issue #232.)
  (c) Every state-changing step is preceded by a ZFS hold; recovery
      defaults to clone + read-only inspection, NOT destructive rollback.
      (OpenZFS zfs-hold: https://openzfs.github.io/openzfs-docs/man/8/zfs-hold.8.html)
  (d) Audit entries are hash-chained; verify with:
        python3 audit_logger.py verify
      (NIST SP 800-92 requires log integrity checking;
       hash chaining is the standard tamper-evident construction.)
  (e) SHA256SUMS is regenerated at bootstrap time from the actual files,
      not left as an empty-string placeholder. (NEW)

3. HOW TO USE
-------------
Step 1 -- Host prerequisite (once):
    Ensure a ZFS dataset exists, e.g. tank/sandbox/target_env.
    The bootstrap script does NOT create pools (destructive host op).
    FIX #5: Before Step 5, verify that the dataset is mounted at
    ./target_environment or adjust the compose volume source.

Step 2 -- Authenticate GitHub CLI (once):
    gh auth login

Step 3 -- Bootstrap files and push:
    REPO_NAME=my-harness VISIBILITY=private bash bootstrap.sh
    (VISIBILITY accepts "private" or "--private"; see FIX #4.)

Step 4 -- Prepare and protect baseline (on the host):
    python3 zfs_snapshot_manager.py create baseline_state
    python3 zfs_snapshot_manager.py hold baseline_state

Step 5 -- Build and run the hardened sandbox:
    docker compose build
    docker compose up

Step 6 -- Verify audit chain at any time:
    python3 audit_logger.py verify

Step 7 -- Recover WITHOUT destroying evidence:
    python3 zfs_snapshot_manager.py clone baseline_state recovery_001
    # mount <parent>/recovery_001 read-only and inspect
    # only after explicit acceptance of data loss:
    # python3 zfs_snapshot_manager.py rollback baseline_state --confirm

WARNING:
  Do NOT use zfs rollback -r or -R. They destroy intermediate snapshots
  and dependent clones. Read OpenZFS documentation before any rollback.
