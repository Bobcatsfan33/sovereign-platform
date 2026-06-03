package sovereign.base.authentication_test

import rego.v1

import data.sovereign.base.authentication

test_mfa_amr_allows_state_change if {
    count(authentication.deny) == 0 with input as {
        "context": {"action": "provision", "require_mfa": true, "amr": ["pwd", "mfa"]},
    }
}

test_missing_mfa_denies_state_change if {
    some msg in authentication.deny with input as {
        "context": {"action": "update", "require_mfa": true, "amr": ["pwd"]},
    }
    contains(msg, "IA-2(11)")
}

test_missing_mfa_allows_read_only_action if {
    count(authentication.deny) == 0 with input as {
        "context": {"action": "read", "require_mfa": true, "amr": ["pwd"]},
    }
}

test_basic_compatibility_not_mfa_gated if {
    count(authentication.deny) == 0 with input as {
        "context": {"action": "provision", "require_mfa": false, "amr": []},
    }
}
