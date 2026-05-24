package sovereign.base.gov_region_test

import rego.v1

import data.sovereign.base.gov_region

test_govcloud_west_allows if {
    count(gov_region.deny) == 0 with input as {
        "parameters": {"region": "us-gov-west-1"},
    }
}

test_govcloud_east_allows if {
    count(gov_region.deny) == 0 with input as {
        "parameters": {"region": "us-gov-east-1"},
    }
}

test_azure_gov_virginia_allows if {
    count(gov_region.deny) == 0 with input as {
        "parameters": {"region": "usgovvirginia"},
    }
}

test_commercial_region_denies if {
    some msg in gov_region.deny with input as {
        "parameters": {"region": "us-east-1"},
    }
    contains(msg, "gov-region")
    contains(msg, "us-east-1")
}

test_missing_region_denies if {
    "gov-region: parameters.region is required" in gov_region.deny with input as {
        "parameters": {},
    }
}

test_custom_approved_regions_override_default if {
    count(gov_region.deny) == 0 with input as {
        "parameters": {"region": "us-west-2"},
        "approved_regions": ["us-west-2"],
    }
}

test_empty_approved_regions_falls_back_to_default if {
    # An empty list is treated as "no per-tenant override" so the default
    # GovCloud set still applies — important so a misconfiguration that
    # blanks the list doesn't widen the policy.
    some msg in gov_region.deny with input as {
        "parameters": {"region": "us-east-1"},
        "approved_regions": [],
    }
    contains(msg, "us-east-1")
}
