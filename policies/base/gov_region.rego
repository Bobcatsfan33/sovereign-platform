# GovCloud region enforcement.
# All resources must be provisioned in an approved GovCloud or Azure
# Gov region. `approved_regions` is settable per-tenant; when absent
# the default GovCloud set applies.
package sovereign.base.gov_region

import rego.v1

default_approved := {
    "us-gov-west-1",
    "us-gov-east-1",
    "usgovvirginia",
    "usgovarizona",
}

deny contains sprintf(
    "gov-region: parameters.region is required",
    [],
) if {
    not input.parameters.region
}

deny contains sprintf(
    "gov-region: %q is not an approved GovCloud region (allowed: %v)",
    [input.parameters.region, approved],
) if {
    input.parameters.region
    not input.parameters.region in approved
}

approved := input.approved_regions if {
    input.approved_regions
    count(input.approved_regions) > 0
}

approved := default_approved if {
    not input.approved_regions
}

approved := default_approved if {
    input.approved_regions
    count(input.approved_regions) == 0
}
