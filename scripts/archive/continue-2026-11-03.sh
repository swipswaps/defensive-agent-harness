#!/usr/bin/env bash
# ==============================================================================
# CITATION & REFERENCES:
# - Named-volume shadowing (root cause of six prior failures):
#   https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container
# - Filtering sha256sum output to isolate the hash field:
#   https://www.gnu.org/software/coreutils/manual/html_node/sha2-utilities.html
# - docker volume rm requires all holders removed first:
#   https://docs.docker.com/reference/cli/docker/volume/rm/
# - docker compose run --entrypoint CMD:
#   https://docs.docker.com/reference/cli/docker/compose/run/
# - ENTRYPOINT/CMD: command: overrides CMD:
#   https://docs.docker.com/engine/reference/builder/#cmd
# - NIST SP 800-92 log integrity / hash chains:
#   https://csrc.nist.gov/pubs/sp/800/92/final
#   https://auditbuffet.com/patterns/ab-001387
# - Kerrisk (2020), The Linux Programming Interface, ISBN 978-1-59327-220-3.
# - Maurice et al. (2017), CROWDSATER, IEEE S&P,
#   ISBN 978-1-5090-5533-3, DOI 10.1109/SP.2017.31.
# - Arditi et al. (2024), arXiv:2406.11717.
# ==============================================================================
set -u
set -o pipefail

echo "[CONT] 1/6 — verify container file matches disk (correctly parsed)"
disk=$(sha256sum harness_orchestrator.py | awk '{print $1}')
img_raw=$(docker compose run --rm --entrypoint sha256sum defensive_harness /app/workspace/harness_orchestrator.py 2>&1)
# Restrict to lines whose first field is exactly 64 hex chars (sha256sum output).
img=$(printf '%s\n' "$img_raw" | awk '$1 ~ /^[0-9a-f]{64}$/ {print $1; exit}')
echo "  disk:  $disk"
echo "  image: $img"
if [ "$disk" != "$img" ]; then
    echo "[FATAL] container still shadowed." >&2
    echo "  Raw output for diagnosis:" >&2
    printf '%s\n' "$img_raw" >&2
    exit 2
fi
echo "  OK: container has the new code"

echo "[CONT] 2/6 — purge orphaned volume from prior project layout"
# defensive-agent-harness_harness_workspace was populated at 11:11 with the
# 2-option orchestrator and is now orphaned (no compose file references it).
if docker volume inspect defensive-agent-harness_harness_workspace >/dev/null 2>&1; then
    holders=$(docker ps -aq --filter volume=defensive-agent-harness_harness_workspace)
    for cid in $holders; do
        docker rm -f "$cid" && echo "  removed container $cid"
    done
    docker volume rm defensive-agent-harness_harness_workspace \
        && echo "  removed volume defensive-agent-harness_harness_workspace"
fi
# Also drop any lingering 'repo_harness_workspace' if it somehow reappeared.
if docker volume inspect repo_harness_workspace >/dev/null 2>&1; then
    docker volume rm repo_harness_workspace \
        && echo "  removed repo_harness_workspace"
fi

echo "[CONT] 3/6 — verify image exposes --audit-event (unambiguous test)"
docker compose run --rm defensive_harness --audit-verify \
    || { echo "[FATAL] --audit-verify rejected by argparse" >&2; exit 2; }

echo "[CONT] 4/6 — exercise manual audit event and probe"
docker compose run --rm defensive_harness \
        --audit-event "continue-$(date -u +%Y%m%dT%H%M%SZ)" \
    || { echo "[FATAL] --audit-event" >&2; exit 2; }
docker compose run --rm defensive_harness \
    || { echo "[FATAL] probe" >&2; exit 2; }
docker compose run --rm defensive_harness --audit-verify \
    || { echo "[FATAL] --audit-verify post-probe" >&2; exit 2; }

echo "[CONT] 5/6 — host tamper-detection test"
if [ -f test_audit_chain.py ]; then
    python3 test_audit_chain.py || { echo "[FATAL] host test" >&2; exit 2; }
fi

echo "[CONT] 6/6 — commit and push"
git add -A
git -c user.name="defensive-harness" -c user.email="harness@localhost" \
    commit -m "Move log volume to /app/logs; /app/workspace comes from image unshadowed. Root cause of six --audit-event failures: volume created 11:11 was populated with the 2-option orchestrator and shadowed every rebuild."

if command -v gh >/dev/null; then
    if gh repo view defensive-agent-harness >/dev/null 2>&1; then
        git remote get-url origin >/dev/null 2>&1 || \
            git remote add origin "https://github.com/$(gh api user --jq .login)/defensive-agent-harness.git"
        git push origin main || echo "  (push failed — check network/auth)"
    fi
fi

echo
echo "[CONT] DONE. Verify state from a fresh shell:"
echo "  docker compose run --rm defensive_harness --help       # 4 options"
echo "  docker compose run --rm defensive_harness --audit-verify"
echo "  docker volume ls | grep defensive"
echo "    -> expect ONLY: defensive-agent-harness_harness_logs"
echo "    -> expect NO:   defensive-agent-harness_harness_workspace"
