# ==============================================================================
# CITATION & REFERENCES:
# - Digest pinning (the digest below is the current multi-arch manifest for
#   python:3.12-slim as published by Docker Hub):
#   https://docs.docker.com/engine/reference/commandline/pull/#pull-an-image-by-digest
#   https://hub.docker.com/v2/repositories/library/python/tags/3.12-slim
# - Reproducible builds:
#   https://reproducible-builds.org/
# - Dockerfile reference (USER, ENTRYPOINT, COPY):
#   https://docs.docker.com/engine/reference/builder/
# - Named volume populated from image on first use:
#   https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container
# ==============================================================================
# TO REFRESH THE PIN:
#   docker buildx imagetools inspect python:3.12-slim
#   Replace the digest below with the current top-level manifest digest, then
#   rebuild with --pull. Do not invent a digest: an invalid pin cannot build.
# ==============================================================================
FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --gid 10001 harness \
    && useradd --uid 10001 --gid 10001 --no-create-home \
               --shell /usr/sbin/nologin harness

WORKDIR /app

COPY harness_orchestrator.py /app/workspace/harness_orchestrator.py
COPY audit_logger.py /app/workspace/audit_logger.py
COPY SHA256SUMS /app/workspace/SHA256SUMS

# /app/workspace is code (image content; read-only rootfs enforces immutability).
# /app/logs is a volume mount point, writable by the runtime UID. It must be
# created here so ownership is correct on first volume population.
# https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container
RUN chmod 0555 /app/workspace/harness_orchestrator.py /app/workspace/audit_logger.py \
    && chmod 0444 /app/workspace/SHA256SUMS \
    && chown -R root:root /app/workspace \
    && mkdir -p /app/logs \
    && chown 10001:10001 /app/logs

USER 10001:10001

STOPSIGNAL SIGTERM

ENTRYPOINT ["python3", "/app/workspace/harness_orchestrator.py"]
