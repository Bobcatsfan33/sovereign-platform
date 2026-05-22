"""Tests for the Envoy v3 schema validator and the renderer's gate."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError
from sovereign.envoy_v3 import EnvoyBootstrap, validate_bootstrap
from sovereign.models import Cluster, LbParameters, Listener, Route, ServiceInstance
from sovereign.render import RenderValidationError, _build_doc, render_envoy


def _good_instance() -> ServiceInstance:
    return ServiceInstance(
        instance_id="i1",
        service_id="sovereign-envoy-lb",
        plan_id="standard-regional",
        parameters=LbParameters(
            listeners=[Listener(name="http", port=8080, protocol="HTTP")],
            routes=[Route(host="app.local", prefix="/", cluster="app")],
            clusters=[Cluster(name="app", endpoints=["127.0.0.1:3000"])],
        ),
    )


class TestEnvoyBootstrapModel:
    def test_round_trip_valid(self) -> None:
        doc = _build_doc(_good_instance())
        bootstrap = validate_bootstrap(doc)
        assert isinstance(bootstrap, EnvoyBootstrap)
        assert bootstrap.static_resources.listeners[0].name == "http"

    def test_missing_static_resources_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_bootstrap({"admin": {"address": {"socket_address": {"address": "0.0.0.0", "port_value": 9901}}}})

    def test_bad_port_rejected(self) -> None:
        doc = _build_doc(_good_instance())
        doc["static_resources"]["listeners"][0]["address"]["socket_address"]["port_value"] = 999999
        with pytest.raises(ValidationError):
            validate_bootstrap(doc)

    def test_cluster_with_no_endpoints_rejected(self) -> None:
        doc = _build_doc(_good_instance())
        # Empty lb_endpoints triggers min_length=1
        doc["static_resources"]["clusters"][0]["load_assignment"]["endpoints"][0][
            "lb_endpoints"
        ] = []
        with pytest.raises(ValidationError):
            validate_bootstrap(doc)

    def test_route_must_have_action_or_direct_response(self) -> None:
        doc = _build_doc(_good_instance())
        hcm = doc["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][0][
            "typed_config"
        ]
        # Remove both 'route' and don't add direct_response — invalid
        rule = hcm["route_config"]["virtual_hosts"][0]["routes"][0]
        rule.pop("route", None)
        rule.pop("direct_response", None)
        with pytest.raises(ValidationError):
            validate_bootstrap(doc)

    def test_route_cannot_have_both_actions(self) -> None:
        doc = _build_doc(_good_instance())
        rule = doc["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][0][
            "typed_config"
        ]["route_config"]["virtual_hosts"][0]["routes"][0]
        rule["direct_response"] = {"status": 404}
        with pytest.raises(ValidationError):
            validate_bootstrap(doc)


class TestRendererGate:
    def test_rendered_yaml_parses_and_validates(self) -> None:
        yaml_text = render_envoy(_good_instance())
        doc = yaml.safe_load(yaml_text)
        validate_bootstrap(doc)  # must not raise

    def test_renderer_rejects_invalid_template(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Force `_build_doc` to emit an invalid shape and verify
        render_envoy raises RenderValidationError rather than returning
        broken YAML."""
        from sovereign import render as render_mod

        def broken(_instance: ServiceInstance) -> dict:  # type: ignore[type-arg]
            return {"static_resources": {"listeners": [{"name": "x"}], "clusters": []}}

        monkeypatch.setattr(render_mod, "_build_doc", broken)
        with pytest.raises(RenderValidationError):
            render_envoy(_good_instance())

    def test_renderer_with_no_routes_emits_direct_response(self) -> None:
        """The renderer's fallback (no routes -> direct_response 404)
        must still validate."""
        inst = ServiceInstance(
            instance_id="i2",
            service_id="sovereign-envoy-lb",
            plan_id="standard-regional",
            parameters=LbParameters(
                listeners=[Listener(name="http", port=8080)],
                routes=[],
                clusters=[Cluster(name="c", endpoints=["127.0.0.1:80"])],
            ),
        )
        yaml_text = render_envoy(inst)
        doc = yaml.safe_load(yaml_text)
        validate_bootstrap(doc)
