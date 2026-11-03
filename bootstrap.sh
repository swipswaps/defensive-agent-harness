#!/usr/bin/env bash
# ==============================================================================
# CITATION & REFERENCES:
# - gh repo view: https://cli.github.com/manual/gh_repo_view
# - gh repo create --source=. --push: https://cli.github.com/manual/gh_repo_create
# - gh repo clone: https://cli.github.com/manual/gh_repo_clone
# - Heredoc: https://www.gnu.org/software/bash/manual/bash.html#Here-Documents
# ==============================================================================
# PURPOSE:
#   Sync a populated working tree with the remote only after the local
#   verification gate passes. This prevents the historical failure mode in
#   which a stub generator pushed an empty or unverified repository.
# ==============================================================================
set -u
set -o pipefail

REPO_NAME="${REPO_NAME:-defensive-agent-harness}"
VISIBILITY="${VISIBILITY:-public}"
case "$VISIBILITY" in
    --*) VIS_FLAG="$VISIBILITY" ;;
    *)   VIS_FLAG="--$VISIBILITY" ;;
esac

REQUIRED=(
    harness_orchestrator.py
    audit_logger.py
    snapshot_manager.py
    scripts/manifest.sh
    scripts/verify.sh
)

main() {
    for f in "${REQUIRED[@]}"; do
        if [ ! -f "$f" ]; then
            printf '%s\n' "[BOOTSTRAP] Missing: $f" >&2
            printf '%s\n' "            Clone first: gh repo clone ${REPO_NAME}" >&2
            return 2
        fi
    done

    printf '%s\n' "[BOOTSTRAP] Working tree populated; running verification gate"
    bash scripts/manifest.sh --write || return 2
    bash scripts/verify.sh || return 2

    git add -A
    git -c user.name="defensive-harness" -c user.email="harness@localhost" \
        commit -m "bootstrap: verified sync (manifest + tests)"

    if command -v gh >/dev/null; then
        if gh repo view "$REPO_NAME" >/dev/null 2>&1; then
            git remote get-url origin >/dev/null 2>&1 || \
                git remote add origin "https://github.com/$(gh api user --jq .login)/${REPO_NAME}.git"
            git push -u origin main || return 2
        else
            gh repo create "$REPO_NAME" "$VIS_FLAG" --source=. --push || return 2
        fi
    else
        printf '%s\n' "[BOOTSTRAP] gh not found; push manually: git push origin main" >&2
        return 2
    fi
    printf '%s\n' "[BOOTSTRAP] Done."
    return 0
}

main "$@"
exit $?
