# NIST 800-53 CM-7 — Least Functionality.
# Reject service types or plans that are not on the tenant's approved
# list. `approved_services` and `approved_plans` are populated by the
# broker from per-tenant configuration (Phase 3 tenancy will move this
# to DynamoDB; for now it's part of the OPA input document).
package sovereign.base.allowed_services

import rego.v1

deny contains sprintf(
    "CM-7: service_type %q is not approved for tenant %q",
    [input.service_type, input.tenant_id],
) if {
    input.approved_services
    count(input.approved_services) > 0
    not input.service_type in input.approved_services
}

deny contains sprintf(
    "CM-7: plan_id %q is not approved for service %q (tenant %q)",
    [input.plan_id, input.service_type, input.tenant_id],
) if {
    input.approved_plans
    plans := input.approved_plans[input.service_type]
    count(plans) > 0
    not input.plan_id in plans
}
