#!/usr/bin/env bash
# ==============================================================================
# CITATION & REFERENCES:
# - gh repo create --source=. --push: https://cli.github.com/manual/gh_repo_create
# - gh repo view (idempotency probe): https://cli.github.com/manual/gh_repo_view
# - Heredoc: https://www.gnu.org/software/bash/manual/bash.html#Here-Documents
# - OpenZFS hold (EBUSY on destroy):
#   https://openzfs.github.io/openzfs-docs/man/8/zfs-hold.8.html
# - OpenZFS rollback is destructive:
#   https://openzfs.github.io/openzfs-docs/man/8/zfs-rollback.8.html
# - NIST SP 800-92 (log integrity): https://csrc.nist.gov/pubs/sp/800/92/final
# - Hash-chain tamper-evident logging:
#   https://auditbuffet.com/patterns/ab-001387
# - Python Popen(start_new_session=True), communicate(timeout=):
#   https://docs.python.org/3/library/subprocess.html#subprocess.Popen
# - Docker ENTRYPOINT/CMD interaction:
#   https://docs.docker.com/engine/reference/builder/#cmd
# - Named volume initialisation from image content:
#   https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container
# - Compose: deploy is Swarm-oriented; top-level cpus/mem_limit for non-Swarm:
#   https://docs.docker.com/compose/compose-file/deploy/
# - Maurice et al. (2017), CROWDSATER, IEEE S&P,
#   ISBN 978-1-5090-5533-3, DOI 10.1109/SP.2017.31
# - Kerrisk (2020), The Linux Programming Interface, ISBN 978-1-59327-220-3
# - Arditi et al. (2024), arXiv:2406.11717
# ==============================================================================
# CONSTRAINTS: no sed, no set -e, no rm -rf, no 2>/dev/null, no exit 1;
#              all file generation via heredoc; one-shot create+push.
# ==============================================================================
set -u
set -o pipefail

REPO_NAME="${REPO_NAME:-defensive-agent-harness}"
VISIBILITY="${VISIBILITY:-public}"
case "$VISIBILITY" in
    --*) VIS_FLAG="$VISIBILITY" ;;
    *)   VIS_FLAG="--$VISIBILITY" ;;
esac

echo "[BOOTSTRAP] Generating files via heredoc ..."
