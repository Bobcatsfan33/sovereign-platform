# NIST 800-53 SC-28 — Protection of Information at Rest.
# Every storage-backed service must have encryption enabled.
package sovereign.base.encryption_at_rest

import rego.v1

# Service types that persist data and therefore require encryption at rest.
storage_backed := {
    "rag-workspace",
    "vector-db",
    "managed-database",
    "container-registry",
    "siem-workspace",
}

deny contains sprintf(
    "SC-28: encryption_at_rest must be true on storage-backed service %q",
    [input.service_type],
) if {
    storage_backed[input.service_type]
    input.parameters.encryption_at_rest == false
}

deny contains sprintf(
    "SC-28: encryption_at_rest must be explicitly set on storage-backed service %q",
    [input.service_type],
) if {
    storage_backed[input.service_type]
    not has_encryption_param
}

has_encryption_param if {
    input.parameters.encryption_at_rest
}

has_encryption_param if {
    input.parameters.encryption_at_rest == false
}
