# ==============================================================================
# CITATION & REFERENCES:
# - Named volumes inherit contents and ownership from the image directory on
#   first population; an existing volume is not re-populated.
#   https://docs.docker.com/storage/volumes/#populate-a-volume-using-a-container
#   Stack Overflow: https://stackoverflow.com/revisions/130ade44-eaa3-4f7a-b739-017e60f7ed2d
# - Digest pinning (recommended for production; a tag is used here because a
#   fabricated digest blocked builds in the prior revision):
#   https://docs.docker.com/engine/reference/commandline/pull/#pull-an-image-by-digest
# - Reproducible builds: https://reproducible-builds.org/
# ==============================================================================
FROM python:3.12-slim

RUN groupadd --gid 10001 harness \
    && useradd --uid 10001 --gid 10001 --no-create-home \
               --shell /usr/sbin/nologin harness

WORKDIR /app

COPY harness_orchestrator.py /app/workspace/harness_orchestrator.py
COPY audit_logger.py /app/workspace/audit_logger.py
COPY SHA256SUMS /app/workspace/SHA256SUMS

# FIX (F3): the workspace directory must be owned by the runtime UID before
# the named volume is first populated from the image; otherwise the audit log
# cannot be created and the hash chain never starts.
RUN chmod 0555 /app/workspace/harness_orchestrator.py /app/workspace/audit_logger.py \
    && chmod 0444 /app/workspace/SHA256SUMS \
    && chown -R root:root /app \
    && chown 10001:10001 /app/workspace

USER 10001:10001

ENTRYPOINT ["python3", "/app/workspace/harness_orchestrator.py"]
