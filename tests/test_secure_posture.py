"""S-1: boot-time secure-posture guard + credential bootstrap."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sovereign.settings import assert_secure_posture

ROOT = Path(__file__).resolve().parent.parent


def _posture(**kw: object) -> SimpleNamespace:
    base = {
        "env": "production",
        "shared_bearer_auth_enabled": False,
        "require_oidc": True,
        "mtls_required": False,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_dev_posture_is_noop() -> None:
    # No raise for a dev environment regardless of flags.
    assert_secure_posture(_posture(env="dev", shared_bearer_auth_enabled=True, require_oidc=False))


def test_production_with_shared_bearer_is_fatal() -> None:
    with pytest.raises(RuntimeError, match="shared bearer auth is enabled"):
        assert_secure_posture(_posture(shared_bearer_auth_enabled=True))


def test_production_without_strong_auth_is_fatal() -> None:
    with pytest.raises(RuntimeError, match="no strong auth"):
        assert_secure_posture(_posture(require_oidc=False, mtls_required=False))


def test_production_with_oidc_is_ok() -> None:
    assert_secure_posture(_posture(require_oidc=True))


def test_production_with_mtls_is_ok() -> None:
    assert_secure_posture(_posture(require_oidc=False, mtls_required=True))


# ── bootstrap-env.sh ──────────────────────────────────────────────────


def test_bootstrap_generates_random_credentials(tmp_path: Path) -> None:
    """Running the bootstrap in an isolated dir yields generated, unique
    credentials and no committed defaults."""
    script = (ROOT / "scripts" / "bootstrap-env.sh").read_text()
    # Drop the repo-root `cd` so the test writes into its own tmp dir.
    script = "\n".join(line for line in script.splitlines() if not line.startswith('cd "'))
    (tmp_path / "bootstrap.sh").write_text(script)

    subprocess.run(["bash", "bootstrap.sh"], cwd=tmp_path, check=True, capture_output=True)
    env = (tmp_path / ".env").read_text()

    assert "minioadmin" not in env
    assert "BROKER_PASSWORD=broker\n" not in env
    assert "ENV=dev" in env
    # 600 perms.
    mode = stat.S_IMODE(os.stat(tmp_path / ".env").st_mode)
    assert mode == 0o600


def test_bootstrap_refuses_to_overwrite() -> None:
    script = (ROOT / "scripts" / "bootstrap-env.sh").read_text()
    assert 'refusing to overwrite' in script
    assert "openssl rand" in script  # credentials are generated, not literal
