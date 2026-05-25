# Sovereign Platform — audit-service image.
# Phase 5.4 STIG hardening: pinned base, non-root sovereign:1000,
# OCI labels, healthcheck. The audit-service is the only chassis
# component that talks to ClickHouse directly; everything else goes
# through this service.
FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="sovereign-platform-audit-service" \
      org.opencontainers.image.description="Dedicated audit ingestion service (ClickHouse-backed)" \
      org.opencontainers.image.source="https://github.com/Bobcatsfan33/sovereign-platform" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Sovereign Platform"

RUN apt-get update \
 && apt-get -y --no-install-recommends upgrade \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1000 sovereign \
 && useradd  --system --uid 1000 --gid sovereign --shell /usr/sbin/nologin --create-home sovereign

WORKDIR /app

COPY libs/common /app/libs/common
COPY apps/audit-service/app /app/app

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
 && pip install --no-cache-dir \
      "fastapi>=0.111" \
      "uvicorn[standard]>=0.30" \
      "pydantic>=2.7" \
      "httpx>=0.27" \
      "clickhouse-connect>=0.7" \
      "python-dotenv>=1.0"

RUN chown -R sovereign:sovereign /app

ENV PYTHONPATH=/app/libs/common \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVICE_NAME=audit-service

USER sovereign:sovereign

EXPOSE 8086

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8086/healthz', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8086"]
