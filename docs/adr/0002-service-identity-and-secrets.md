# ADR 0002: Service Identity And Secrets Model

## Status

Accepted for Sprint 0.

## Context

The current chassis supports local development with a shared bearer token and
sentinel defaults. That is useful for compose, but it is not an acceptable
enterprise or government production trust model.

Production deployments need per-workload identity, mutually authenticated
service-to-service traffic, managed secrets, and hard failure when development
sentinels are present.

## Decision

Production deployments must use all of the following:

- Workload identity for each service.
- Mutual TLS for service-to-service traffic through SPIFFE/SPIRE, a service
  mesh, or equivalent platform-native identity.
- OIDC/JWKS validation for human and external API callers.
- Managed secrets from the target environment, such as AWS Secrets Manager,
  HashiCorp Vault, or an agency-approved equivalent.
- KMS-backed encryption at rest for state, audit, and artifact stores.

The shared bearer token remains a local-development compatibility path only. It
must not be used for production authorization. HTTP Basic compatibility with OSB
clients must not bypass RBAC in production unless an explicit, documented
trusted-front-door exception is approved.

## Consequences

- `ENV=production` defaults to strict secret enforcement.
- `BROKER_TRUST_BASIC_AUTH` defaults to false in production.
- Future service manifests must define unique service accounts and identity
  bindings.
- Future Terraform must provision least-privilege IAM, KMS keys, secret access
  policies, and auditable rotation.

## Exit Criteria

- No production deployment starts with development sentinel secrets.
- Service-to-service calls authenticate the workload identity, not a flat shared
  token.
- Every state-changing broker call runs through identity, RBAC, quota, policy,
  execution, metering, and audit.
