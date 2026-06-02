# Blockchain pack policy — membership + key custody + consensus.
#
# NIST 800-53: AC-3 (Access Enforcement / closed membership), IA-3
# (Device Identification and Authentication / validator identity), SC-12
# (Cryptographic Key Establishment and Management / HSM custody), SC-13
# (FIPS crypto). Government ledgers must be permissioned with known,
# identity-bound validators and hardware-protected keys.
#
# Rules are inert when the ledger-specific input fields are absent.
package sovereign.pack.blockchain

import rego.v1

_bft := {"ibft2", "qbft"}

# AC-3: a government ledger must be permissioned (no public/permissionless).
deny contains sprintf(
	"AC-3: ledger %q must be permissioned",
	[input.instance_id],
) if {
	input.service_type == "permissioned-ledger"
	input.parameters.permissioned == false
}

# IA-3: validators must authenticate with an issued identity.
deny contains sprintf(
	"IA-3: ledger %q must require validator identity",
	[input.instance_id],
) if {
	input.service_type == "permissioned-ledger"
	input.parameters.validator_identity_required == false
}

# SC-12: signing keys for a classified ledger must be HSM/KMS-held.
deny contains sprintf(
	"SC-12: %q ledger %q must use HSM key custody",
	[classification, input.instance_id],
) if {
	input.service_type == "permissioned-ledger"
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.hsm_key_custody == false
}

# SC-13: a classified ledger must use FIPS-validated crypto.
deny contains sprintf(
	"SC-13: %q ledger %q must use FIPS crypto",
	[classification, input.instance_id],
) if {
	input.service_type == "permissioned-ledger"
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.fips_crypto == false
}

# AC-3(reliability): a large validator set must use BFT consensus, since
# crash-fault-tolerant raft cannot tolerate a malicious validator and the
# collusion surface grows with the set size.
deny contains sprintf(
	"AC-3: ledger %q with %d validators must use BFT consensus (got %q)",
	[input.instance_id, count_v, consensus],
) if {
	input.service_type == "permissioned-ledger"
	count_v := input.parameters.validator_count
	count_v > 7
	consensus := input.parameters.consensus
	not _bft[consensus]
}

# Obligation: register validator identities in the audit trail (IA-3/AU-2).
obligations contains "register-validator-identities" if {
	input.service_type == "permissioned-ledger"
}
