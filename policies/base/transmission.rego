# NIST 800-53 SC-8 — Transmission Confidentiality and Integrity.
# TLS must be enabled on every network-facing service.
package sovereign.base.transmission

import rego.v1

# Service types that are inherently network-facing and must speak TLS.
network_facing := {
    "sovereign-envoy-lb",
    "inference-endpoint",
    "rag-workspace",
    "ai-gateway",
}

deny contains sprintf(
    "SC-8: TLS must be enabled on network-facing service %q",
    [input.service_type],
) if {
    network_facing[input.service_type]
    input.parameters.tls == false
}

deny contains sprintf(
    "SC-8: TLS parameter must be explicitly set on network-facing service %q",
    [input.service_type],
) if {
    network_facing[input.service_type]
    not has_tls_param
}

has_tls_param if {
    input.parameters.tls
}

has_tls_param if {
    input.parameters.tls == false
}
