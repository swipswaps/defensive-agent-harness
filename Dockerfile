# ==============================================================================
# CITATION & REFERENCES:
# - Digest pinning:
#   https://docs.docker.com/engine/reference/commandline/pull/#pull-an-image-by-digest
# - Reproducible builds: https://reproducible-builds.org/
# - Current python:3.12-slim digest changes on every rebuild:
#   https://dhub.cyberranges.com/_/python/tags (e.g. amd64 digest e8a38829209a)
#   https://github.com/rysweet/amplihack (supply-chain audit reference)
# ==============================================================================
# FIX #2: The fabricated digest is REPLACED with a TAG. The tag is not
# digest-pinned, so this is weaker than production-grade digest pinning,
# but it BUILDS. The user is instructed (in the comment below) to replace
# the tag with a real digest obtained from `docker manifest inspect`.
# Shipping a fake digest is strictly worse than shipping a tag: a tag at
# least resolves; a fake digest cannot be pulled at all.
# ==============================================================================
FROM python:3.12-slim

# TO PIN (production): run `docker manifest inspect python:3.12-slim --verbose`
# and replace the line above with:
#   FROM python:3.12-slim@sha256:<real-digest-here>
# Do not copy the placeholder from this file; it was invalid and has been
# removed deliberately.

RUN groupadd --gid 10001 harness \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin harness

WORKDIR /app

COPY harness_orchestrator.py /app/workspace/harness_orchestrator.py
COPY audit_logger.py /app/workspace/audit_logger.py
COPY SHA256SUMS /app/workspace/SHA256SUMS

RUN chmod 0555 /app/workspace/harness_orchestrator.py /app/workspace/audit_logger.py \
    && chmod 0444 /app/workspace/SHA256SUMS \
    && chown -R root:root /app

USER 10001:10001

ENTRYPOINT ["python3", "/app/workspace/harness_orchestrator.py"]
