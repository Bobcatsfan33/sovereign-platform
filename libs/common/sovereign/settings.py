import os
from functools import lru_cache

class Settings:
    aws_region: str = os.getenv("AWS_REGION", "us-east-1")
    dynamodb_endpoint: str | None = os.getenv("DYNAMODB_ENDPOINT")
    s3_endpoint: str | None = os.getenv("S3_ENDPOINT")
    s3_access_key: str = os.getenv("S3_ACCESS_KEY", "minioadmin")
    s3_secret_key: str = os.getenv("S3_SECRET_KEY", "minioadmin")
    config_bucket: str = os.getenv("CONFIG_BUCKET", "sovereign-configs")
    clickhouse_host: str = os.getenv("CLICKHOUSE_HOST", "localhost")
    clickhouse_port: int = int(os.getenv("CLICKHOUSE_PORT", "8123"))
    clickhouse_database: str = os.getenv("CLICKHOUSE_DATABASE", "sovereign")
    control_plane_url: str = os.getenv("CONTROL_PLANE_URL", "http://localhost:8090")
    broker_username: str = os.getenv("BROKER_USERNAME", "broker")
    broker_password: str = os.getenv("BROKER_PASSWORD", "broker")

@lru_cache
def get_settings() -> Settings:
    return Settings()
