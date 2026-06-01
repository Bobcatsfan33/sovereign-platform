# FinOps pack policy — budget enforcement.
#
# NIST 800-53 SA-2 (Allocation of Resources) / PM-3 (Resource Availability).
# Denies a provisioning request when the requesting tenant is over a
# hard budget. The broker lifts FinOps budget state into the policy input
# under `finops` (current spend + limit) the same way it lifts per-tenant
# approved_services today; when that context is absent the rule is inert,
# so the pack is safe to install before any budget is configured.
package sovereign.pack.finops

import rego.v1

# Deny when a hard budget exists and current spend would be exceeded.
deny contains sprintf(
	"SA-2: tenant %q is over its hard budget (%.2f / %.2f %s)",
	[input.tenant_id, spend, limit, currency],
) if {
	input.finops.enforcement == "hard"
	spend := input.finops.current_spend
	limit := input.finops.budget_limit
	currency := object.get(input.finops, "currency", "USD")
	spend > limit
}

# A soft budget never denies; it is surfaced for audit only. Exposed as a
# separate rule so the broker/audit layer can record the warning without
# blocking.
warn contains sprintf(
	"SA-2 (soft): tenant %q has exceeded its soft budget (%.2f / %.2f %s)",
	[input.tenant_id, spend, limit, currency],
) if {
	input.finops.enforcement == "soft"
	spend := input.finops.current_spend
	limit := input.finops.budget_limit
	currency := object.get(input.finops, "currency", "USD")
	spend > limit
}
