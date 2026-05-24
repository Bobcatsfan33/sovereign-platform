# NIST 800-53 AU-2 (Audit Events) and AU-3 (Content of Audit Records).
# Every provisioned service must have logging enabled.
package sovereign.base.audit_logging

import rego.v1

deny contains "AU-2: logging_enabled must be true on every provisioned service" if {
    input.parameters.logging_enabled == false
}

# logging_enabled defaulting to absent is treated as off (fail-closed).
deny contains "AU-2: logging_enabled must be explicitly set to true" if {
    not has_logging_param
}

has_logging_param if {
    input.parameters.logging_enabled
}

has_logging_param if {
    input.parameters.logging_enabled == false
}
