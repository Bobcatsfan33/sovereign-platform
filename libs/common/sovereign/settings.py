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


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes"}


def _is_production(env: str) -> bool:
    return env.lower() in {"production", "prod"}


# Environments where the baked-in dev defaults (well-known credentials,
# permissive auth) are acceptable. ANY other value — "staging", "demo",
# "gov-prod", or a typo — is treated as a managed environment that must
# supply real secrets and fails closed otherwise. Secure-by-default: you
# opt INTO dev convenience, you never fall INTO it by mislabelling an env.
_DEV_ENVIRONMENTS: frozenset[str] = frozenset(
    {"dev", "development", "local", "test", "testing", "ci"}
)


def _is_development(env: str) -> bool:
    return env.lower() in _DEV_ENVIRONMENTS


def _requires_real_secrets(env: str) -> bool:
    """True for every environment that is not an explicitly-declared
    development one. This is the single trigger for all fail-closed
    guardrails — production AND any unrecognised (e.g. staging) env."""
    return not _is_development(env)


def _default_broker_trust_basic_auth(env: str) -> bool:
    return not _requires_real_secrets(env)


def _default_strict_secrets(env: str) -> bool:
    return _requires_real_secrets(env)


def _default_shared_bearer_auth_enabled(env: str) -> bool:
    return not _requires_real_secrets(env)


def _default_require_oidc(env: str) -> bool:
    return _requires_real_secrets(env)


def _default_require_managed_secrets(env: str) -> bool:
    return _requires_real_secrets(env)


def _default_workload_identity_enabled(env: str) -> bool:
    return _requires_real_secrets(env)


def _default_require_audit_signing(env: str) -> bool:
    return _requires_real_secrets(env)


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
    shared_bearer_auth_enabled: bool = _env_bool(
        "SHARED_BEARER_AUTH_ENABLED",
        default=_default_shared_bearer_auth_enabled(env),
    )

    # S1 hardening: when False, HTTP Basic (OSB) callers go through the full
    # RBAC pipeline like JWT callers instead of being trusted. Defaults True
    # for OSB/Cloud-Foundry back-compat; lock down in gov deployments.
    broker_trust_basic_auth: bool = _env_bool(
        "BROKER_TRUST_BASIC_AUTH",
        default=_default_broker_trust_basic_auth(env),
    )

    # S3 hardening: when True AND ENV=production, get_settings() fails closed
    # if any dev sentinel secret is still active (not just logs an error).
    # Production defaults to strict; local dev remains permissive.
    strict_secrets: bool = _env_bool(
        "STRICT_SECRETS",
        default=_default_strict_secrets(env),
    )

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
    require_oidc: bool = _env_bool("REQUIRE_OIDC", default=_default_require_oidc(env))
    oidc_jwks_cache_ttl_seconds: float = float(os.getenv("OIDC_JWKS_CACHE_TTL_SECONDS", "3600"))
    oidc_jwks_stale_grace_seconds: float = float(
        os.getenv("OIDC_JWKS_STALE_GRACE_SECONDS", "900")
    )

    # Service identity — every service reports its own name to the audit
    # service so the trail says which component emitted the event.
    service_name: str = os.getenv("SERVICE_NAME", "unknown")

    # S4: in-process token-bucket rate limit. RPS<=0 disables it.
    rate_limit_rps: float = float(os.getenv("RATE_LIMIT_RPS", "50"))
    rate_limit_burst: float = float(os.getenv("RATE_LIMIT_BURST", "100"))

    # Epic 1 / ADR-0004: periodic drift reconciler. The broker runs a
    # background loop every `reconcile_interval_seconds` that refreshes drift
    # (via the control-plane /diff) and re-converges drifted instances.
    # Set the interval to 0 to disable the loop (it stays available via the
    # manual POST /v2/reconcile). `reconcile_batch_limit` bounds how many
    # instances one pass scans so the loop stays predictable.
    reconcile_interval_seconds: float = float(os.getenv("RECONCILE_INTERVAL_SECONDS", "0"))
    reconcile_batch_limit: int = int(os.getenv("RECONCILE_BATCH_LIMIT", "200"))

    # S5: durable audit disk spool. Empty path disables it (in-memory
    # ring buffer only). Set to a writable path in production so audit
    # events survive a ClickHouse outage that outlasts the buffer.
    audit_spool_path: str = os.getenv("AUDIT_SPOOL_PATH", "")
    audit_retention_days: int = int(os.getenv("AUDIT_RETENTION_DAYS", "730"))

    # Enterprise audit export. When set, the audit service posts each
    # accepted, hash-chained event to this endpoint as JSON. Export is
    # best-effort so the local audit trail remains the source of record.
    siem_webhook_url: str = os.getenv("SIEM_WEBHOOK_URL", "")
    siem_webhook_token: str = os.getenv("SIEM_WEBHOOK_TOKEN", "")
    siem_webhook_timeout_seconds: float = float(os.getenv("SIEM_WEBHOOK_TIMEOUT_SECONDS", "2"))
    audit_signature_key_id: str = os.getenv("AUDIT_SIGNATURE_KEY_ID", "")
    audit_signing_private_key_pem: str = os.getenv("AUDIT_SIGNING_PRIVATE_KEY_PEM", "")
    require_audit_signing: bool = _env_bool(
        "REQUIRE_AUDIT_SIGNING",
        default=_default_require_audit_signing(env),
    )

    # Step 0.3: secret-material backend selector. Only "env" ships in
    # the chassis (SOVEREIGN_SECRET_<NAME> vars); production registers a
    # Vault/Secrets-Manager provider via set_secrets_provider().
    secrets_provider: str = os.getenv("SECRETS_PROVIDER", "env")
    secrets_prefix: str = os.getenv("SECRETS_PREFIX", "")
    require_managed_secrets: bool = _env_bool(
        "REQUIRE_MANAGED_SECRETS",
        default=_default_require_managed_secrets(env),
    )

    # Workload identity headers are expected to be injected by a trusted
    # mTLS front door/service mesh. They are a transition hook until the
    # deployment layer wires native SPIFFE/SPIRE or mesh policy.
    workload_identity_enabled: bool = _env_bool(
        "WORKLOAD_IDENTITY_ENABLED",
        default=_default_workload_identity_enabled(env),
    )
    allowed_workload_identities: str = os.getenv("ALLOWED_WORKLOAD_IDENTITIES", "")
    # E2: the identity THIS service asserts on outbound service-to-service
    # calls (the inbound side verifies it against allowed_workload_identities).
    # Empty falls back to a SPIFFE-style id derived from service_name, so a
    # mesh/front-door that injects real SVIDs can override it while the
    # chassis still asserts *something* when workload identity is enabled.
    workload_identity: str = os.getenv("WORKLOAD_IDENTITY", "")

    def asserted_workload_identity(self) -> str:
        """The workload identity this service presents outbound. Explicit
        WORKLOAD_IDENTITY wins; otherwise derive a stable SPIFFE-style id
        from the service name."""
        return self.workload_identity or f"spiffe://sovereign/{self.service_name}"

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
    if _requires_real_secrets(s.env):
        live = [k for k, v in _DEV_SENTINELS.items() if getattr(s, k, None) == v]
        if live:
            logger.error(
                "Sovereign Platform started with ENV=%s but dev defaults are "
                "still active for: %s. Inject real secrets via the secret "
                "manager before serving traffic.",
                s.env,
                ", ".join(live),
            )
            if s.strict_secrets:
                raise RuntimeError(
                    f"refusing to start in a managed environment (ENV={s.env}) "
                    "with dev sentinels active: " + ", ".join(live)
                )
        if s.require_oidc and (not s.oidc_issuer_url or not s.oidc_audience):
            raise RuntimeError(
                f"refusing to start in a managed environment (ENV={s.env}) "
                "without OIDC_ISSUER_URL and OIDC_AUDIENCE"
            )
        if s.require_managed_secrets and (s.secrets_provider or "env").lower() == "env":
            raise RuntimeError(
                f"refusing to start in a managed environment (ENV={s.env}) "
                "with env-only secrets provider"
            )
        if s.require_audit_signing and (
            not s.audit_signature_key_id or not s.audit_signing_private_key_pem
        ):
            raise RuntimeError(
                f"refusing to start in a managed environment (ENV={s.env}) "
                "without audit signing key material"
            )
    return s
