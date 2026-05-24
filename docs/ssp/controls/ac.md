# AC — Access Control

The chassis enforces access control through three concentric layers:

1. **Identity** — OSB Basic credentials (Cloud Foundry style) for
   programmatic callers, plus OIDC JWT bearer tokens for human callers
   (Phase 3.5). Anonymous callers are tolerated only on /healthz and
   the OSB catalogue probe.
2. **RBAC** — `AuthzResolver` (Phase 3) maps a caller's `tid` + `groups`
   claims to a role on a tenant. State-changing actions check the role
   has the necessary capability via `_enforce_rbac` before the request
   reaches the policy engine.
3. **Policy** — OPA `sovereign.base.allowed_services` (CM-7), plus pack
   and tenant rules that may further constrain (e.g. an AI Pack rule
   that requires a privacy impact assessment for inference endpoints
   serving CUI-classified data).

## Control mapping

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| **AC-2** Account Management | implemented (partial — accounts come from the IdP) | The chassis does not provision accounts. Group sync (`libs/common/sovereign/idp/group_sync.py`, Phase 3.5) reconciles IdP groups into local role bindings. Group→role mapping is configurable per tenant. | `libs/common/sovereign/idp/group_sync.py`; `tests/test_idp.py` |
| **AC-3** Access Enforcement | implemented | Every state-changing OSB endpoint depends on `state_change_identify` and calls `_enforce_rbac(caller, tenant_id=..., action=...)`. JWT callers without the required role on the target tenant receive 403. | `apps/broker/app/main.py`; `tests/test_broker_tenancy.py::test_provision_requires_provision_role` |
| **AC-4** Information Flow Enforcement | implemented | The OPA `sovereign.base.transmission` rule (SC-8) requires TLS on every network-facing service; `sovereign.base.allowed_services` (CM-7) blocks unapproved service types per tenant; the `gov_region` rule constrains all flows to GovCloud regions. | `policies/base/transmission.rego`, `policies/base/allowed_services.rego`, `policies/base/gov_region.rego`; `policies/tests/*` |
| **AC-5** Separation of Duties | implemented (chassis-enforced primitives) | The role catalogue defines distinct `tenant_admin`, `tenant_member`, and `auditor` roles. The same principal cannot both provision and audit unless explicitly granted both groups. | `libs/common/sovereign/tenancy/role_store.py`; `tests/test_tenancy.py::test_role_groups_are_disjoint` |
| **AC-6** Least Privilege | implemented | Three reinforcing mechanisms: (a) RBAC scopes capabilities to a tenant; (b) tenancy hierarchy lets a parent admin see descendants without seeing siblings (`AuthzResolver.visible_tenants`); (c) `sovereign.base.tenancy` Rego rule rejects requests with a missing or malformed `tenant_id`. | `libs/common/sovereign/tenancy/authz.py`; `policies/base/tenancy.rego`; `policies/tests/tenancy_test.rego` |
| **AC-7** Unsuccessful Logon Attempts | implemented (HTTP-layer) | The broker rate-limits Basic-auth failures via Starlette middleware (TODO Phase 5.2 — currently relies on the front-door API gateway to throttle). JWT verification failures land in the audit trail via `identify`. | `apps/broker/app/main.py::identify` (returns 401 with WWW-Authenticate); upstream throttling is organizational (POA&M item 5.2-A). |
| **AC-12** Session Termination | implemented (UI session) | The portal stores credentials in `sessionStorage`, which is cleared when the browser tab closes. JWT tokens carry the IdP-issued `exp` claim and are rejected when expired. | `apps/portal/src/hooks/useAuth.ts`; `libs/common/sovereign/tenancy/jwt_auth.py::_decode` (raises on `exp` past). |
| **AC-14** Permitted Actions without Identification or Authentication | implemented | The only un-authenticated endpoints are `/healthz` on each service and the OSB `/v2/catalog` probe (per OSB spec). Every state-changing endpoint requires authentication. Documented in [`../system-description.md`](../system-description.md). | Source: `grep -nE 'dependencies=\[Depends' apps/broker/app/main.py` shows every state-changing endpoint is gated. |
| **AC-17** Remote Access | inherited | Remote access to the chassis itself is via the hosting environment's authorised IdP (AWS IAM Identity Center, Azure AD). Documented in agency SSP wrapper. |  |
| **AC-18** Wireless Access | N/A | The chassis runs inside the agency's authorised cloud or datacentre boundary; no wireless interface is in scope. |  |
| **AC-22** Publicly Accessible Content | implemented | The portal is not public — it sits behind the agency IdP. The OSB catalogue endpoint returns metadata only (no PII, no secrets). | `apps/broker/app/main.py::catalog` returns the static `CATALOG` dict. |

## High overlay

| Additional | Note |
| --- | --- |
| AC-2(11) Inactive Accounts | Requires the IdP to disable inactive accounts within an agency-defined window. Add to group-sync runbook. |
| AC-2(12) Account Monitoring for Atypical Usage | Add ClickHouse alert on policy-deny spike per principal (POA&M 5.2-B). |
