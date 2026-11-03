#!/usr/bin/env bash
# ==============================================================================
# CITATION & REFERENCES:
# - GNU coreutils SHA-2 utilities (SHA256SUMS format):
#   https://www.gnu.org/software/coreutils/manual/html_node/sha2-utilities.html
# - Bash here-documents and main() wrapper:
#   https://www.gnu.org/software/bash/manual/bash.html
# ==============================================================================
# PURPOSE:
#   Write or check the runtime manifest that the image verifies before every
#   probe. Only files copied into /app/workspace belong in the manifest.
# ==============================================================================
set -u
set -o pipefail

FILES=(
    harness_orchestrator.py
    audit_logger.py
)

usage() {
    printf '%s\n' "usage: bash scripts/manifest.sh [--write|--check]"
}

write_manifest() {
    printf '%s\n' "[MANIFEST] writing SHA256SUMS"
    printf '%s\n' "  cwd: $(pwd)"
    {
        printf '%s\n' "# SHA256SUMS -- generated from active workspace files."
        printf '%s\n' "# Only files that Dockerfile COPYs into /app/workspace are listed."
        sha256sum "${FILES[@]}"
    } > SHA256SUMS
    rc=$?
    if [ "$rc" -ne 0 ]; then
        printf '%s\n' "[FATAL] could not write SHA256SUMS (rc=$rc)" >&2
        return 2
    fi
    awk 'length($1) == 64 && $1 ~ /^[0-9a-f]+$/ {printf "  %s  %s\n", $1, $2}' SHA256SUMS
    return 0
}

check_manifest() {
    printf '%s\n' "[MANIFEST] checking SHA256SUMS"
    printf '%s\n' "  cwd: $(pwd)"
    if [ ! -f SHA256SUMS ]; then
        printf '%s\n' "[FATAL] SHA256SUMS missing" >&2
        return 2
    fi
    awk 'length($1) == 64 && $1 ~ /^[0-9a-f]+$/ {print $0}' SHA256SUMS | sha256sum -c -
    rc=$?
    if [ "$rc" -ne 0 ]; then
        printf '%s\n' "[FATAL] manifest check failed (rc=$rc)" >&2
        printf '%s\n' "        run: bash scripts/manifest.sh --write" >&2
        return 2
    fi
    printf '%s\n' "[OK] manifest matches working tree"
    return 0
}

main() {
    mode="${1:---check}"
    case "$mode" in
        --write) write_manifest ;;
        --check) check_manifest ;;
        -h|--help) usage; return 0 ;;
        *) usage >&2; return 2 ;;
    esac
}

main "$@"
exit $?
