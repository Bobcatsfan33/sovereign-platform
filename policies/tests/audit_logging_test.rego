package sovereign.base.audit_logging_test

import rego.v1

import data.sovereign.base.audit_logging

test_logging_enabled_allows if {
    count(audit_logging.deny) == 0 with input as {
        "parameters": {"logging_enabled": true},
    }
}

test_logging_disabled_denies if {
    some msg in audit_logging.deny with input as {
        "parameters": {"logging_enabled": false},
    }
    contains(msg, "AU-2")
    contains(msg, "must be true")
}

test_logging_absent_denies_fail_closed if {
    "AU-2: logging_enabled must be explicitly set to true" in audit_logging.deny with input as {
        "parameters": {},
    }
}

test_logging_missing_parameters_denies if {
    "AU-2: logging_enabled must be explicitly set to true" in audit_logging.deny with input as {}
}
