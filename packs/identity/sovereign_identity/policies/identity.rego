# Identity pack policy — authentication assurance (IA family).
#
# NIST 800-53: IA-2 (Identification and Authentication / MFA), IA-2(1)
# (network access to privileged accounts), IA-2(12) (PIV/CAC acceptance),
# IA-4 (Identifier Management), IA-8 (non-organizational users). Binds
# the chassis identity plane to agency IdPs only when they meet assurance
# requirements.
#
# Rules are inert when the identity-specific input fields are absent.
package sovereign.pack.identity

import rego.v1

# IA-2: an IdP broker must require MFA.
deny contains sprintf(
	"IA-2: IdP broker %q must require_mfa",
	[input.instance_id],
) if {
	input.service_type == "idp-broker"
	input.parameters.require_mfa == false
}

# IA-2(1): privileged federation must be at least AAL2.
deny contains sprintf(
	"IA-2(1): IdP broker %q required_aal %q is below aal2",
	[input.instance_id, aal],
) if {
	input.service_type == "idp-broker"
	aal := input.parameters.required_aal
	aal == "aal1"
}

# Token lifetime ceiling — long-lived access tokens are an IA-5 risk.
deny contains sprintf(
	"IA-5: IdP broker %q max_token_minutes (%d) exceeds the 240-minute ceiling",
	[input.instance_id, mins],
) if {
	input.service_type == "idp-broker"
	mins := input.parameters.max_token_minutes
	mins > 240
}

# IA-4: a SCIM bridge must deprovision principals removed upstream.
deny contains sprintf(
	"IA-4: SCIM bridge %q must deprovision_on_remove",
	[input.instance_id],
) if {
	input.service_type == "scim-bridge"
	input.parameters.deprovision_on_remove == false
}

# Obligation: record the bound issuer/assurance in the audit trail (IA-8).
obligations contains "audit-identity-binding" if {
	input.service_type in {"idp-broker", "scim-bridge"}
}
