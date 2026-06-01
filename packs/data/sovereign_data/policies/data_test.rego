package sovereign.pack.data_test

import rego.v1

import data.sovereign.pack.data

test_unencrypted_cui_db_denies if {
	some msg in data.deny with input as {
		"instance_id": "db1",
		"service_type": "managed-database",
		"parameters": {"classification": "CUI", "encryption_at_rest": false, "backup_retention_days": 7},
	}
	contains(msg, "SC-28")
}

test_low_backup_retention_denies if {
	some msg in data.deny with input as {
		"instance_id": "db2",
		"service_type": "managed-database",
		"parameters": {"classification": "CUI", "encryption_at_rest": true, "backup_retention_days": 3},
	}
	contains(msg, "CP-9")
}

test_deletion_protection_off_denies if {
	some msg in data.deny with input as {
		"instance_id": "db3",
		"service_type": "managed-database",
		"parameters": {
			"classification": "SECRET",
			"encryption_at_rest": true,
			"backup_retention_days": 14,
			"deletion_protection": false,
		},
	}
	contains(msg, "SI-12")
}

test_compliant_db_allows if {
	count(data.deny) == 0 with input as {
		"instance_id": "db4",
		"service_type": "managed-database",
		"parameters": {
			"classification": "CUI",
			"encryption_at_rest": true,
			"backup_retention_days": 7,
			"deletion_protection": true,
		},
	}
}

test_unencrypted_vector_db_denies if {
	some msg in data.deny with input as {
		"instance_id": "v1",
		"service_type": "vector-db",
		"parameters": {"classification": "CUI", "encryption_at_rest": false},
	}
	contains(msg, "SC-28")
}

test_unclassified_db_is_lenient if {
	count(data.deny) == 0 with input as {
		"instance_id": "db5",
		"service_type": "managed-database",
		"parameters": {"classification": "U", "encryption_at_rest": false, "backup_retention_days": 0},
	}
}

test_classification_tag_obligation if {
	"tag-data-classification" in data.obligations with input as {
		"instance_id": "db6",
		"service_type": "managed-database",
		"parameters": {"classification": "CUI"},
	}
}

test_non_data_service_inert if {
	count(data.deny) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
	count(data.obligations) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
}
