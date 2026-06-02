package sovereign.pack.edge_test

import rego.v1

import data.sovereign.pack.edge

test_non_fips_classified_denies if {
	some msg in edge.deny with input as {
		"instance_id": "n1",
		"service_type": "edge-node",
		"parameters": {"classification": "CUI", "fips_image": false, "attestation_required": true, "disk_encryption": true},
	}
	contains(msg, "SI-7")
}

test_no_attestation_denies if {
	some msg in edge.deny with input as {
		"instance_id": "n2",
		"service_type": "edge-cluster",
		"parameters": {"classification": "SECRET", "fips_image": true, "attestation_required": false},
	}
	contains(msg, "SI-7(9)")
}

test_no_disk_encryption_denies if {
	some msg in edge.deny with input as {
		"instance_id": "n3",
		"service_type": "edge-node",
		"parameters": {"classification": "CUI", "fips_image": true, "attestation_required": true, "disk_encryption": false},
	}
	contains(msg, "SC-28")
}

test_compliant_edge_node_allows if {
	count(edge.deny) == 0 with input as {
		"instance_id": "n4",
		"service_type": "edge-node",
		"parameters": {"classification": "CUI", "fips_image": true, "attestation_required": true, "disk_encryption": true},
	}
}

test_unclassified_edge_lenient if {
	count(edge.deny) == 0 with input as {
		"instance_id": "n5",
		"service_type": "edge-node",
		"parameters": {"classification": "U", "fips_image": false, "attestation_required": false, "disk_encryption": false},
	}
}

test_attestation_obligation if {
	"record-edge-attestation" in edge.obligations with input as {
		"instance_id": "n6",
		"service_type": "edge-cluster",
		"parameters": {"classification": "CUI"},
	}
}

test_cluster_fips_enforced if {
	some msg in edge.deny with input as {
		"instance_id": "c1",
		"service_type": "edge-cluster",
		"parameters": {"classification": "CUI", "fips_image": false, "attestation_required": true},
	}
	contains(msg, "SI-7")
}

test_non_edge_inert if {
	count(edge.deny) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
	count(edge.obligations) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
}
