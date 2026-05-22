import os
from functools import lru_cache


class Settings:
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

    # Auth — basic creds for the broker's OSB API (Cloud Foundry style) and
    # a shared bearer token for inter-service calls. Both default for dev;
    # production injects real values via the secret manager.
    broker_username: str = os.getenv("BROKER_USERNAME", "broker")
    broker_password: str = os.getenv("BROKER_PASSWORD", "broker")
    dev_bearer_token: str = os.getenv("DEV_BEARER_TOKEN", "dev-token")

    # Service identity — every service reports its own name to the audit
    # service so the trail says which component emitted the event.
    service_name: str = os.getenv("SERVICE_NAME", "unknown")


@lru_cache
def get_settings() -> Settings:
    return Settings()
