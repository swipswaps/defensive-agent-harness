DEFENSIVE AGENT HARNESS
=======================

A local-first, containerized harness for running bounded probes against a
target tree while preserving a tamper-evident audit trail and a
non-destructive snapshot for recovery. It is a defensive lab tool, not a
malware sandbox and not a substitute for a virtual machine or dedicated
hardware.


1. HOW WE GOT HERE
------------------
Autonomous coding agents backed by weight-ablated LLMs can automate
reconnaissance, version fingerprinting, package downgrades to CVE-bearing
releases, and lateral movement within minutes. Published work also
demonstrates microarchitectural cache side-channels (Prime+Probe) crossing
VM boundaries without a network bridge.

(Arditi et al., arXiv:2406.11717; Maurice et al., IEEE S&P 2017,
ISBN 978-1-5090-5533-3, DOI 10.1109/SP.2017.31.)


2. WHERE WE ARE
---------------
This repository provides five controls, each with an explicit boundary:

  (a) Container hardening
      cap_drop ALL, no-new-privileges, non-root UID, read-only rootfs,
      internal-only bridge network, memory/CPU/PID limits.

  (b) Integrity manifest
      SHA256SUMS is generated from the files that Dockerfile actually copies
      into /app/workspace. The orchestrator verifies it before a probe.
      This proves consistency, not authorship.

  (c) Hash-chained audit log
      Each entry commits to the previous entry hash. verify_chain() detects
      modification, deletion, reordering, and sequence gaps. An optional
      anchor file records the current count and tip hash so an off-box copy
      can detect a full rewrite. The chain is tamper-EVIDENT, not
      tamper-PROOF.

  (d) Non-destructive snapshots
      The tar backend is the default and always available. ZFS is opt-in.
      Recovery defaults to clone-and-inspect. ZFS rollback requires
      --confirm and never passes -r or -R.

  (e) Fail-closed target guard
      A missing or empty target aborts before the probe. An empty target is
      treated as a configuration error unless --allow-empty-target is passed
      deliberately.

WHAT IS NOT GUARANTEED
----------------------
  - taskset pins the spawned probe and its descendants. It does not isolate
    the container, the host, or the CPU cache. Docker shares the host kernel;
    it is not a virtual machine.
  - A local writable log volume can be rewritten by a process that can write
    it. The anchor only detects this if the anchor is stored outside that
    trust boundary.
  - The SHA256SUMS file and the code it describes ship in the same image.
    Signing and provenance attestation (Cosign/Sigstore) are not yet wired.
  - Snapshots are operator-driven. The orchestrator does not create them
    automatically; --require-checkpoint only enforces that the operator
    supplies an identifier.
  - The target bind mount is read-only inside the container, but the host
    operator and any host process with access can still change it.


3. HOW TO USE
-------------
PREREQUISITES
  - Linux host with Docker Engine and Docker Compose v2
  - Python 3.11 or newer for host-side tools
  - Optional: OpenZFS kernel modules for the zfs backend
  - Optional: gh CLI for bootstrap.sh

QUICK START (TAR BACKEND)
  1. Populate the target. The repository ships only a placeholder, so the
     guard intentionally fails until this is done:

       mkdir -p target_environment
       printf 'demo\n' > target_environment/demo.txt

  2. Take a snapshot before running anything:

       python3 snapshot_manager.py create baseline
       python3 snapshot_manager.py hold baseline

  3. Build the image:

       docker compose build

  4. Append a manual audit event:

       docker compose run --rm defensive_harness \
           --audit-event "session-start"

  5. Run the probe. It records PROBE_START and PROBE_END:

       docker compose run --rm defensive_harness \
           --checkpoint-id baseline

     To enforce the checkpoint gate in automation, add
     --require-checkpoint. Without it, --checkpoint-id is recorded but not
     required.

  6. Verify the chain inside the container:

       docker compose run --rm defensive_harness --audit-verify

  7. Write an anchor and copy it off-box:

       docker compose run --rm --entrypoint python3 defensive_harness \
           /app/workspace/audit_logger.py anchor \
           --path /app/logs/audit.anchor

       docker run --rm -v defensive-agent-harness_harness_logs:/logs:ro \
           --entrypoint cat defensive-agent-harness:local /logs/audit.anchor

     Store that output somewhere the container cannot write. Append-only
     remote storage or a signed ticket is the correct long-term home.

  8. Verify against the anchor:

       docker compose run --rm defensive_harness --audit-verify \
           --audit-anchor /app/logs/audit.anchor

     Any append after the anchor invalidates it until the anchor is rewritten.
     That is intentional: the anchor is a checkpoint, not a live tail.

EMPTY TARGET DRY RUN
  For a deliberate smoke test of the harness plumbing only:

       docker compose run --rm defensive_harness --allow-empty-target

  Never use this for a real probe. It produces a vacuous success.

RECOVERY
  Tar backend (default):

       python3 snapshot_manager.py clone baseline recovery_001
       # Inspect snapshots/recovery_001 read-only before copying anything back.

  ZFS backend (explicit):

       python3 snapshot_manager.py --backend zfs create baseline
       python3 snapshot_manager.py --backend zfs hold baseline
       python3 snapshot_manager.py --backend zfs clone baseline recovery_001
       # Destructive, and only after accepting data loss:
       python3 snapshot_manager.py --backend zfs rollback baseline --confirm

  zfs_snapshot_manager.py is retained as a deprecated compatibility shim.
  New automation should call snapshot_manager.py --backend zfs.

VERIFY THE REPOSITORY
       bash scripts/manifest.sh --check
       bash scripts/verify.sh
       VERIFY_DOCKER=1 bash scripts/verify.sh    # adds compose/build checks

MANIFEST MAINTENANCE
  After editing harness_orchestrator.py or audit_logger.py:

       bash scripts/manifest.sh --write
       bash scripts/verify.sh

  The manifest must list only files that Dockerfile copies into
  /app/workspace. Host-only tools such as snapshot_manager.py are excluded.


4. FAILURE MATRIX
-----------------
SYMPTOM                                  CAUSE / ACTION
---------------------------------------- -------------------------------------
[FATAL] Target directory is empty        Populate target_environment, or use
                                         --allow-empty-target for a dry run.
[FATAL] Integrity mismatch               Stale SHA256SUMS. Run
                                         bash scripts/manifest.sh --write
                                         then rebuild the image.
[BROKEN] line N: prev_hash mismatch      Middle entry deleted or reordered.
                                         Preserve the log; do not rewrite it.
[BROKEN] line N: seq mismatch            Entry removed or inserted. Same.
[BROKEN] anchor mismatch                 Log changed after the anchor. Treat
                                         as evidence loss and investigate.
[BROKEN] anchor missing                  Anchor path wrong, or the anchor was
                                         not copied into the container.
taskset: failed to set pid affinity      Invalid --pin-cpu for this host/cgroup.
                                         Check taskset -pc $$ and pass a valid
                                         core list.
No audit log yet; nothing to verify      No events have been written. Append
                                         an event first.
tar extraction refused                   Archive contains a link, device,
                                         absolute path, or traversal. Do not
                                         bypass; rebuild the snapshot from a
                                         trusted target.


5. WHAT CHANGED IN THIS REVISION
--------------------------------
  - snapshot_manager.py: tar extraction no longer uses extractall(). Every
    member is validated; links, devices, absolute paths, traversal, and
    oversized members are rejected. The tar backend refuses symlinks in the
    source tree.
  - audit_logger.py: entries now carry seq and instance; writes are locked
    and fsynced; anchor files are supported; verification detects sequence
    gaps and anchor mismatches. Legacy entries without seq still verify.
  - harness_orchestrator.py: fail-closed target guard, explicit checkpoint
    gate, audit anchor option, and PROBE_DENIED events.
  - docker-compose.yml: pids_limit, init, ulimits, a meaningful healthcheck,
    and comments that state the real isolation boundary.
  - Dockerfile: base image pinned to the current multi-arch digest.
  - .dockerignore: target data and repository metadata are no longer sent to
    the Docker daemon as build context.
  - CI: unit tests, manifest check, compose validation, and image build.
  - Root-level incident scripts moved to scripts/archive/.


6. SECURITY LIMITS
------------------
  - No custom seccomp profile; Docker's default profile applies.
  - No user-namespace remapping; the container shares the host kernel.
  - No device cgroup allowlist beyond Docker defaults.
  - No egress policy beyond the internal-only bridge network.
  - No image signature verification on pull; digest pinning is not signing.
  - No automatic snapshot before every probe; --require-checkpoint is an
    operator gate, not proof that a snapshot exists.
  - No protection against a hostile host, a compromised Docker daemon, or a
    kernel exploit.


7. CITATIONS
------------
  Arditi, A., et al. (2024). Refusal in Language Models Is Mediated by a
  Single Direction. arXiv:2406.11717. https://arxiv.org/abs/2406.11717

  Maurice, C., et al. (2017). CROWDSATER: Side-Channel Attacks in the Cloud.
  IEEE S&P, pp. 601-618. ISBN 978-1-5090-5533-3.
  DOI 10.1109/SP.2017.31.

  Kerrisk, M. (2020). The Linux Programming Interface. No Starch Press.
  ISBN 978-1-59327-220-3.

  NIST SP 800-92. Guide to Computer Security Log Management.
  https://csrc.nist.gov/pubs/sp/800/92/final

  OpenZFS zfs-hold(8):
  https://openzfs.github.io/openzfs-docs/man/8/zfs-hold.8.html

  OpenZFS zfs-rollback(8):
  https://openzfs.github.io/openzfs-docs/man/8/zfs-rollback.8.html

  Python tarfile extraction filters:
  https://docs.python.org/3/library/tarfile.html#tarfile.TarFile.extractall

  Docker security:
  https://docs.docker.com/engine/security/

  Docker named volumes:
  https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container

  GNU coreutils SHA-2 utilities:
  https://www.gnu.org/software/coreutils/manual/html_node/sha2-utilities.html
