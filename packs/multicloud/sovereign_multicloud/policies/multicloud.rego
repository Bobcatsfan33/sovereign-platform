# Multi-Cloud pack policy — residency + account governance.
#
# NIST 800-53: AC-4 (Information Flow / data residency), CM-2 (Baseline
# Configuration / guardrails), SC-7 (Boundary Protection), AU-2 (org
# audit). Extends the base gov_region rule from single resources to whole
# cloud accounts and landing zones, per provider.
#
# The approved-region set is provided in the policy input under
# `approved_regions_by_provider` (the broker lifts it from the pack), so
# the rule is data-driven and inert when that context is absent.
package sovereign.pack.multicloud

import rego.v1

_account_services := {"cloud-account", "landing-zone"}

# AC-4: region must be approved for the chosen provider. The broker
# supplies approved_regions_by_provider; when present we enforce it.
deny contains sprintf(
	"AC-4: %q in region %q is not approved for provider %q",
	[input.service_type, region, provider],
) if {
	input.service_type in _account_services
	provider := input.parameters.provider
	region := input.parameters.region
	approved := input.approved_regions_by_provider[provider]
	not region in approved
}

# CM-2: a cloud account must enable baseline guardrails.
deny contains sprintf(
	"CM-2: cloud account %q must enable guardrails",
	[input.instance_id],
) if {
	input.service_type == "cloud-account"
	input.parameters.guardrails_enabled == false
}

# AU-2: a cloud account must enable org-level audit logging.
deny contains sprintf(
	"AU-2: cloud account %q must enable org_audit",
	[input.instance_id],
) if {
	input.service_type == "cloud-account"
	input.parameters.org_audit_enabled == false
}

# SC-7: a landing zone must have a managed network boundary.
deny contains sprintf(
	"SC-7: landing zone %q must enable network_boundary",
	[input.instance_id],
) if {
	input.service_type == "landing-zone"
	input.parameters.network_boundary == false
}

# Obligation: tag every cloud resource with its classification for
# cross-cloud inventory/DLP (CM-8).
obligations contains "tag-cloud-classification" if {
	input.service_type in _account_services
}
