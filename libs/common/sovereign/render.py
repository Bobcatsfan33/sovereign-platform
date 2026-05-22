import yaml
from .models import ServiceInstance

def render_envoy(instance: ServiceInstance) -> str:
    params = instance.parameters
    listeners = []
    for listener in params.listeners:
        listeners.append({
            "name": listener.name,
            "address": {"socket_address": {"address": "0.0.0.0", "port_value": listener.port}},
            "filter_chains": [{"filters": [{
                "name": "envoy.filters.network.http_connection_manager",
                "typed_config": {
                    "@type": "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
                    "stat_prefix": f"{instance.instance_id}_{listener.name}",
                    "route_config": {
                        "name": f"{listener.name}_routes",
                        "virtual_hosts": [{
                            "name": "service_routes",
                            "domains": sorted(list({r.host for r in params.routes})) or ["*"],
                            "routes": [{"match": {"prefix": r.prefix}, "route": {"cluster": r.cluster}} for r in params.routes] or [{"match":{"prefix":"/"},"direct_response":{"status":404}}]
                        }]
                    },
                    "http_filters": [{"name": "envoy.filters.http.router", "typed_config": {"@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"}}]
                }
            }]}]
        })
    clusters = []
    for cluster in params.clusters:
        clusters.append({
            "name": cluster.name,
            "connect_timeout": "2s",
            "type": "STRICT_DNS",
            "load_assignment": {"cluster_name": cluster.name, "endpoints": [{"lb_endpoints": [
                {"endpoint": {"address": {"socket_address": {"address": ep.split(':')[0], "port_value": int(ep.split(':')[1])}}}} for ep in cluster.endpoints
            ]}]}
        })
    doc = {"static_resources": {"listeners": listeners, "clusters": clusters}, "admin": {"access_log_path": "/tmp/admin_access.log", "address": {"socket_address": {"address": "0.0.0.0", "port_value": 9901}}}}
    return yaml.safe_dump(doc, sort_keys=False)
