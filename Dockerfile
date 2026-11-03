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
