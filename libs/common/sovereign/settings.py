import logging
import os
from functools import lru_cache

logger = logging.getLogger("sovereign.settings")


# Sentinel values that indicate a development default rather than a real
# secret. If any of these are still in effect when ENV=production, startup
# logs a loud warning so misconfigurations are visible.
_DEV_SENTINELS: dict[str, str] = {
    "dev_bearer_token": "dev-token",
    "dev_jwt_secret": "dev-jwt-secret-replace-me-with-a-real-one",
    "broker_password": "broker",
    "s3_secret_key": "minioadmin",
}


class Settings:
    # Environment marker — "dev" locally, "production" in real deployments.
    env: str = os.getenv("ENV", "dev")

    # Cloud / object store
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    dynamodb_endpoint: str | None = os.getenv("DYNAMODB_ENDPOINT")
    s3_endpoint: str | None = os.getenv("S3_ENDPOINT")
    s3_access_key: str = os.getenv("S3_ACCESS_KEY", "minioadmin")
    s3_secret_key: str = os.getenv("S3_SECRET_KEY", "minioadmin")
    config_bucket: str = os.getenv("CONFIG_BUCKET", "sovereign-configs")

    # ClickHouse — only the audit service talks to ClickHouse directly.
    clickhouse_host: str = os.getenv("CLICKHOUSE_HOST", "localhost")
    clickhouse_port: int = int(os.getenv("CLICKHOUSE_PORT", "8123"))
    clickhouse_database: str = os.getenv("CLICKHOUSE_DATABASE", "sovereign")

    # Service URLs (in-cluster service discovery is the docker-compose
    # service name; in K8s these come from env injected by the manifest).
    control_plane_url: str = os.getenv("CONTROL_PLANE_URL", "http://localhost:8090")
    audit_service_url: str = os.getenv("AUDIT_SERVICE_URL", "http://localhost:8086")
    metering_service_url: str = os.getenv("METERING_SERVICE_URL", "http://localhost:8087")
    opa_url: str = os.getenv("OPA_URL", "http://localhost:8181")
    opa_decision_path: str = os.getenv("OPA_DECISION_PATH", "v1/data/sovereign/decision")

    # Auth — basic creds for the broker's OSB API (Cloud Foundry style) and
    # a shared bearer token for inter-service calls. Both default for dev;
    # production injects real values via the secret manager.
    broker_username: str = os.getenv("BROKER_USERNAME", "broker")
    broker_password: str = os.getenv("BROKER_PASSWORD", "broker")
    dev_bearer_token: str = os.getenv("DEV_BEARER_TOKEN", "dev-token")

    # HS256 JWT secret for tenant-aware Phase-3 authorization. Real
    # deployments swap in JWKS-based verification against the agency IdP
    # via the OIDC integration in task 3.5; this default exists only so
    # docker-compose + tests work out of the box.
    dev_jwt_secret: str = os.getenv("DEV_JWT_SECRET", "dev-jwt-secret-replace-me-with-a-real-one")

    # Phase 3.5 OIDC: when issuer_url is set the broker switches from
    # HS256 dev tokens to JWKS-verified RS256/ES256 tokens. Audience
    # check is enabled when audience is non-empty.
    oidc_issuer_url: str = os.getenv("OIDC_ISSUER_URL", "")
    oidc_audience: str = os.getenv("OIDC_AUDIENCE", "")

    # Service identity — every service reports its own name to the audit
    # service so the trail says which component emitted the event.
    service_name: str = os.getenv("SERVICE_NAME", "unknown")

    # CORS allow-list for browser-facing services (broker + audit). Comma-
    # separated origin URLs; empty allows the dev defaults below only.
    # Production sets this to the portal's deployed origin(s).
    portal_origins: str = os.getenv(
        "PORTAL_ORIGINS",
        "http://localhost:5173,http://localhost:4173,http://localhost:8088",
    )


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.env.lower() in {"production", "prod"}:
        live = [k for k, v in _DEV_SENTINELS.items() if getattr(s, k, None) == v]
        if live:
            logger.error(
                "Sovereign Platform started with ENV=%s but dev defaults are "
                "still active for: %s. Inject real secrets via the secret "
                "manager before serving traffic.",
                s.env,
                ", ".join(live),
            )
    return s
