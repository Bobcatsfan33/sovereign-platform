package sovereign.base.transmission_test

import rego.v1

import data.sovereign.base.transmission

test_tls_enabled_on_lb_allows if {
    count(transmission.deny) == 0 with input as {
        "service_type": "sovereign-envoy-lb",
        "parameters": {"tls": true},
    }
}

test_tls_disabled_on_lb_denies if {
    some msg in transmission.deny with input as {
        "service_type": "sovereign-envoy-lb",
        "parameters": {"tls": false},
    }
    contains(msg, "SC-8")
}

test_tls_absent_on_lb_denies_fail_closed if {
    some msg in transmission.deny with input as {
        "service_type": "sovereign-envoy-lb",
        "parameters": {},
    }
    contains(msg, "must be explicitly set")
}

test_tls_not_required_on_non_network_service if {
    count(transmission.deny) == 0 with input as {
        "service_type": "container-registry",
        "parameters": {},
    }
}

test_tls_required_on_inference_endpoint if {
    some msg in transmission.deny with input as {
        "service_type": "inference-endpoint",
        "parameters": {"tls": false},
    }
    contains(msg, "inference-endpoint")
}
