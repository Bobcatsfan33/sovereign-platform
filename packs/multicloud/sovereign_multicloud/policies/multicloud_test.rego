package sovereign.pack.multicloud_test

import rego.v1

import data.sovereign.pack.multicloud

_approved := {
	"aws-govcloud": ["us-gov-west-1", "us-gov-east-1"],
	"azure-gov": ["usgovvirginia", "usgovarizona"],
}

test_commercial_region_denies if {
	some msg in multicloud.deny with input as {
		"instance_id": "acct1",
		"service_type": "cloud-account",
		"approved_regions_by_provider": _approved,
		"parameters": {"provider": "aws-govcloud", "region": "us-east-1", "guardrails_enabled": true, "org_audit_enabled": true},
	}
	contains(msg, "AC-4")
}

test_approved_region_allows if {
	count(multicloud.deny) == 0 with input as {
		"instance_id": "acct2",
		"service_type": "cloud-account",
		"approved_regions_by_provider": _approved,
		"parameters": {"provider": "aws-govcloud", "region": "us-gov-west-1", "guardrails_enabled": true, "org_audit_enabled": true},
	}
}

test_azure_gov_region_allows if {
	count(multicloud.deny) == 0 with input as {
		"instance_id": "acct3",
		"service_type": "cloud-account",
		"approved_regions_by_provider": _approved,
		"parameters": {"provider": "azure-gov", "region": "usgovvirginia", "guardrails_enabled": true, "org_audit_enabled": true},
	}
}

test_no_guardrails_denies if {
	some msg in multicloud.deny with input as {
		"instance_id": "acct4",
		"service_type": "cloud-account",
		"approved_regions_by_provider": _approved,
		"parameters": {"provider": "aws-govcloud", "region": "us-gov-west-1", "guardrails_enabled": false, "org_audit_enabled": true},
	}
	contains(msg, "CM-2")
}

test_no_org_audit_denies if {
	some msg in multicloud.deny with input as {
		"instance_id": "acct5",
		"service_type": "cloud-account",
		"approved_regions_by_provider": _approved,
		"parameters": {"provider": "aws-govcloud", "region": "us-gov-west-1", "guardrails_enabled": true, "org_audit_enabled": false},
	}
	contains(msg, "AU-2")
}

test_landing_zone_no_boundary_denies if {
	some msg in multicloud.deny with input as {
		"instance_id": "lz1",
		"service_type": "landing-zone",
		"approved_regions_by_provider": _approved,
		"parameters": {"provider": "aws-govcloud", "region": "us-gov-west-1", "network_boundary": false},
	}
	contains(msg, "SC-7")
}

test_classification_tag_obligation if {
	"tag-cloud-classification" in multicloud.obligations with input as {
		"instance_id": "acct6",
		"service_type": "cloud-account",
		"parameters": {"provider": "aws-govcloud", "region": "us-gov-west-1"},
	}
}

test_non_multicloud_inert if {
	count(multicloud.deny) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
	count(multicloud.obligations) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
}
