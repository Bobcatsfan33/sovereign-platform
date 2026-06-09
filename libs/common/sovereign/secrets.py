"""SecretsProvider abstraction (Step 0.3).

Connectors and executors need credentials — kubeconfigs, cloud keys,
per-connector tokens. Today `ConnectorCredentials.data` is a free dict
populated by the caller, which makes it easy to accidentally persist
secrets in DynamoDB/S3. This module introduces a small provider interface
so secret material is fetched by reference at use-time from a real
backend (Vault / AWS Secrets Manager / SSM) and never stored in chassis
state.

The chassis ships:
  - EnvSecretsProvider: reads `SOVEREIGN_SECRET_<NAME>` env vars. The safe
    default for local/dev and CI.
  - A `get_secrets_provider()` factory that selects by settings
    (`SECRETS_PROVIDER`), defaulting to env.

Production deployments register a Vault/ASM provider via
`set_secrets_provider(...)` at startup. The interface is intentionally
two methods so that swap is mechanical.
"""

from __future__ import annotations

import os
import threading
import time
from abc import ABC, abstractmethod
from base64 import b64decode
from collections.abc import Callable
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import BotoCoreError, ClientError

if TYPE_CHECKING:
    from .settings import Settings


class SecretNotFoundError(KeyError):
    """Raised when a referenced secret does not exist in the backend."""


class SecretsProvider(ABC):
    """Fetch secret material by logical name. Implementations must never
    log secret values."""

    @abstractmethod
    def get(self, name: str) -> str:
        """Return the secret string for `name`. Raise SecretNotFoundError
        if absent."""
        raise NotImplementedError

    def get_optional(self, name: str, default: str | None = None) -> str | None:
        try:
            return self.get(name)
        except SecretNotFoundError:
            return default


class EnvSecretsProvider(SecretsProvider):
    """Reads `SOVEREIGN_SECRET_<UPPER_NAME>` from the environment.

    Names are normalised: dashes/dots -> underscores, upper-cased. So
    `get("github-pat")` reads `SOVEREIGN_SECRET_GITHUB_PAT`."""

    PREFIX = "SOVEREIGN_SECRET_"

    def _env_key(self, name: str) -> str:
        norm = name.replace("-", "_").replace(".", "_").upper()
        return f"{self.PREFIX}{norm}"

    def get(self, name: str) -> str:
        key = self._env_key(name)
        val = os.environ.get(key)
        if val is None:
            raise SecretNotFoundError(name)
        return val


class AwsSecretsManagerProvider(SecretsProvider):
    """Reads secrets from AWS Secrets Manager by logical name.

    `SECRETS_PREFIX` is prepended when configured, e.g. prefix
    `sovereign/prod/` + name `broker-password` reads
    `sovereign/prod/broker-password`.
    """

    def __init__(
        self,
        *,
        region_name: str,
        prefix: str = "",
        endpoint_url: str | None = None,
    ) -> None:
        self._prefix = prefix
        self._client = boto3.client(
            "secretsmanager",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )

    def _secret_id(self, name: str) -> str:
        return f"{self._prefix}{name}"

    def get(self, name: str) -> str:
        try:
            response = self._client.get_secret_value(SecretId=self._secret_id(name))
        except (ClientError, BotoCoreError) as exc:
            raise SecretNotFoundError(name) from exc

        if "SecretString" in response:
            return str(response["SecretString"])
        if "SecretBinary" in response:
            raw = response["SecretBinary"]
            if isinstance(raw, bytes):
                return raw.decode()
            return b64decode(raw).decode()
        raise SecretNotFoundError(name)


class AwsSsmParameterProvider(SecretsProvider):
    """Reads SecureString parameters from AWS Systems Manager Parameter Store."""

    def __init__(
        self,
        *,
        region_name: str,
        prefix: str = "",
        endpoint_url: str | None = None,
    ) -> None:
        self._prefix = prefix
        self._client = boto3.client(
            "ssm",
            region_name=region_name,
            endpoint_url=endpoint_url,
        )

    def _parameter_name(self, name: str) -> str:
        return f"{self._prefix}{name}"

    def get(self, name: str) -> str:
        try:
            response = self._client.get_parameter(
                Name=self._parameter_name(name),
                WithDecryption=True,
            )
        except (ClientError, BotoCoreError) as exc:
            raise SecretNotFoundError(name) from exc
        value = response.get("Parameter", {}).get("Value")
        if value is None:
            raise SecretNotFoundError(name)
        return str(value)


_lock = threading.Lock()
_provider: SecretsProvider | None = None


def set_secrets_provider(provider: SecretsProvider) -> None:
    """Install the process-wide provider (call once at startup)."""
    global _provider
    with _lock:
        _provider = provider


class RotatingSecretsProvider(SecretsProvider):
    """Wraps a backend provider and caches each secret for `ttl_seconds`,
    re-fetching from the backend after the TTL expires. This is what makes
    rotation automatic: when the secrets manager rotates a value, every
    service picks up the new one within one TTL without a restart.

    `force_expire()` drops the cache immediately — wire it to a rotation
    webhook for instant cutover. The clock is injectable for testing."""

    def __init__(
        self,
        backend: SecretsProvider,
        *,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._backend = backend
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, str]] = {}

    def get(self, name: str) -> str:
        now = self._clock()
        with self._lock:
            hit = self._cache.get(name)
            if hit is not None and (now - hit[0]) < self._ttl:
                return hit[1]
        value = self._backend.get(name)  # may raise SecretNotFoundError
        with self._lock:
            self._cache[name] = (now, value)
        return value

    def force_expire(self) -> None:
        with self._lock:
            self._cache.clear()


def _build_provider(s: Settings) -> SecretsProvider:
    """Construct a provider from a settings instance WITHOUT importing
    settings. Kept separate so `get_settings()` can resolve managed secrets
    by passing its own (not-yet-cached) instance, avoiding a get_settings →
    get_secrets_provider → get_settings recursion.

    Selection is by the SECRETS_PROVIDER setting. Unknown values fail closed
    so a production typo cannot silently fall back to env-only secrets. A
    managed provider is wrapped for automatic rotation when SECRETS_TTL_SECONDS
    is set."""
    kind = (s.secrets_provider or "env").lower()
    if kind in {"env", ""}:
        return EnvSecretsProvider()
    if kind in {"aws-secrets-manager", "secretsmanager", "asm"}:
        backend: SecretsProvider = AwsSecretsManagerProvider(
            region_name=s.aws_region,
            prefix=s.secrets_prefix,
        )
    elif kind in {"aws-ssm", "ssm", "parameter-store"}:
        backend = AwsSsmParameterProvider(
            region_name=s.aws_region,
            prefix=s.secrets_prefix,
        )
    else:
        raise RuntimeError(f"unknown secrets provider {kind!r}")

    ttl = getattr(s, "secrets_ttl_seconds", 0) or 0
    if ttl > 0:
        return RotatingSecretsProvider(backend, ttl_seconds=ttl)
    return backend


def provider_for_settings(s: Settings) -> SecretsProvider:
    """Return the installed process-wide provider if one was set (e.g. a
    test mock or an explicit production registration), otherwise build one
    from `s`. Does NOT import settings, so it is safe to call from inside
    `get_settings()`."""
    with _lock:
        if _provider is not None:
            return _provider
        return _build_provider(s)


def get_secrets_provider() -> SecretsProvider:
    """Return the active provider, constructing the default on first use."""
    global _provider
    with _lock:
        if _provider is not None:
            return _provider
    # Resolve settings OUTSIDE the lock. get_settings() may itself build a
    # transient provider to resolve managed secrets, and that path takes
    # _lock via provider_for_settings(); holding it here would deadlock the
    # non-reentrant lock. It also keeps boto3 client construction off the
    # critical section. Imported lazily to avoid a settings import at module
    # load.
    from .settings import get_settings

    provider = provider_for_settings(get_settings())
    with _lock:
        if _provider is None:
            _provider = provider
        return _provider


def reset_secrets_provider() -> None:
    """Test helper — clear the cached provider."""
    global _provider
    with _lock:
        _provider = None
