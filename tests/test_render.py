from sovereign.models import ServiceInstance, ProvisionRequest
from sovereign.render import render_envoy


def test_render_envoy_contains_cluster():
    req = ProvisionRequest(
        service_id="sovereign-envoy-lb",
        plan_id="standard-regional",
        parameters={
            "routes": [{"host": "app.local", "prefix": "/", "cluster": "app"}],
            "clusters": [{"name": "app", "endpoints": ["127.0.0.1:3000"]}],
        },
    )
    inst = ServiceInstance(instance_id="demo", **req.model_dump())
    rendered = render_envoy(inst)
    assert "app.local" in rendered
    assert "127.0.0.1" in rendered
