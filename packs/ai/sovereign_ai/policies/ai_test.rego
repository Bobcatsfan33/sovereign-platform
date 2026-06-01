package sovereign.pack.ai_test

import rego.v1

import data.sovereign.pack.ai

test_cui_without_residency_denies if {
	some msg in ai.deny with input as {
		"instance_id": "i1",
		"service_type": "inference-endpoint",
		"parameters": {"classification": "CUI"},
	}
	contains(msg, "AC-4")
}

test_cui_with_residency_allows if {
	count(ai.deny) == 0 with input as {
		"instance_id": "i1",
		"service_type": "inference-endpoint",
		"parameters": {"classification": "CUI", "data_residency": "us-gov-west-1"},
	}
}

test_secret_logging_off_denies if {
	some msg in ai.deny with input as {
		"instance_id": "i2",
		"service_type": "inference-endpoint",
		"parameters": {
			"classification": "SECRET",
			"data_residency": "us-gov-west-1",
			"logging_enabled": false,
		},
	}
	contains(msg, "SI-12")
}

test_rag_cui_unencrypted_denies if {
	some msg in ai.deny with input as {
		"instance_id": "r1",
		"service_type": "rag-workspace",
		"parameters": {
			"classification": "CUI",
			"data_residency": "us-gov-west-1",
			"encryption_at_rest": false,
		},
	}
	contains(msg, "SC-28")
}

test_pii_redaction_obligation_when_off if {
	"pii-redaction" in ai.obligations with input as {
		"instance_id": "i3",
		"service_type": "inference-endpoint",
		"parameters": {
			"classification": "CUI",
			"data_residency": "us-gov-west-1",
			"pii_redaction": false,
		},
	}
}

test_audit_provenance_obligation_always if {
	"audit-model-provenance" in ai.obligations with input as {
		"instance_id": "i4",
		"service_type": "inference-endpoint",
		"parameters": {"classification": "U"},
	}
}

test_unclassified_minimal_is_inert if {
	count(ai.deny) == 0 with input as {
		"instance_id": "i5",
		"service_type": "inference-endpoint",
		"parameters": {"classification": "U"},
	}
}

test_non_ai_service_no_obligations if {
	count(ai.obligations) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
}
