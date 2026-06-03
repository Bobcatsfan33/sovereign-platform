# ADR 0001: Initial Enterprise Authorization Boundary

## Status

Accepted for Sprint 0.

## Context

The repository contains a base chassis and ten service-pack families. Authorizing
the full catalog at once would expand the assessment surface before the core
control plane has proven production operations.

The first enterprise deployment needs a boundary that is small enough to assess
and large enough to prove the platform thesis: governed self-service
provisioning, policy enforcement, auditability, and repeatable operations.

## Decision

The first authorization boundary is the base chassis plus one production pack:

- Broker API
- Control plane
- Audit service
- Metering service
- OPA policy bundle
- Portal
- Shared libraries under `libs/common/sovereign`
- One end-to-end provisioned service pack selected during pilot planning

Remaining packs are outside the first authorization boundary. They can be added
after the initial authorization through documented significant-change requests.

The default target environment is a government cloud region with inherited
controls from the cloud service provider. The exact target baseline must be
selected before Sprint 1 starts:

- FedRAMP Moderate / NIST 800-53 Moderate
- FedRAMP High
- DoD SRG IL4/IL5

## Consequences

- The execution loop only has to prove one pack end to end in the first
  production pilot.
- SSP and POA&M evidence should reference a narrow, testable system boundary.
- Pack APIs must support versioning and compatibility, but every pack does not
  need production-grade implementation before the first authorization.
- New packs after the first authorization require change-impact analysis,
  updated control evidence, and regression testing.

## Exit Criteria

- The selected target baseline and cloud environment are recorded in the SSP.
- The chosen pilot pack is named in the release plan.
- Boundary diagrams show every trust crossing, data store, external service, and
  administrative access path.
