"""S-2: the internal mTLS front door sanitizes XFCC.

The runtime trust that `require_bearer` places in XFCC depends on Envoy
stripping any client-supplied copy and setting it from the verified TLS
session. This validates that the shipped front-door config does exactly that —
and that it is well-formed Envoy v3 (same validator the renderer uses).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sovereign.envoy_v3 import validate_bootstrap

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "infra" / "envoy" / "internal-mtls.yaml"


def _doc() -> dict[str, Any]:
    return yaml.safe_load(CONFIG.read_text())


def _filter_chain(doc: dict[str, Any]) -> dict[str, Any]:
    return doc["static_resources"]["listeners"][0]["filter_chains"][0]


def test_front_door_is_valid_envoy() -> None:
    validate_bootstrap(_doc())  # raises on any structural problem


def test_terminates_mtls_tls13() -> None:
    tc = _filter_chain(_doc())["transport_socket"]["typed_config"]
    assert tc["@type"].endswith("DownstreamTlsContext")
    assert tc["require_client_certificate"] is True
    params = tc["common_tls_context"]["tls_params"]
    assert params["tls_minimum_protocol_version"] == "TLSv1_3"


def test_sanitizes_and_forwards_xfcc() -> None:
    hcm = _filter_chain(_doc())["filters"][0]["typed_config"]
    # The whole point: drop client-supplied XFCC, set it from the TLS session.
    assert hcm["forward_client_cert_details"] == "SANITIZE_SET"
    assert hcm["set_current_client_cert_details"] == {"uri": True}
