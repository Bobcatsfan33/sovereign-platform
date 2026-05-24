package sovereign.base.allowed_services_test

import rego.v1

import data.sovereign.base.allowed_services as svc

test_service_in_approved_list_allows if {
    count(svc.deny) == 0 with input as {
        "tenant_id": "agency-x",
        "service_type": "sovereign-envoy-lb",
        "approved_services": ["sovereign-envoy-lb", "inference-endpoint"],
    }
}

test_service_not_in_approved_list_denies if {
    some msg in svc.deny with input as {
        "tenant_id": "agency-x",
        "service_type": "siem-workspace",
        "approved_services": ["sovereign-envoy-lb"],
    }
    contains(msg, "CM-7")
    contains(msg, "siem-workspace")
}

test_no_approved_services_list_allows if {
    # If the broker doesn't supply an approved_services list, CM-7 does
    # not gate — the tenant has no per-tenant restriction yet (Phase 3
    # tenancy will tighten this).
    count(svc.deny) == 0 with input as {
        "tenant_id": "agency-x",
        "service_type": "sovereign-envoy-lb",
    }
}

test_plan_in_approved_plans_allows if {
    count(svc.deny) == 0 with input as {
        "tenant_id": "agency-x",
        "service_type": "sovereign-envoy-lb",
        "plan_id": "standard-regional",
        "approved_plans": {
            "sovereign-envoy-lb": ["standard-regional", "multi-region"],
        },
    }
}

test_plan_not_in_approved_plans_denies if {
    some msg in svc.deny with input as {
        "tenant_id": "agency-x",
        "service_type": "sovereign-envoy-lb",
        "plan_id": "sidecar",
        "approved_plans": {"sovereign-envoy-lb": ["standard-regional"]},
    }
    contains(msg, "sidecar")
}
