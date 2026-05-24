# NIST 800-53 AC-6 — Least Privilege.
# Every provisioning request must carry a tenant_id; service instances
# are isolated to the requesting tenant.
package sovereign.base.tenancy

import rego.v1

deny contains "AC-6: missing tenant_id on provisioning request" if {
    not input.tenant_id
}

deny contains sprintf("AC-6: empty tenant_id on provisioning request", []) if {
    input.tenant_id == ""
}

# Tenant_id must look like a valid identifier (alphanumeric, dash, underscore).
deny contains sprintf("AC-6: tenant_id %q is not a valid identifier", [input.tenant_id]) if {
    input.tenant_id
    not regex.match("^[a-zA-Z0-9_-]+$", input.tenant_id)
}
