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
from abc import ABC, abstractmethod


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


_lock = threading.Lock()
_provider: SecretsProvider | None = None


def set_secrets_provider(provider: SecretsProvider) -> None:
    """Install the process-wide provider (call once at startup)."""
    global _provider
    with _lock:
        _provider = provider


def get_secrets_provider() -> SecretsProvider:
    """Return the active provider, constructing the default on first use.

    Selection is by the SECRETS_PROVIDER setting; only the env provider
    ships in the chassis. Unknown values fall back to env so a
    mis-set var never leaves a service without a provider."""
    global _provider
    with _lock:
        if _provider is not None:
            return _provider
        # Imported lazily to avoid a settings import at module load.
        from .settings import get_settings

        kind = (get_settings().secrets_provider or "env").lower()
        # Only 'env' is built in; production registers others explicitly.
        provider: SecretsProvider = EnvSecretsProvider()
        if kind not in {"env", ""}:
            # Unknown provider configured but not registered — fail safe to
            # env rather than crash; the operator sees nothing leak.
            provider = EnvSecretsProvider()
        _provider = provider
        return _provider


def reset_secrets_provider() -> None:
    """Test helper — clear the cached provider."""
    global _provider
    with _lock:
        _provider = None
