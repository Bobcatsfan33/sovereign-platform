# SecOps pack policy — audit storage assurance (AU family).
#
# NIST 800-53: AU-9 (Protection of Audit Information / immutability),
# AU-10 (Non-repudiation), AU-11 (Audit Record Retention), SI-4 (System
# Monitoring). A SIEM that does not itself meet the audit-protection
# controls is worthless, so the pack enforces them on its own resources.
#
# Rules are inert when the secops-specific input fields are absent.
package sovereign.pack.secops

import rego.v1

# AU-11: a classified SIEM workspace must retain records >= 90 days.
deny contains sprintf(
	"AU-11: %q SIEM %q retention_days (%d) below the 90-day floor",
	[classification, input.instance_id, retention],
) if {
	input.service_type == "siem-workspace"
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	retention := input.parameters.retention_days
	retention < 90
}

# AU-9: a classified SIEM must use immutable (tamper-evident) storage.
deny contains sprintf(
	"AU-9: %q SIEM %q must enable immutable_storage",
	[classification, input.instance_id],
) if {
	input.service_type == "siem-workspace"
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.immutable_storage == false
}

# AU-10: a classified log pipeline must sign forwarded records.
deny contains sprintf(
	"AU-10: %q log pipeline %q must sign_records",
	[classification, input.instance_id],
) if {
	input.service_type == "log-pipeline"
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.sign_records == false
}

# Obligation: forward every SecOps provisioning event into the platform
# audit trail for SI-4 monitoring correlation.
obligations contains "siem-self-monitor" if {
	input.service_type in {"siem-workspace", "log-pipeline"}
}
