package sovereign.pack.comms_test

import rego.v1

import data.sovereign.pack.comms

test_no_tls_denies if {
	some msg in comms.deny with input as {
		"instance_id": "m1",
		"service_type": "secure-email",
		"parameters": {"tls_required": false, "cipher_suite": "TLS_AES_256_GCM_SHA384", "classification": "CUI", "retention_days": 2555},
	}
	contains(msg, "SC-8")
}

test_non_fips_cipher_denies if {
	some msg in comms.deny with input as {
		"instance_id": "m2",
		"service_type": "secure-chat",
		"parameters": {"tls_required": true, "cipher_suite": "TLS_RSA_WITH_RC4_128_SHA", "classification": "U"},
	}
	contains(msg, "SC-13")
}

test_low_email_retention_denies if {
	some msg in comms.deny with input as {
		"instance_id": "m3",
		"service_type": "secure-email",
		"parameters": {"tls_required": true, "cipher_suite": "TLS_AES_256_GCM_SHA384", "classification": "CUI", "retention_days": 30},
	}
	contains(msg, "AU-11")
}

test_secret_chat_federation_denies if {
	some msg in comms.deny with input as {
		"instance_id": "m4",
		"service_type": "secure-chat",
		"parameters": {"tls_required": true, "cipher_suite": "TLS_AES_256_GCM_SHA384", "classification": "SECRET", "external_federation": true},
	}
	contains(msg, "AC-4")
}

test_compliant_email_allows if {
	count(comms.deny) == 0 with input as {
		"instance_id": "m5",
		"service_type": "secure-email",
		"parameters": {"tls_required": true, "cipher_suite": "TLS_AES_256_GCM_SHA384", "classification": "CUI", "retention_days": 2555},
	}
}

test_compliant_chat_allows if {
	count(comms.deny) == 0 with input as {
		"instance_id": "m6",
		"service_type": "secure-chat",
		"parameters": {"tls_required": true, "cipher_suite": "TLS_AES_256_GCM_SHA384", "classification": "CUI", "external_federation": false},
	}
}

test_archive_obligation if {
	"archive-comms-metadata" in comms.obligations with input as {
		"instance_id": "m7",
		"service_type": "secure-email",
		"parameters": {"tls_required": true, "cipher_suite": "TLS_AES_256_GCM_SHA384", "classification": "U", "retention_days": 365},
	}
}

test_non_comms_inert if {
	count(comms.deny) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
	count(comms.obligations) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
}
