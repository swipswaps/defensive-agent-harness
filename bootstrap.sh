#!/usr/bin/env bash
# ==============================================================================
# CITATION & REFERENCES:
# - gh repo create --source=. --push: https://cli.github.com/manual/gh_repo_create
# - gh repo view: https://cli.github.com/manual/gh_repo_view
# - Heredoc: https://www.gnu.org/software/bash/manual/bash.html#Here-Documents
# - OpenZFS hold: https://openzfs.github.io/openzfs-docs/man/8/zfs-hold.8.html
# - NIST SP 800-92: https://csrc.nist.gov/pubs/sp/800/92/final
# - Hash chain: https://auditbuffet.com/patterns/ab-001387
# - Docker ENTRYPOINT/CMD: https://docs.docker.com/engine/reference/builder/#cmd
# - Named volume population: https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container
# - zfs-fuse deprecation: https://openzfs.github.io/openzfs-docs/Getting%20Started/Fedora/
# - Compose non-Swarm limits: https://docs.docker.com/compose/compose-file/deploy/
# ==============================================================================
set -u
set -o pipefail

REPO_NAME="${REPO_NAME:-defensive-agent-harness}"
VISIBILITY="${VISIBILITY:-public}"
case "$VISIBILITY" in
    --*) VIS_FLAG="$VISIBILITY" ;;
    *)   VIS_FLAG="--$VISIBILITY" ;;
esac

if [ -f docker-compose.yml ] && [ -f Dockerfile ] && [ -f snapshot_manager.py ]; then
    echo "[BOOTSTRAP] Working tree already present; refusing to clobber." >&2
    echo "            Diff and re-run deliberately if you intend to regenerate." >&2
    exit 2
fi

# ... (full heredoc bodies for README, compose, Dockerfile, Python files,
#      snapshot_manager, CI, .gitkeep, .gitignore — identical to remediate.sh
#      steps 2–5 above) ...

{
    echo "# SHA256SUMS -- generated at bootstrap time from actual files."
    sha256sum harness_orchestrator.py audit_logger.py snapshot_manager.py
} > SHA256SUMS

git init -b main
git add -A
git -c user.name="defensive-harness" -c user.email="harness@localhost" \
    commit -m "Bootstrap: defensive-agent-harness (F1/F3 fixed, backend-neutral snapshots)"

if command -v gh >/dev/null; then
    if gh repo view "$REPO_NAME" >/dev/null 2>&1; then
        git remote get-url origin >/dev/null 2>&1 || \
            git remote add origin "https://github.com/$(gh api user --jq .login)/${REPO_NAME}.git"
        git push -u origin main
    else
        gh repo create "$REPO_NAME" "$VIS_FLAG" --source=. --push
    fi
else
    echo "[BOOTSTRAP] gh not found; local tree ready." >&2
    exit 2
fi

echo "[BOOTSTRAP] Done."
