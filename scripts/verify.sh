#!/usr/bin/env bash
# ==============================================================================
# CITATION & REFERENCES:
# - Bash syntax checking (bash -n):
#   https://www.gnu.org/software/bash/manual/bash.html#Invoking-Bash
# - Python compileall:
#   https://docs.python.org/3/library/compileall.html
# - Python unittest discovery:
#   https://docs.python.org/3/library/unittest.html#test-discovery
# - Docker Compose config validation:
#   https://docs.docker.com/reference/cli/docker/compose/config/
# ==============================================================================
# PURPOSE:
#   One verification entry point. Runs local checks always; runs container
#   checks when VERIFY_DOCKER=1 and Docker is available. Exits 0 on success
#   and 2 on any failure (the repository avoids exit 1).
# ==============================================================================
set -u
set -o pipefail

main() {
    failures=0
    printf '%s\n' "[VERIFY] cwd=$(pwd)"
    printf '%s\n' "[VERIFY] python=$(python3 --version 2>&1)"
    printf '%s\n' "[VERIFY] docker=$(command -v docker || printf 'absent')"

    printf '%s\n' "[VERIFY] shell syntax"
    for script in bootstrap.sh scripts/*.sh; do
        if [ -f "$script" ]; then
            if bash -n "$script"; then
                printf '%s\n' "  OK $script"
            else
                printf '%s\n' "  FAIL $script" >&2
                failures=2
            fi
        fi
    done

    printf '%s\n' "[VERIFY] python syntax"
    if python3 -m compileall -q harness_orchestrator.py audit_logger.py \
            snapshot_manager.py zfs_snapshot_manager.py test_audit_chain.py \
            test_orchestrator_guards.py test_snapshot_safety.py \
            test_audit_anchor.py test_orchestrator_integration.py; then
        printf '%s\n' "  OK compileall"
    else
        printf '%s\n' "  FAIL compileall" >&2
        failures=2
    fi

    printf '%s\n' "[VERIFY] audit chain script"
    if python3 test_audit_chain.py; then
        printf '%s\n' "  OK test_audit_chain.py"
    else
        printf '%s\n' "  FAIL test_audit_chain.py" >&2
        failures=2
    fi

    printf '%s\n' "[VERIFY] unittest suite"
    if python3 -m unittest discover -v; then
        printf '%s\n' "  OK unittest"
    else
        printf '%s\n' "  FAIL unittest" >&2
        failures=2
    fi

    printf '%s\n' "[VERIFY] manifest"
    if bash scripts/manifest.sh --check; then
        printf '%s\n' "  OK manifest"
    else
        printf '%s\n' "  FAIL manifest (run: bash scripts/manifest.sh --write)" >&2
        failures=2
    fi

    if [ "${VERIFY_DOCKER:-0}" = "1" ]; then
        printf '%s\n' "[VERIFY] container checks (VERIFY_DOCKER=1)"
        if ! command -v docker >/dev/null; then
            printf '%s\n' "  FAIL docker not found" >&2
            failures=2
        else
            printf '%s\n' "  docker compose config"
            if docker compose config; then
                printf '%s\n' "  OK compose config"
            else
                printf '%s\n' "  FAIL compose config" >&2
                failures=2
            fi

            printf '%s\n' "  docker build"
            if docker build -t defensive-agent-harness:verify .; then
                printf '%s\n' "  OK docker build"
            else
                printf '%s\n' "  FAIL docker build" >&2
                failures=2
            fi

            printf '%s\n' "  image option surface"
            help_out=$(docker run --rm defensive-agent-harness:verify --help 2>&1)
            if printf '%s\n' "$help_out" | grep -q -- '--audit-verify'; then
                printf '%s\n' "  OK --audit-verify present"
            else
                printf '%s\n' "  FAIL --audit-verify absent" >&2
                printf '%s\n' "$help_out" >&2
                failures=2
            fi
        fi
    else
        printf '%s\n' "[VERIFY] container checks skipped (set VERIFY_DOCKER=1)"
    fi

    if [ "$failures" -ne 0 ]; then
        printf '%s\n' "[VERIFY] FAILED"
        return 2
    fi
    printf '%s\n' "[VERIFY] PASS"
    return 0
}

main "$@"
exit $?
