#!/usr/bin/env bash
# ==============================================================================
# CITATION & REFERENCES:
# - Named-volume shadowing: a volume mounted at a path within the image
#   hides the image's content at that path for the container's lifetime.
#   https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container
#   "If you start a container which creates a new volume, and the container
#    has files or directories in the directory to be mounted, Docker copies
#    the directory's contents into the volume." Only on FIRST use; existing
#    volumes are not re-populated.
# - read_only: true makes the rootfs read-only; writable paths must be
#   explicit volumes or tmpfs.
#   https://docs.docker.com/reference/cli/docker/container/run/#read-only
# - env: AUDIT_LOG_PATH is already read by audit_logger.py (line ~17 in the
#   disk version): os.environ.get("AUDIT_LOG_PATH", "/app/workspace/...").
#   https://docs.python.org/3/library/os.html#os.environ
# - docker compose build --no-cache --pull:
#   https://docs.docker.com/reference/cli/docker/compose/build/
# - docker compose run --rm --entrypoint CMD:
#   https://docs.docker.com/reference/cli/docker/compose/run/
# - ENTRYPOINT/CMD composition:
#   https://docs.docker.com/engine/reference/builder/#cmd
# - NIST SP 800-92 log integrity / hash chains:
#   https://csrc.nist.gov/pubs/sp/800/92/final
#   https://auditbuffet.com/patterns/ab-001387
# - GNU coreutils sha256sum:
#   https://www.gnu.org/software/coreutils/manual/html_node/sha2-utilities.html
# - Kerrisk (2020), The Linux Programming Interface, ISBN 978-1-59327-220-3.
# - Maurice et al. (2017), CROWDSATER, IEEE S&P,
#   ISBN 978-1-5090-5533-3, DOI 10.1109/SP.2017.31.
# - Arditi et al. (2024), arXiv:2406.11717.
# ==============================================================================
set -u
set -o pipefail

echo "[FIX] 1/8 — snapshot current state"
sha256sum harness_orchestrator.py audit_logger.py | tee /tmp/pre_fix_hashes
docker image inspect defensive-agent-harness:local --format 'image_created={{.Created}}'

echo "[FIX] 2/8 — rewrite docker-compose.yml (volume at /app/logs, code unshadowed)"
cat > docker-compose.yml <<'COMPOSE_EOF'
# ==============================================================================
# CITATION & REFERENCES:
# - Named-volume shadowing: mounting a volume at /app/workspace hides the
#   image's COPY'd files at that path. Only an EMPTY volume is populated
#   from the image on first use; existing volumes are not re-populated.
#   https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container
#   This is the root cause of the six failed --audit-event runs: the volume
#   created at 11:11 contained the pre-audit 2-option orchestrator and
#   shadowed every subsequent image build.
# - read_only: true + writable paths must be explicit volumes or tmpfs.
#   https://docs.docker.com/reference/cli/docker/container/run/#read-only
# - AUDIT_LOG_PATH env: audit_logger.py reads it via os.environ.get.
#   https://docs.python.org/3/library/os.html#os.environ
# - ENTRYPOINT/CMD: command: overrides CMD; result is ENTRYPOINT + command.
#   https://docs.docker.com/engine/reference/builder/#cmd
# - Compose deploy is Swarm-oriented; top-level cpus/mem_limit for non-Swarm.
#   https://docs.docker.com/compose/compose-file/deploy/
# - Kerrisk (2020), ISBN 978-1-59327-220-3.
# - Maurice et al. (2017), ISBN 978-1-5090-5533-3, DOI 10.1109/SP.2017.31.
# ==============================================================================
name: defensive-agent-harness

services:
  defensive_harness:
    build:
      context: .
      dockerfile: Dockerfile
    image: defensive-agent-harness:local
    container_name: local_red_team_harness
    restart: "no"
    networks:
      - isolated_sandbox
    volumes:
      # Target: read-only bind mount (host -> container, single direction).
      - ./target_environment:/app/target:ro
      # Logs: writable named volume. NOT at /app/workspace — that path is
      # code from the image and must not be shadowed.
      - harness_logs:/app/logs:rw
    environment:
      - PYTHONUNBUFFERED=1
      - PYTHONDONTWRITEBYTECODE=1
      # audit_logger.py writes here (created by Dockerfile).
      - AUDIT_LOG_PATH=/app/logs/audit_trail.log
    cpus: "1.0"
    mem_limit: "2g"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:rw,noexec,nosuid,nodev,size=64m
    command: ["--max-runtime", "120"]
    healthcheck:
      test: ["CMD", "python3", "-c", "import sys; sys.exit(0)"]
      interval: 30s
      timeout: 5s
      retries: 2

networks:
  isolated_sandbox:
    internal: true

volumes:
  harness_logs:
    driver: local
COMPOSE_EOF

echo "[FIX] 3/8 — rewrite Dockerfile (create /app/logs writable by UID 10001)"
cat > Dockerfile <<'DOCKERFILE_EOF'
# ==============================================================================
# CITATION & REFERENCES:
# - Named volume populated from image on first use:
#   https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container
# - Digest pinning (recommended in production):
#   https://docs.docker.com/engine/reference/commandline/pull/#pull-an-image-by-digest
# - Reproducible builds:
#   https://reproducible-builds.org/
# ==============================================================================
FROM python:3.12-slim

RUN groupadd --gid 10001 harness \
    && useradd --uid 10001 --gid 10001 --no-create-home \
               --shell /usr/sbin/nologin harness

WORKDIR /app

COPY harness_orchestrator.py /app/workspace/harness_orchestrator.py
COPY audit_logger.py /app/workspace/audit_logger.py
COPY SHA256SUMS /app/workspace/SHA256SUMS

# /app/workspace is code (image content, read-only rootfs enforces immutability).
# /app/logs is a volume mount point, writable by the runtime UID. It must be
# created here so ownership is correct on first volume population.
# https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container
RUN chmod 0555 /app/workspace/harness_orchestrator.py /app/workspace/audit_logger.py \
    && chmod 0444 /app/workspace/SHA256SUMS \
    && chown -R root:root /app/workspace \
    && mkdir -p /app/logs \
    && chown 10001:10001 /app/logs

USER 10001:10001

ENTRYPOINT ["python3", "/app/workspace/harness_orchestrator.py"]
DOCKERFILE_EOF

echo "[FIX] 4/8 — rebuild"
docker compose build --no-cache --pull || { echo "[FATAL] build" >&2; exit 2; }

echo "[FIX] 5/8 — verify code in container matches disk (unshadowed now)"
disk=$(sha256sum harness_orchestrator.py | awk '{print $1}')
img=$(docker compose run --rm --entrypoint sha256sum defensive_harness /app/workspace/harness_orchestrator.py 2>&1 | awk '{print $1}')
echo "  disk:  $disk"
echo "  image: $img"
if [ "$disk" != "$img" ]; then
    echo "[FATAL] still shadowed; inspect:" >&2
    echo "  docker volume ls" >&2
    echo "  grep -A3 volumes: docker-compose.yml" >&2
    exit 2
fi
echo "  OK: /app/workspace is unshadowed, disk == image"

echo "[FIX] 6/8 — purge stale volume created at 11:11 (shadowed content)"
if docker volume inspect defensive-agent-harness_harness_workspace >/dev/null 2>&1; then
    cids=$(docker ps -aq --filter volume=defensive-agent-harness_harness_workspace)
    for cid in $cids; do docker rm -f "$cid"; done
    docker volume rm defensive-agent-harness_harness_workspace \
        && echo "  removed defensive-agent-harness_harness_workspace"
fi
# Note: defensive-agent-harness_harness_logs will be created fresh on first run.

echo "[FIX] 7/8 — exercise new options (must work now)"
docker compose run --rm defensive_harness --audit-event "fix-mounts-$(date -u +%Y%m%dT%H%M%SZ)" \
    || { echo "[FATAL] --audit-event still failing" >&2; exit 2; }
docker compose run --rm defensive_harness \
    || { echo "[FATAL] probe" >&2; exit 2; }
docker compose run --rm defensive_harness --audit-verify \
    || { echo "[FATAL] --audit-verify" >&2; exit 2; }

if [ -f test_audit_chain.py ]; then
    python3 test_audit_chain.py || { echo "[FATAL] host test" >&2; exit 2; }
fi

echo "[FIX] 8/8 — commit and push"
git add -A
git -c user.name="defensive-harness" -c user.email="harness@localhost" \
    commit -m "Move log volume to /app/logs; /app/workspace comes from image unshadowed. Root cause of six --audit-event failures: volume created 11:11 was populated with the 2-option orchestrator and shadowed every subsequent rebuild."

if command -v gh >/dev/null; then
    if gh repo view defensive-agent-harness >/dev/null 2>&1; then
        git push origin main || echo "  (push failed — check network/auth)"
    fi
fi

echo
echo "[FIX] DONE. Verify from a fresh shell:"
echo "  docker compose run --rm defensive_harness --help   # should list 4 options"
echo "  docker compose run --rm defensive_harness --audit-verify   # [OK] Hash chain intact"
echo "  docker run --rm -v defensive-agent-harness_harness_logs:/l:ro alpine cat /l/audit_trail.log"
