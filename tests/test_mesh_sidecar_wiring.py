"""Mesh sidecar wiring checks (E3).

Two guarantees:
1. The committed per-service sidecar bootstrap ConfigMaps in
   deploy/k8s/mesh-sidecars.yaml are byte-for-byte what
   render_sidecar_bootstrap() produces — they can't silently drift from the
   renderer.
2. Each backend Deployment asserts the SPIFFE identity that the allowlist and
   the SPIRE registration entries expect (the identity was previously unset,
   so every service defaulted to spiffe://sovereign/unknown).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent

# service -> app container port; identity is spiffe://sovereign-platform/<service>.
BACKEND_SERVICES = {
    "broker": 8080,
    "control-plane": 8090,
    "audit-service": 8086,
    "metering-service": 8087,
}


def _docs(name: str) -> list[dict[str, Any]]:
    path = ROOT / "deploy" / "k8s" / name
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _render_expected(service: str, port: int) -> str:
    from sovereign import settings as settings_module
    from sovereign.render import render_sidecar_bootstrap

    settings_module.Settings.mesh_sds_enabled = True  # type: ignore[attr-defined]
    settings_module.Settings.workload_identity = f"spiffe://sovereign-platform/{service}"  # type: ignore[attr-defined]
    settings_module.get_settings.cache_clear()
    try:
        return render_sidecar_bootstrap(service, port)
    finally:
        settings_module.Settings.mesh_sds_enabled = False  # type: ignore[attr-defined]
        settings_module.Settings.workload_identity = ""  # type: ignore[attr-defined]
        settings_module.get_settings.cache_clear()


@pytest.mark.parametrize("service,port", sorted(BACKEND_SERVICES.items()))
def test_sidecar_configmap_matches_renderer(service: str, port: int) -> None:
    cfgs = {d["metadata"]["name"]: d for d in _docs("mesh-sidecars.yaml")}
    committed = cfgs[f"sidecar-bootstrap-{service}"]["data"]["envoy.yaml"]
    assert committed == _render_expected(service, port)


def test_backend_deployments_assert_their_spiffe_identity() -> None:
    deployments = {
        d["metadata"]["name"]: d
        for d in _docs("production.yaml")
        if d.get("kind") == "Deployment"
    }
    for service in BACKEND_SERVICES:
        app = deployments[service]["spec"]["template"]["spec"]["containers"][0]
        env = {e["name"]: e["value"] for e in app.get("env", [])}
        assert env.get("WORKLOAD_IDENTITY") == f"spiffe://sovereign-platform/{service}"
        assert env.get("SERVICE_NAME") == service


def test_identity_matches_allowlist_and_spire_registration() -> None:
    """The asserted identities, the inbound allowlist, and the SPIRE
    registration entries must name the same SPIFFE ids — otherwise a verified
    peer would be rejected or could never get an SVID."""
    asserted = {f"spiffe://sovereign-platform/{s}" for s in BACKEND_SERVICES}

    config = next(
        d
        for d in _docs("production.yaml")
        if d.get("kind") == "Secret" and d["metadata"]["name"] == "sovereign-runtime"
    )
    allowlist = set(config["stringData"]["ALLOWED_WORKLOAD_IDENTITIES"].split(","))
    assert asserted.issubset(allowlist)

    spire_cfg = next(
        d
        for d in _docs("spire.yaml")
        if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "spire-registration-entries"
    )
    import json

    entries = json.loads(spire_cfg["data"]["entries.json"])["entries"]
    registered = {e["spiffe_id"] for e in entries}
    assert asserted.issubset(registered)
