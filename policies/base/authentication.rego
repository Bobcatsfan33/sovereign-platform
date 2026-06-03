package sovereign.base.authentication

import rego.v1

state_changing_action contains "provision"
state_changing_action contains "update"
state_changing_action contains "delete"
state_changing_action contains "bind"
state_changing_action contains "deprovision"

amr_values contains lower(value) if {
    some value in input.context.amr
    is_string(value)
}

deny contains sprintf("IA-2(11): MFA is required for %q", [input.context.action]) if {
    input.context.require_mfa == true
    input.context.action in state_changing_action
    not "mfa" in amr_values
}
