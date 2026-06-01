# AI pack policy — model governance + data-protection obligations.
#
# NIST 800-53: AC-4 (Information Flow Enforcement), SC-8/SC-28
# (transmission / at-rest protection), SI-12 (Information Handling and
# Retention). The AI pack adds rules the base bundle cannot express
# because they are model/data-classification specific.
#
# Two kinds of output:
#   deny        — hard rejections (request is blocked).
#   obligations — side-effects the broker MUST honour on allow (PII
#                 redaction, audit tagging). This activates the chassis
#                 PolicyDecision.obligations field, which until the AI
#                 pack had no producer.
#
# All rules are inert when the AI-specific input fields are absent, so
# the bundle is safe to install before any AI service is provisioned.
package sovereign.pack.ai

import rego.v1

# AC-4: a model serving CUI or SECRET data must declare an approved
# residency region (the base gov_region rule covers the allowed set;
# here we require the field is present for classified workloads).
deny contains sprintf(
	"AC-4: %q workload %q must declare data_residency",
	[classification, input.instance_id],
) if {
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	not input.parameters.data_residency
}

# SI-12: SECRET inference endpoints must keep logging enabled (no
# silent classified inference).
deny contains sprintf(
	"SI-12: SECRET workload %q must keep logging_enabled=true",
	[input.instance_id],
) if {
	input.parameters.classification == "SECRET"
	input.parameters.logging_enabled == false
}

# SC-28: a RAG workspace over CUI/SECRET must encrypt at rest.
deny contains sprintf(
	"SC-28: %q RAG workspace %q must set encryption_at_rest=true",
	[classification, input.instance_id],
) if {
	input.service_type == "rag-workspace"
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.encryption_at_rest == false
}

# ── Obligations (honoured by the broker on allow) ────────────────────

# SI-12: any CUI/SECRET workload that has not explicitly enabled PII
# redaction gets a mandatory redaction obligation rather than a denial —
# the request proceeds but the platform enforces redaction.
obligations contains "pii-redaction" if {
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.pii_redaction == false
}

# AU-2: every AI provision carries an audit-tagging obligation so the
# model + classification land in the audit record.
obligations contains "audit-model-provenance" if {
	input.service_type in {"inference-endpoint", "rag-workspace"}
}
