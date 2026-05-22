"""Shared pytest fixtures and environment for the Sovereign Platform suite.

Tests run in-process against the FastAPI apps using `starlette.testclient.TestClient`.
External dependencies are stubbed:
  - DynamoDB via moto's `mock_aws`.
  - S3 via moto's `mock_aws`.
  - ClickHouse — the audit service exposes a module-level `_client` that
    tests replace with an in-memory fake.
  - Outbound HTTP — broker → control-plane / audit-service is wired through
    `httpx.MockTransport` so no real network is hit.

The env vars set here are picked up by `Settings()` at import time. They
override `.env` for tests so the test suite is self-contained and never
talks to localhost services.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make sure libs/common is on the import path even when running pytest
# without an installed editable copy.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "libs" / "common"))

# Inject test-friendly defaults BEFORE the apps' settings module loads.
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("DEV_BEARER_TOKEN", "test-token")
os.environ.setdefault("SERVICE_NAME", "pytest")
os.environ.setdefault("AUDIT_SERVICE_URL", "http://audit.test")
os.environ.setdefault("METERING_SERVICE_URL", "http://metering.test")
os.environ.setdefault("CONTROL_PLANE_URL", "http://control-plane.test")
os.environ.setdefault("CLICKHOUSE_HOST", "clickhouse.test")
os.environ.setdefault("CLICKHOUSE_PORT", "8123")
os.environ.setdefault("CLICKHOUSE_DATABASE", "sovereign_test")
os.environ.setdefault("CONFIG_BUCKET", "sovereign-configs-test")
os.environ.setdefault("BROKER_USERNAME", "broker")
os.environ.setdefault("BROKER_PASSWORD", "broker")

import importlib.util  # noqa: E402
import types  # noqa: E402

import pytest  # noqa: E402

BEARER = "test-token"
AUTH_HEADER = {"Authorization": f"Bearer {BEARER}"}


def _load_module(service_dir: str, module_alias: str) -> types.ModuleType:
    """Load `apps/<service_dir>/app/main.py` under the alias `module_alias`.

    Each service ships its app under `apps/<service-name>/app/main.py`. The
    directory name contains a hyphen so `apps.<name>.app.main` is not a valid
    Python identifier; loading via `importlib.util.spec_from_file_location`
    sidesteps that and avoids name collisions across services."""
    path = ROOT / "apps" / service_dir / "app" / "main.py"
    spec = importlib.util.spec_from_file_location(module_alias, str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_alias] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def audit_service_module() -> types.ModuleType:
    return _load_module("audit-service", "audit_service_main")


@pytest.fixture(scope="session")
def metering_service_module() -> types.ModuleType:
    return _load_module("metering-service", "metering_service_main")


@pytest.fixture(scope="session")
def broker_module() -> types.ModuleType:
    return _load_module("broker", "broker_main")


@pytest.fixture(scope="session")
def control_plane_module() -> types.ModuleType:
    return _load_module("control-plane", "control_plane_main")


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """`get_settings()` is lru_cached. Clear so per-test env tweaks take effect."""
    from sovereign.settings import get_settings

    get_settings.cache_clear()
