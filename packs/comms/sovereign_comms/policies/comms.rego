# Comms pack policy — transmission confidentiality + retention.
#
# NIST 800-53: SC-8 (Transmission Confidentiality), SC-13 (Cryptographic
# Protection / FIPS), SI-12 + AU-11 (retention), AC-4 (federation / data
# flow). Governed comms channels must encrypt in transit with FIPS
# crypto, retain records to schedule, and restrict external federation
# for classified channels.
#
# Rules are inert when the comms-specific input fields are absent.
package sovereign.pack.comms

import rego.v1

_comms_services := {"secure-email", "secure-chat"}

_fips_suites := {
	"TLS_AES_256_GCM_SHA384",
	"TLS_AES_128_GCM_SHA256",
	"TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
	"TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
}

# SC-8: TLS required on every comms channel.
deny contains sprintf(
	"SC-8: comms channel %q must require TLS",
	[input.instance_id],
) if {
	input.service_type in _comms_services
	input.parameters.tls_required == false
}

# SC-13: cipher suite must be FIPS-validated.
deny contains sprintf(
	"SC-13: comms channel %q cipher %q is not FIPS-validated",
	[input.instance_id, suite],
) if {
	input.service_type in _comms_services
	suite := input.parameters.cipher_suite
	not _fips_suites[suite]
}

# AU-11: a classified email relay must retain >= 1 year (365 days).
deny contains sprintf(
	"AU-11: %q secure-email %q retention_days (%d) below the 365-day floor",
	[classification, input.instance_id, retention],
) if {
	input.service_type == "secure-email"
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	retention := input.parameters.retention_days
	retention < 365
}

# AC-4: SECRET chat must not allow external federation.
deny contains sprintf(
	"AC-4: SECRET secure-chat %q must disable external_federation",
	[input.instance_id],
) if {
	input.service_type == "secure-chat"
	input.parameters.classification == "SECRET"
	input.parameters.external_federation == true
}

# Obligation: archive comms metadata to the audit trail (AU-2).
obligations contains "archive-comms-metadata" if {
	input.service_type in _comms_services
}
