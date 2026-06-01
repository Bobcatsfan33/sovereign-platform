package sovereign.pack.identity_test

import rego.v1

import data.sovereign.pack.identity

test_no_mfa_denies if {
	some msg in identity.deny with input as {
		"instance_id": "idp1",
		"service_type": "idp-broker",
		"parameters": {"require_mfa": false, "required_aal": "aal2", "max_token_minutes": 60},
	}
	contains(msg, "IA-2")
}

test_aal1_denies if {
	some msg in identity.deny with input as {
		"instance_id": "idp2",
		"service_type": "idp-broker",
		"parameters": {"require_mfa": true, "required_aal": "aal1", "max_token_minutes": 60},
	}
	contains(msg, "IA-2(1)")
}

test_long_token_denies if {
	some msg in identity.deny with input as {
		"instance_id": "idp3",
		"service_type": "idp-broker",
		"parameters": {"require_mfa": true, "required_aal": "aal2", "max_token_minutes": 480},
	}
	contains(msg, "IA-5")
}

test_compliant_idp_allows if {
	count(identity.deny) == 0 with input as {
		"instance_id": "idp4",
		"service_type": "idp-broker",
		"parameters": {"require_mfa": true, "required_aal": "aal2", "max_token_minutes": 60},
	}
}

test_scim_no_deprovision_denies if {
	some msg in identity.deny with input as {
		"instance_id": "scim1",
		"service_type": "scim-bridge",
		"parameters": {"deprovision_on_remove": false},
	}
	contains(msg, "IA-4")
}

test_scim_compliant_allows if {
	count(identity.deny) == 0 with input as {
		"instance_id": "scim2",
		"service_type": "scim-bridge",
		"parameters": {"deprovision_on_remove": true},
	}
}

test_identity_binding_obligation if {
	"audit-identity-binding" in identity.obligations with input as {
		"instance_id": "idp5",
		"service_type": "idp-broker",
		"parameters": {"require_mfa": true, "required_aal": "aal2", "max_token_minutes": 60},
	}
}

test_non_identity_inert if {
	count(identity.deny) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
	count(identity.obligations) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
}
