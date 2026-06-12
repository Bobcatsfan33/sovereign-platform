"""S-4: the reference deployment runs the strict production posture and is
wired for continuous monitoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "deploy" / "reference"


def test_overlay_bases_on_the_hardened_manifests() -> None:
    kust = yaml.safe_load((REF / "kustomization.yaml").read_text())
    assert "../k8s" in kust["resources"]  # the hardened production base
    assert any(p["path"] == "posture-patch.yaml" for p in kust["patches"])
    # The base includes the hardened manifests (mesh mTLS, etc.).
    base = yaml.safe_load((ROOT / "deploy" / "k8s" / "kustomization.yaml").read_text())
    assert {"production.yaml", "spire.yaml", "mesh-sidecars.yaml"}.issubset(base["resources"])


def test_overlay_enforces_strict_mtls() -> None:
    patch = yaml.safe_load((REF / "posture-patch.yaml").read_text())
    assert patch["data"]["MTLS_REQUIRED"] == "true"
    assert patch["data"]["MESH_MTLS_STRICT"] == "true"


def test_base_runs_oidc_on_shared_bearer_off() -> None:
    docs: list[dict[str, Any]] = [
        d
        for d in yaml.safe_load_all((ROOT / "deploy" / "k8s" / "production.yaml").read_text())
        if d
    ]
    config = next(
        d for d in docs if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "sovereign-config"
    )
    assert config["data"]["REQUIRE_OIDC"] == "true"
    assert config["data"]["SHARED_BEARER_AUTH_ENABLED"] == "false"


def test_readme_wires_continuous_monitoring() -> None:
    text = (REF / "README.md").read_text()
    assert "continuous_monitor.py" in text
    assert "AUDIT_SERVICE_URL" in text
    assert "30 consecutive days" in text
