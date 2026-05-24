package sovereign.base.encryption_at_rest_test

import rego.v1

import data.sovereign.base.encryption_at_rest as ear

test_encryption_enabled_on_storage_allows if {
    count(ear.deny) == 0 with input as {
        "service_type": "rag-workspace",
        "parameters": {"encryption_at_rest": true},
    }
}

test_encryption_disabled_on_storage_denies if {
    some msg in ear.deny with input as {
        "service_type": "vector-db",
        "parameters": {"encryption_at_rest": false},
    }
    contains(msg, "SC-28")
}

test_encryption_absent_on_storage_denies_fail_closed if {
    some msg in ear.deny with input as {
        "service_type": "managed-database",
        "parameters": {},
    }
    contains(msg, "must be explicitly set")
}

test_encryption_not_required_on_lb if {
    # The LB does not persist data — SC-28 does not apply.
    count(ear.deny) == 0 with input as {
        "service_type": "sovereign-envoy-lb",
        "parameters": {},
    }
}
