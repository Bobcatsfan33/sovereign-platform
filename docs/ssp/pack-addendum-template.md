# Pack SSP Addendum — Template

> Phase 5 task 5.7. Every service pack ships a copy of this template
> populated for its own services, renderers, connectors, and policy
> bundle. When the pack is installed, its addendum merges into the base
> SSP, extending the authorisation boundary.

Copy this file to `docs/ssp/pack-addenda/<pack-id>.md`, fill in every
section, and reference it from the pack's `pack.toml` `ssp_addendum`
field.

---

# {Pack Display Name} — SSP Addendum

| Field | Value |
| --- | --- |
| Pack id | `{pack-id}` (matches `packs/{pack-id}/pack.toml::id`) |
| Pack version | `{semver}` |
| Authorisation owner | `{name}, {email}` |
| Last review date | `{YYYY-MM-DD}` |

## 1 — Pack scope

What the pack adds to the chassis. Service types, renderers, connectors,
external dependencies. Be explicit about whether the pack introduces
any **net-new authorisation boundary expansion** (e.g. an inference
endpoint that calls out to a model provider's API) — if so, list every
new egress destination, the data classification flowing across it, and
the encryption-in-transit mechanism.

## 2 — New service types

| Service type | Plans | Bindable | Compliance controls auto-satisfied |
| --- | --- | --- | --- |
| `{svc-id}` | `{plan, plan, ...}` | yes/no | `{control-id list}` |

## 3 — New components

| Component | Role | Boundary | Network egress |
| --- | --- | --- | --- |
| `{name}` | `{purpose}` | in/out | `{destinations, ports}` |

## 4 — Pack-specific OPA policies

The pack ships its Rego bundle under `packs/{pack-id}/policies/`. List
each rule, the NIST control it maps to, and the deny reasons it can
produce.

| Rule (package) | Control | Deny reasons |
| --- | --- | --- |
| `sovereign.pack.{pack-id}.{rule}` | `{control-id}` | `{example deny strings}` |

Tests live under `packs/{pack-id}/policies/tests/`. Coverage gate
mirrors the base: 100% required on the pack bundle.

## 5 — Pack-specific data flows

Use the same table shape as the base SSP's
[`boundary-and-data-flow.md`](./boundary-and-data-flow.md) so the
combined picture is consistent.

| # | From | To | Protocol | Port | Direction | Auth | Encryption-in-transit |
| --- | --- | --- | --- | --- | --- | --- | --- |

## 6 — Pack-specific control mapping

Extend each relevant base SSP control chapter (`ac.md`, `au.md`,
`cm.md`, `sc.md`, etc.) with the pack's additional implementation
notes. Use the **same table format** as the base; do not invent new
columns.

Cite the pack's code paths and tests as evidence — relative to the
pack directory, e.g. `packs/{pack-id}/renderers/inference.py`.

## 7 — Pack-specific POA&M items

Pack-specific gaps live in this section, with the same severity scale
as the base POA&M. Items here merge into the base POA&M at install
time. Use the prefix `pack:{pack-id}:` for the ID so they're
distinguishable from base items.

| ID | Severity | Title | Source | Owner | Target | Status |
| --- | --- | --- | --- | --- | --- | --- |

## 8 — Pack-specific incident response

Any incident scenarios unique to this pack (e.g. AI Pack: model
poisoning, prompt-injection-driven exfiltration). Extend the base
runbook at [`../../incident-response.md`](../../incident-response.md)
with the pack's response procedures.

## 9 — Pack installation acceptance checklist

When this pack is installed in a deployment, the platform operator
confirms:

- [ ] The pack's policy bundle passes `opa test packs/{pack-id}/policies/`
      at 100% coverage.
- [ ] Every new service type appears in the catalogue's pack section.
- [ ] Every new component's image passes `trivy` at the same gate
      (zero critical/high CVEs).
- [ ] Every new data-flow row above corresponds to a documented egress
      allow-list rule.
- [ ] The pack-specific POA&M items are accepted by the AO.
