package sovereign.pack.secops_test

import rego.v1

import data.sovereign.pack.secops

test_low_retention_denies if {
	some msg in secops.deny with input as {
		"instance_id": "s1",
		"service_type": "siem-workspace",
		"parameters": {"classification": "CUI", "retention_days": 30, "immutable_storage": true},
	}
	contains(msg, "AU-11")
}

test_mutable_storage_denies if {
	some msg in secops.deny with input as {
		"instance_id": "s2",
		"service_type": "siem-workspace",
		"parameters": {"classification": "SECRET", "retention_days": 365, "immutable_storage": false},
	}
	contains(msg, "AU-9")
}

test_unsigned_pipeline_denies if {
	some msg in secops.deny with input as {
		"instance_id": "p1",
		"service_type": "log-pipeline",
		"parameters": {"classification": "CUI", "sign_records": false},
	}
	contains(msg, "AU-10")
}

test_compliant_siem_allows if {
	count(secops.deny) == 0 with input as {
		"instance_id": "s3",
		"service_type": "siem-workspace",
		"parameters": {"classification": "CUI", "retention_days": 90, "immutable_storage": true},
	}
}

test_unclassified_siem_lenient if {
	count(secops.deny) == 0 with input as {
		"instance_id": "s4",
		"service_type": "siem-workspace",
		"parameters": {"classification": "U", "retention_days": 7, "immutable_storage": false},
	}
}

test_self_monitor_obligation if {
	"siem-self-monitor" in secops.obligations with input as {
		"instance_id": "s5",
		"service_type": "siem-workspace",
		"parameters": {"classification": "CUI"},
	}
}

test_pipeline_self_monitor_obligation if {
	"siem-self-monitor" in secops.obligations with input as {
		"instance_id": "p2",
		"service_type": "log-pipeline",
		"parameters": {"classification": "CUI"},
	}
}

test_non_secops_inert if {
	count(secops.deny) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
	count(secops.obligations) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
}
