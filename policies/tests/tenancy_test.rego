package sovereign.base.tenancy_test

import rego.v1

import data.sovereign.base.tenancy

test_valid_tenant_allows if {
    count(tenancy.deny) == 0 with input as {
        "tenant_id": "agency-x",
        "service_type": "sovereign-envoy-lb",
    }
}

test_missing_tenant_id_denies if {
    "AC-6: missing tenant_id on provisioning request" in tenancy.deny with input as {
        "service_type": "sovereign-envoy-lb",
    }
}

test_empty_tenant_id_denies if {
    some msg in tenancy.deny with input as {"tenant_id": "", "service_type": "x"}
    contains(msg, "AC-6")
}

test_invalid_tenant_id_chars_denies if {
    some msg in tenancy.deny with input as {
        "tenant_id": "agency x!",
        "service_type": "sovereign-envoy-lb",
    }
    contains(msg, "not a valid identifier")
}
