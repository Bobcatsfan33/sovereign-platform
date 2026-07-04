# Service Pack Maturity

Sovereign Platform ships a broad pack catalog, but enterprise buyers need a
clear signal for what is ready to run, what is ready to pilot, and what still
needs customer-specific validation. Each pack manifest includes a `maturity`
field surfaced through `/healthz`.

## Levels

| Level | Meaning | Buyer expectation |
| --- | --- | --- |
| `ga` | Ready for controlled production adoption on the supported chassis path. | Standard security review, deployment hardening, and operational handoff. |
| `preview` | Functionally integrated and CI-gated, but needs a buyer pilot before production. | Pilot against representative accounts, IdP, data, or workload assumptions. |
| `lab` | Design-complete or specialized capability that needs real-environment validation. | Treat as roadmap/deal-shaping material until a joint validation completes. |

## Current Pack Posture

| Pack | Maturity | Rationale |
| --- | --- | --- |
| FinOps | `ga` | Uses existing metering and catalog behavior with no infrastructure apply path. |
| AI | `preview` | Needs governed workload validation for inference and RAG deployments. |
| Data | `preview` | Needs buyer cloud-account validation for Terraform apply paths. |
| SecOps | `preview` | Needs SIEM/log-retention assumptions mapped to buyer tooling. |
| Identity | `preview` | Needs customer directory, IdP, and SCIM mapping validation. |
| Multi-Cloud | `lab` | Needs live multi-cloud landing-zone validation. |
| Edge | `lab` | Needs hardware, attestation, and disconnected-site validation. |
| Comms | `lab` | Needs provider-specific email/chat integration. |
| Blockchain | `lab` | Needs buyer-specific ledger, HSM, and validator validation. |
