# Sovereign Platform — broker service image.
# Phase 5.4 STIG hardening:
#   - Pinned base image tag (no `:latest`; explicit minor + distro).
#   - Dedicated non-root system user (`sovereign:1000`); USER directive
#     before CMD so the runtime can never elevate.
#   - OCI labels for image provenance + vulnerability tracking.
#   - HEALTHCHECK so the container orchestrator surfaces broken instances.
FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="sovereign-platform-broker" \
      org.opencontainers.image.description="Open Service Broker API for the Sovereign Platform" \
      org.opencontainers.image.source="https://github.com/Bobcatsfan33/sovereign-platform" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Sovereign Platform"

# Pull patched system packages on top of the base image so trivy CVE
# scans pass on the freshly-built artefact (the upstream Python image
# is rebuilt periodically; running apt-upgrade closes the gap between
# its build date and ours).
RUN apt-get update \
 && apt-get -y --no-install-recommends upgrade \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Non-root system user. UID/GID 1000 is intentional so file ownership
# round-trips cleanly when developers bind-mount source during dev.
RUN groupadd --system --gid 1000 sovereign \
 && useradd  --system --uid 1000 --gid sovereign --shell /usr/sbin/nologin --create-home sovereign

WORKDIR /app

# Install dependencies as root so site-packages are owned by root and
# the runtime user can't tamper with them.
COPY libs/common /app/libs/common
COPY apps/broker/app /app/app

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
      "fastapi>=0.111" \
      "uvicorn[standard]>=0.30" \
      "pydantic>=2.7" \
      "boto3>=1.34" \
      "httpx>=0.27" \
      "PyYAML>=6.0" \
      "python-dotenv>=1.0"

RUN chown -R sovereign:sovereign /app

ENV PYTHONPATH=/app/libs/common \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_NAME=broker

USER sovereign:sovereign

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/healthz', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
