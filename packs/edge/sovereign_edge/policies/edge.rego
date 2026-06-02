# Edge pack policy — supply-chain + boot integrity (SI-7 / SR-11).
#
# NIST 800-53: SI-7 (Software/Firmware/Information Integrity), SI-7(9)
# (verify boot process / measured boot), SC-28 (at-rest encryption — edge
# sites are physically exposed), SR-11 (component authenticity), AC-4
# (edge data flow). Edge compute lives outside the physical perimeter, so
# the integrity bar is higher than core: FIPS images + attestation are
# mandatory for classified edge workloads.
#
# Rules are inert when the edge-specific input fields are absent.
package sovereign.pack.edge

import rego.v1

_edge_services := {"edge-node", "edge-cluster"}

# SR-11 / SI-7: classified edge workloads must use a FIPS-validated image.
deny contains sprintf(
	"SI-7: %q edge workload %q must use a FIPS-validated image",
	[classification, input.instance_id],
) if {
	input.service_type in _edge_services
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.fips_image == false
}

# SI-7(9): classified edge workloads must require boot attestation.
deny contains sprintf(
	"SI-7(9): %q edge workload %q must require attestation",
	[classification, input.instance_id],
) if {
	input.service_type in _edge_services
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.attestation_required == false
}

# SC-28: a classified edge node must encrypt local disk (physical exposure).
deny contains sprintf(
	"SC-28: %q edge node %q must enable disk_encryption",
	[classification, input.instance_id],
) if {
	input.service_type == "edge-node"
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.disk_encryption == false
}

# Obligation: record the attestation/image posture in the audit trail so
# a compromised edge node is detectable post-hoc (SI-4).
obligations contains "record-edge-attestation" if {
	input.service_type in _edge_services
}
