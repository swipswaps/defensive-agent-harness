#!/usr/bin/env bash
# ==============================================================================
# CITATION & REFERENCES:
# - gh repo view: https://cli.github.com/manual/gh_repo_view
# - gh repo create --source=. --push: https://cli.github.com/manual/gh_repo_create
# - gh repo clone: https://cli.github.com/manual/gh_repo_clone
# - Heredoc: https://www.gnu.org/software/bash/manual/bash.html#Here-Documents
# ==============================================================================
# PURPOSE: sync a populated working tree with the remote. If the tree is empty,
# the operator is told to clone first — this avoids the failure mode where a
# "generator" stub emits nothing and pushes an empty repository.
# ==============================================================================
set -u
set -o pipefail

REPO_NAME="${REPO_NAME:-defensive-agent-harness}"
VISIBILITY="${VISIBILITY:-public}"
case "$VISIBILITY" in
    --*) VIS_FLAG="$VISIBILITY" ;;
    *)   VIS_FLAG="--$VISIBILITY" ;;
esac

if [ ! -f harness_orchestrator.py ] || [ ! -f audit_logger.py ] || [ ! -f snapshot_manager.py ]; then
    echo "[BOOTSTRAP] Working tree is not populated." >&2
    echo "            Clone first:" >&2
    echo "              gh repo clone ${REPO_NAME}" >&2
    echo "            Then re-run: bash bootstrap.sh" >&2
    exit 2
fi

echo "[BOOTSTRAP] Working tree populated; verifying and syncing ..."
{
    echo "# SHA256SUMS -- generated from active workspace files."
    echo "# Only files that Dockerfile COPYs into /app/workspace are listed."
    sha256sum harness_orchestrator.py audit_logger.py
} > SHA256SUMS

git add -A
git -c user.name="defensive-harness" -c user.email="harness@localhost" \
    commit -m "bootstrap: sync working tree"

if command -v gh >/dev/null; then
    if gh repo view "$REPO_NAME" >/dev/null 2>&1; then
        git remote get-url origin >/dev/null 2>&1 || \
            git remote add origin "https://github.com/$(gh api user --jq .login)/${REPO_NAME}.git"
        git push -u origin main
    else
        gh repo create "$REPO_NAME" "$VIS_FLAG" --source=. --push
    fi
else
    echo "[BOOTSTRAP] gh not found; push manually: git push origin main" >&2
    exit 2
fi
echo "[BOOTSTRAP] Done."
