# Sovereign Platform — Policy Bundle

OPA Rego policies that gate every provisioning request. The broker
builds a policy input document from the OSB request, calls
`data.sovereign.decision`, and rejects the request if `allow` is false.

## Layered model

```
sovereign.base.*       (this bundle)   — NIST 800-53 + GovCloud baseline
sovereign.pack.<name>  (per service pack) — pack-specific compliance rules
sovereign.tenant.<id>  (per agency)      — tenant-specific customizations
```

All three layers are evaluated; **any** deny rejects the request.
Base policies cannot be overridden. Phase 2 only ships `sovereign.base.*`;
packs add their rules in their own bundles (Phase 1 pack registration
already declares a `policy_bundles` list per pack — discovery loads them).

## Input document

The broker constructs the input from the incoming OSB request plus
tenant/principal context:

```json
{
  "actor": "alice@agency-x.gov",
  "tenant_id": "agency-x",
  "service_type": "sovereign-envoy-lb",
  "plan_id": "standard-regional",
  "parameters": {
    "region": "us-gov-west-1",
    "tls": true,
    "logging_enabled": true,
    "encryption_at_rest": true,
    "cipher_suites": ["TLS_AES_256_GCM_SHA384"],
    ...
  },
  "context": {
    "environment": "production",
    "classification": "CUI"
  },
  "approved_services": ["sovereign-envoy-lb"],
  "approved_regions": ["us-gov-west-1", "us-gov-east-1"]
}
```

## Decision shape

`data.sovereign.decision` returns:

```json
{
  "allow": false,
  "denies": [
    "SC-8: TLS must be enabled on network-facing services",
    "gov-region: 'us-east-1' is not an approved GovCloud region"
  ],
  "matched_rules": ["sovereign.base.transmission", "sovereign.base.gov_region"]
}
```

## Running tests locally

```
opa test policies/ -v
```

CI runs the same command alongside `pytest`; both must pass.

## Adding a new rule

1. Create `policies/base/<short_name>.rego` in package `sovereign.base.<short_name>`.
2. Use the `deny contains "<reason>" if { ... }` pattern. Reasons should
   cite the relevant control (e.g. `"SC-8: ..."`).
3. Import the new sub-package in `policies/base/compose.rego` and add
   a `deny contains msg if { msg := <short>.deny[_] }` line.
4. Add tests in `policies/tests/<short_name>_test.rego` covering both
   allow and deny paths.
