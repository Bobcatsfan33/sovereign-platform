package sovereign.pack.blockchain_test

import rego.v1

import data.sovereign.pack.blockchain

_base := {
	"permissioned": true,
	"validator_identity_required": true,
	"hsm_key_custody": true,
	"fips_crypto": true,
	"validator_count": 4,
	"consensus": "raft",
	"classification": "CUI",
}

test_permissionless_denies if {
	some msg in blockchain.deny with input as {
		"instance_id": "l1",
		"service_type": "permissioned-ledger",
		"parameters": object.union(_base, {"permissioned": false}),
	}
	contains(msg, "AC-3")
}

test_no_validator_identity_denies if {
	some msg in blockchain.deny with input as {
		"instance_id": "l2",
		"service_type": "permissioned-ledger",
		"parameters": object.union(_base, {"validator_identity_required": false}),
	}
	contains(msg, "IA-3")
}

test_no_hsm_custody_denies if {
	some msg in blockchain.deny with input as {
		"instance_id": "l3",
		"service_type": "permissioned-ledger",
		"parameters": object.union(_base, {"hsm_key_custody": false}),
	}
	contains(msg, "SC-12")
}

test_no_fips_crypto_denies if {
	some msg in blockchain.deny with input as {
		"instance_id": "l4",
		"service_type": "permissioned-ledger",
		"parameters": object.union(_base, {"fips_crypto": false}),
	}
	contains(msg, "SC-13")
}

test_large_set_non_bft_denies if {
	some msg in blockchain.deny with input as {
		"instance_id": "l5",
		"service_type": "permissioned-ledger",
		"parameters": object.union(_base, {"validator_count": 10, "consensus": "raft"}),
	}
	contains(msg, "BFT")
}

test_large_set_bft_allows if {
	count(blockchain.deny) == 0 with input as {
		"instance_id": "l6",
		"service_type": "permissioned-ledger",
		"parameters": object.union(_base, {"validator_count": 10, "consensus": "qbft"}),
	}
}

test_compliant_small_ledger_allows if {
	count(blockchain.deny) == 0 with input as {
		"instance_id": "l7",
		"service_type": "permissioned-ledger",
		"parameters": _base,
	}
}

test_unclassified_relaxes_crypto if {
	# U-classified ledger may skip HSM/FIPS, but still must be permissioned
	# with validator identity.
	count(blockchain.deny) == 0 with input as {
		"instance_id": "l8",
		"service_type": "permissioned-ledger",
		"parameters": object.union(_base, {"classification": "U", "hsm_key_custody": false, "fips_crypto": false}),
	}
}

test_validator_obligation if {
	"register-validator-identities" in blockchain.obligations with input as {
		"instance_id": "l9",
		"service_type": "permissioned-ledger",
		"parameters": _base,
	}
}

test_non_ledger_inert if {
	count(blockchain.deny) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
	count(blockchain.obligations) == 0 with input as {
		"instance_id": "x",
		"service_type": "sovereign-envoy-lb",
		"parameters": {},
	}
}
