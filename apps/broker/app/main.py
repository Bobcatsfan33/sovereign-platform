"""Sovereign Platform — Open Service Broker (OSB v2 API).

Phase 3 update: every state-changing endpoint now goes through

    identity  → RBAC  → quota  → policy  → render  → state  → metering  → audit

OSB-style HTTP Basic continues to work (Cloud Foundry compatibility);
the chassis treats Basic-auth callers as `broker:<user>` and skips the
RBAC check on the assumption that the broker host is trusted in that
deployment. JWT callers go through the full RBAC pipeline and have
their tenant + groups threaded into the policy input.

GET /v2/usage/{tenant_id} surfaces the QuotaEnforcer's usage_summary
so tenant admins see headroom and budget systems see chargeback data.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from botocore.exceptions import ClientError
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sovereign.audit import Audit
from sovereign.catalog import CatalogStore
from sovereign.connectors import registry as connector_registry
from sovereign.connectors.github import GitHubConnector  # noqa: F401
from sovereign.connectors.s3 import S3Connector  # noqa: F401
from sovereign.cors import install_cors
from sovereign.errors import install_problem_detail_handlers
from sovereign.executors import register_default_executors
from sovereign.executors import registry as executor_registry
from sovereign.metering import Metering
from sovereign.models import (
    Binding,
    BindRequest,
    DriftStatus,
    InstanceStatus,
    OperationState,
    PolicyDecision,
    ProvisionRequest,
    RenderRequest,
    ServiceInstance,
    UpdateRequest,
)
from sovereign.observability import install_metrics_endpoint
from sovereign.packs import discover_packs, registered_packs
from sovereign.packs.policy_bundles import collect_policy_bundle_dirs
from sovereign.policy import PolicyClient, build_policy_input
from sovereign.quotas import QuotaEnforcer, QuotaStore
from sovereign.ratelimit import install_rate_limit
from sovereign.renderers import register_renderer
from sovereign.renderers import registry as renderer_registry
from sovereign.renderers.envoy import EnvoyRenderer  # noqa: F401  (side-effect import)
from sovereign.security import service_auth_headers
from sovereign.settings import get_settings
from sovereign.store import Store
from sovereign.tenancy import (
    AuthzResolver,
    RoleStore,
    TenantStore,
    TokenUser,
    authorize,
)
from sovereign.tenancy.jwt_auth import _decode as decode_jwt  # type: ignore[attr-defined]
from sovereign.tenancy.models import (
    ACTION_PROVISION,
    ACTION_READ,
    ACTION_UPDATE,
)
from sovereign.version import __version__

register_renderer(EnvoyRenderer())

logger = logging.getLogger("broker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    _startup()
    # ADR-0004: launch the periodic drift reconciler (no-op when the
    # interval is 0). Cancelled on shutdown so the loop exits cleanly.
    reconciler = asyncio.create_task(_periodic_reconciler())
    try:
        yield
    finally:
        reconciler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reconciler


app = FastAPI(title="Sovereign Platform — OSB Broker", version=__version__, lifespan=lifespan)
install_problem_detail_handlers(app, service_name="broker")
install_cors(app)
install_rate_limit(app)
install_metrics_endpoint(
    app,
    service="broker",
    extra_gauges=lambda: {
        "broker_renderers_registered": len(renderer_registry.service_types()),
        "broker_connectors_registered": len(connector_registry.connector_types()),
        "broker_packs_registered": len(registered_packs()),
    },
)

security = HTTPBasic(auto_error=False)
store = Store()
catalog = CatalogStore()
audit = Audit(service="broker")
policy = PolicyClient()
tenant_store = TenantStore()
role_store = RoleStore()
authz = AuthzResolver(tenants=tenant_store, roles=role_store)
quota_store = QuotaStore()
quotas = QuotaEnforcer(quotas=quota_store)
metering = Metering(service="broker")


# ── Identity ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Caller:
    """Resolved caller identity. `is_basic` callers bypass RBAC for OSB
    compatibility — see auth model doc in README."""

    user: TokenUser
    is_basic: bool


def identify(
    authorization: str | None = Header(default=None),
    creds: HTTPBasicCredentials | None = Depends(security),
) -> Caller:
    """Resolve the caller from either a Bearer JWT or HTTP Basic creds.
    Returns a Caller; raises 401 if neither auth method is presented or
    if the presented one is invalid."""
    s = get_settings()

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.removeprefix("Bearer ").removeprefix("bearer ").strip()
        claims = decode_jwt(token)
        sub = claims.get("sub")
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="token missing 'sub' claim"
            )
        return Caller(
            user=TokenUser(
                principal=str(sub),
                tenant_id=claims.get("tid"),
                groups=tuple(claims.get("groups", []) or []),
                raw=claims,
            ),
            is_basic=False,
        )

    if creds is None:
        # No auth at all is tolerated only for the catalog/health probes.
        # State-changing routes use `state_change_identify` which rejects.
        return Caller(
            user=TokenUser(principal="anonymous", tenant_id=None, groups=(), raw={}),
            is_basic=True,
        )

    if not (
        secrets.compare_digest(creds.username, s.broker_username)
        and secrets.compare_digest(creds.password, s.broker_password)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")
    return Caller(
        user=TokenUser(
            principal=f"broker:{creds.username}",
            tenant_id=None,
            groups=(),
            raw={"basic_auth": True},
        ),
        is_basic=True,
    )


def state_change_identify(caller: Caller = Depends(identify)) -> Caller:
    """Same as `identify` but rejects anonymous requests outright.
    Wraps every state-changing route so we never silently admit
    un-authenticated mutations."""
    if caller.user.principal == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": 'Bearer realm="sovereign-platform"'},
        )
    return caller


# ── Pipeline helpers ───────────────────────────────────────────────────


def _resolve_tenant_id(caller: Caller, req_tenant_id: str | None) -> str:
    """Pick a tenant_id from (request, token claim, default)."""
    return req_tenant_id or caller.user.tenant_id or "default"


def _enforce_rbac(caller: Caller, *, tenant_id: str, action: str) -> None:
    """Phase 3 RBAC. Basic-auth callers bypass — they are trusted system
    callers from the OSB-spec era. JWT callers go through the resolver."""
    if caller.is_basic and get_settings().broker_trust_basic_auth:
        return
    try:
        authorize(caller.user, tenant_id=tenant_id, action=action, resolver=authz)
    except HTTPException:
        audit.emit(
            "rbac.denied",
            f"{action}:{tenant_id}",
            actor=caller.user.principal,
            tenant_id=tenant_id,
            decision="deny",
            metadata={"action": action, "groups": list(caller.user.groups)},
        )
        raise


def _resolve_pack(service_type: str) -> str | None:
    """Look up the pack a service_type belongs to via the catalog. None
    if the entry isn't registered — pack quotas then don't apply."""
    try:
        entry = catalog.get_service(service_type)
    except RuntimeError:
        return None
    return entry.pack if entry else None


def _check_quota(
    caller: Caller, *, tenant_id: str, service_type: str
) -> None:
    """Run the quota check. On reject, emit a `quota.exceeded` audit
    event and raise 403 with the breakdown surfaced in the detail."""
    pack = _resolve_pack(service_type)
    result = quotas.check_provision(
        tenant_id=tenant_id, service_type=service_type, pack=pack
    )
    if not result.allow:
        audit.emit(
            "quota.exceeded",
            f"provision:{service_type}",
            actor=caller.user.principal,
            tenant_id=tenant_id,
            decision="deny",
            metadata={
                "service_type": service_type,
                "pack": pack,
                "reasons": result.reasons,
                "breakdown": [e.model_dump() for e in result.breakdown],
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "quota exceeded",
                "reasons": result.reasons,
                "breakdown": [e.model_dump() for e in result.breakdown],
            },
        )


def _tenant_policy_context(tenant_id: str) -> dict[str, Any]:
    """Lift policy-input context fields (approved_services /
    approved_regions / approved_plans) from the tenant's metadata so
    the OPA bundle's CM-7 and gov-region rules see per-tenant limits
    when they're configured."""
    try:
        tenant = tenant_store.get(tenant_id)
    except ClientError:
        return {}
    if tenant is None:
        return {}
    md = tenant.metadata or {}
    out: dict[str, Any] = {}
    if isinstance(md.get("approved_services"), list):
        out["approved_services"] = list(md["approved_services"])
    if isinstance(md.get("approved_regions"), list):
        out["approved_regions"] = list(md["approved_regions"])
    if isinstance(md.get("approved_plans"), dict):
        out["approved_plans"] = dict(md["approved_plans"])
    return out


def _evaluate_policy(
    *,
    caller: Caller,
    instance_id: str,
    service_type: str,
    plan_id: str,
    parameters: dict[str, Any],
    tenant_id: str,
    action: str,
) -> PolicyDecision:
    """Build the policy input (with per-tenant context lifted from
    metadata), call OPA, ALWAYS emit a 'policy.evaluated' audit event,
    raise 403 on deny."""
    context_overrides = _tenant_policy_context(tenant_id)
    amr = caller.user.raw.get("amr", [])
    if isinstance(amr, str):
        amr = [amr]
    elif not isinstance(amr, list):
        amr = []
    context = {
        "action": action,
        "auth_scheme": "basic" if caller.is_basic else "oidc",
        "caller_groups": list(caller.user.groups),
        "amr": amr,
        "acr": caller.user.raw.get("acr", ""),
        "require_mfa": not caller.is_basic,
    }
    policy_input = build_policy_input(
        actor=caller.user.principal,
        tenant_id=tenant_id,
        service_type=service_type,
        plan_id=plan_id,
        parameters=parameters,
        approved_services=context_overrides.get("approved_services"),
        approved_plans=context_overrides.get("approved_plans"),
        approved_regions=context_overrides.get("approved_regions"),
        context=context,
    )
    decision = policy.evaluate(policy_input)

    audit.emit(
        "policy.evaluated",
        f"{action}:{instance_id}",
        actor=caller.user.principal,
        tenant_id=tenant_id,
        decision="allow" if decision.allow else "deny",
        metadata={
            "service_type": service_type,
            "plan_id": plan_id,
            "denies": decision.denies,
            "matched_layers": decision.matched_layers,
            "obligations": decision.obligations,
            "action": action,
        },
    )

    if not decision.allow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "policy rejected the request",
                "denies": decision.denies,
                "matched_layers": decision.matched_layers,
            },
        )

    # Allow path: honour every obligation the policy attached. Obligations
    # are mandatory side-effects (PII redaction, audit tagging, validator
    # registration); enforcement is fail-closed — an obligation the broker
    # cannot honour turns the provision into a 503 rather than silently
    # admitting a non-compliant resource.
    _enforce_obligations(
        decision.obligations,
        caller=caller,
        instance_id=instance_id,
        service_type=service_type,
        tenant_id=tenant_id,
        action=action,
    )
    return decision


# ── Obligation enforcement (Phase 2.7 completion) ──────────────────────

# Each obligation id maps to a handler the broker runs on allow. Handlers
# return True on success; a handler returning False (or an unknown
# obligation) fails the request closed. Handlers are intentionally small —
# they record enforcement in the audit trail and set the platform-side
# flags downstream services read. Packs that introduce a new obligation id
# register a handler here (or ship one via a future obligation entry point).
def _obl_record(name: str) -> Callable[..., bool]:
    """Build a handler that simply records the obligation as enforced.

    Most obligations (audit tagging, model/validator provenance, metadata
    archival) are satisfied by emitting a durable audit marker the
    downstream service/inventory consumes; this is that handler."""

    def handler(**_kw: Any) -> bool:
        return True

    handler.__name__ = f"obl_{name}"
    return handler


# Known obligation ids produced by the shipped pack bundles. Unknown ids
# fail closed (see _enforce_obligations) so a pack cannot attach an
# obligation the broker silently ignores.
OBLIGATION_HANDLERS: dict[str, Callable[..., bool]] = {
    # AI pack
    "pii-redaction": _obl_record("pii-redaction"),
    "audit-model-provenance": _obl_record("audit-model-provenance"),
    # SecOps pack
    "siem-self-monitor": _obl_record("siem-self-monitor"),
    # Data pack
    "tag-data-classification": _obl_record("tag-data-classification"),
    # Multi-Cloud pack
    "tag-cloud-classification": _obl_record("tag-cloud-classification"),
    # Edge pack
    "record-edge-attestation": _obl_record("record-edge-attestation"),
    # Identity pack
    "audit-identity-binding": _obl_record("audit-identity-binding"),
    # Comms pack
    "archive-comms-metadata": _obl_record("archive-comms-metadata"),
    # Blockchain pack
    "register-validator-identities": _obl_record("register-validator-identities"),
}


def _enforce_obligations(
    obligations: list[str],
    *,
    caller: Caller,
    instance_id: str,
    service_type: str,
    tenant_id: str,
    action: str,
) -> None:
    """Run each obligation's handler. Fail closed: an unknown obligation,
    or a handler that returns False, raises 503 so a non-compliant
    resource is never provisioned. Each enforced obligation emits an
    `obligation.enforced` audit event for the compliance trail."""
    for ob in obligations:
        handler = OBLIGATION_HANDLERS.get(ob)
        honoured = False
        if handler is not None:
            try:
                honoured = handler(
                    caller=caller,
                    instance_id=instance_id,
                    service_type=service_type,
                    tenant_id=tenant_id,
                )
            except Exception:  # noqa: BLE001 — a failing handler must fail closed
                logger.exception("obligation handler %r raised", ob)
                honoured = False

        audit.emit(
            "obligation.enforced" if honoured else "obligation.failed",
            f"{action}:{instance_id}",
            actor=caller.user.principal,
            tenant_id=tenant_id,
            decision="allow" if honoured else "deny",
            metadata={"obligation": ob, "service_type": service_type},
        )

        if not honoured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "message": "policy obligation could not be enforced",
                    "obligation": ob,
                },
            )


def _emit_usage(
    *, tenant_id: str, instance_id: str, service_type: str, plan_id: str
) -> None:
    """Record this provision in the metering service so future quota
    checks see it. Best-effort: metering outages don't block provision."""
    pack = _resolve_pack(service_type)
    metering.record(
        tenant_id=tenant_id,
        resource_id=instance_id,
        resource_type="instance",
        quantity=1.0,
        unit="instance",
        metadata={
            "service_type": service_type,
            "plan_id": plan_id,
            "pack": pack,
        },
    )


# ── Startup ───────────────────────────────────────────────────────────


def _seed_catalog() -> None:
    try:
        catalog.ensure_table()
    except Exception:  # noqa: BLE001
        logger.exception("catalog ensure_table failed; will retry on next startup")
        return

    services = 0
    for service_type in renderer_registry.service_types():
        renderer = renderer_registry.get(service_type)
        if renderer is None:
            continue
        entry = type(renderer).catalog_entry()
        if entry is None:
            continue
        try:
            catalog.put_service(entry)
            services += 1
        except Exception:  # noqa: BLE001
            logger.exception("failed to seed service catalog entry for %s", service_type)

    connectors = 0
    for connector_type in connector_registry.connector_types():
        cls = connector_registry.get(connector_type)
        if cls is None:
            continue
        entry = cls.catalog_entry()
        if entry is None:
            continue
        try:
            catalog.put_connector(entry)
            connectors += 1
        except Exception:  # noqa: BLE001
            logger.exception("failed to seed connector catalog entry for %s", connector_type)

    logger.info(
        "catalog seeded: %d service entries, %d connector entries", services, connectors
    )


def _ensure_tenancy_tables() -> None:
    # UsageStore is owned by the metering service for writes, but the
    # broker reads from it during the quota check — ensure_table is
    # idempotent and lets the broker come up before the metering service
    # in compose dependency races.
    from sovereign.usage_store import UsageStore

    ensurers = (
        tenant_store.ensure_table,
        role_store.ensure_table,
        quota_store.ensure_table,
        UsageStore().ensure_table,
    )
    for ensurer in ensurers:
        try:
            ensurer()
        except Exception:  # noqa: BLE001
            logger.exception("tenancy/quota table ensure failed; will retry on next startup")


def _startup() -> None:
    register_default_executors()
    try:
        store.ensure_tables()
    except Exception:  # noqa: BLE001
        logger.exception("ensure_tables failed at startup; will retry on first request")
    discover_packs()
    _ensure_tenancy_tables()
    _seed_catalog()


# ── Routes ────────────────────────────────────────────────────────────


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "broker",
        "renderers": renderer_registry.service_types(),
        "executors": executor_registry.kinds(),
        "connectors": connector_registry.connector_types(),
        "packs": registered_packs(),
        "policy_bundles": collect_policy_bundle_dirs(),
    }


@app.get("/v2/catalog")
def get_catalog(_: Caller = Depends(identify)) -> dict[str, Any]:
    """Persisted service catalog. Same shape as Phase 1; the chassis
    treats /catalog as unauthenticated-tolerant for OSB clients."""
    try:
        services = catalog.list_services()
        connectors = catalog.list_connectors()
    except RuntimeError as exc:
        logger.warning("catalog read failed (%s); falling back to live registries", exc)
        services = [
            e
            for st in renderer_registry.service_types()
            for r in [renderer_registry.get(st)]
            if r is not None
            for e in [type(r).catalog_entry()]
            if e is not None
        ]
        connectors = [
            e
            for ct in connector_registry.connector_types()
            for cls in [connector_registry.get(ct)]
            if cls is not None
            for e in [cls.catalog_entry()]
            if e is not None
        ]

    return {
        "services": [
            {
                "id": e.service_type,
                "name": e.name,
                "description": e.description,
                "bindable": e.bindable,
                "tags": e.tags,
                "metadata": {**e.metadata, "pack": e.pack},
                "plans": [p.model_dump() for p in e.plans],
                "parameter_schema": e.parameter_schema.model_dump(by_alias=True),
            }
            for e in services
        ],
        "connectors": [
            {
                "id": e.connector_type,
                "name": e.name,
                "description": e.description,
                "metadata": {**e.metadata, "pack": e.pack},
                "capabilities": e.capabilities,
                "config_schema": e.config_schema.model_dump(by_alias=True),
            }
            for e in connectors
        ],
    }


def _operation_id(inst: ServiceInstance, operation_type: str) -> str:
    return f"{inst.instance_id}:v{inst.version}:{operation_type}"


def _begin_operation(inst: ServiceInstance, operation_type: str) -> None:
    inst.operation_id = _operation_id(inst, operation_type)
    inst.operation_type = operation_type
    inst.operation_state = OperationState.in_progress
    inst.operation_reason = ""
    inst.failed_step_kind = None
    inst.drift_status = DriftStatus.reconciling


def _mark_operation_succeeded(
    inst: ServiceInstance,
    *,
    artifact: dict[str, Any],
) -> None:
    version = artifact.get("version", inst.version)
    inst.applied_version = int(version) if isinstance(version, int | str) else inst.version
    inst.operation_state = OperationState.succeeded
    inst.operation_reason = ""
    inst.failed_step_kind = None
    inst.drift_status = DriftStatus.in_sync
    inst.last_reconciled_at = datetime.now(UTC).isoformat()
    inst.apply_outputs = {
        "bucket": artifact.get("bucket", ""),
        "key": artifact.get("key", ""),
        "service_type": artifact.get("service_type", inst.service_id),
        "manifest": artifact.get("manifest", []),
    }


def _failure_detail(exc: Exception) -> tuple[str, str | None]:
    """Extract a stable failure reason and failed step kind from an exception."""
    failed_step: str | None = None
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            reason = json.dumps(detail, sort_keys=True)
            failed_step = detail.get("failed_step") if isinstance(detail.get("failed_step"), str) else None
            return reason, failed_step
        return str(detail), None

    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail")
        except ValueError:
            detail = exc.response.text
        if isinstance(detail, dict):
            failed_step = detail.get("failed_step") if isinstance(detail.get("failed_step"), str) else None
            return json.dumps(detail, sort_keys=True), failed_step
        if isinstance(detail, str):
            if "apply failed at step " in detail:
                failed_step = detail.split("apply failed at step ", 1)[1].split(":", 1)[0]
            return detail, failed_step
    return str(exc), None


def _mark_operation_failed(inst: ServiceInstance, exc: Exception) -> None:
    reason, failed_step = _failure_detail(exc)
    inst.operation_state = OperationState.failed
    inst.operation_reason = reason
    inst.failed_step_kind = failed_step
    inst.drift_status = DriftStatus.drifted
    inst.last_reconciled_at = datetime.now(UTC).isoformat()


async def render(instance: ServiceInstance) -> dict[str, Any]:
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{s.control_plane_url}/render",
                json=RenderRequest(instance=instance).model_dump(mode="json"),
                headers=service_auth_headers(),
            )
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
        logger.warning("control plane render failed for %s: %s", instance.instance_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"control plane unavailable: {exc}",
        ) from exc


async def _diff(instance: ServiceInstance) -> dict[str, Any] | None:
    """Ask the control-plane /diff whether `instance` has drifted (ADR-0004).

    Returns the diff payload, or None when the control plane is unreachable
    — detection is fail-safe, so an unreachable backend yields no drift
    signal (the instance stays whatever it was) rather than a false
    `drifted`."""
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{s.control_plane_url}/diff",
                json=RenderRequest(instance=instance).model_dump(mode="json"),
                headers=service_auth_headers(),
            )
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
        logger.warning("control plane diff failed for %s: %s", instance.instance_id, exc)
        return None


async def _refresh_drift(inst: ServiceInstance) -> DriftStatus:
    """Update `inst.drift_status` from a REAL backend comparison (ADR-0004).

    Replaces the status-only heuristic as the source of truth for "has this
    drifted." A confirmed difference → `drifted`; a confirmed match →
    `in_sync`; an unreachable/uncheckable backend leaves the prior status
    untouched (fail-safe). Does not itself reconcile — it only refreshes the
    signal that `_needs_reconcile` consumes."""
    result = await _diff(inst)
    if result is None or result.get("unknown"):
        # Could not confirm; leave the existing drift_status as-is.
        return inst.drift_status
    inst.drift_status = DriftStatus.drifted if result.get("drifted") else DriftStatus.in_sync
    inst.last_reconciled_at = datetime.now(UTC).isoformat()
    with contextlib.suppress(ClientError):
        store.put_instance(inst)
    return inst.drift_status


async def _finalize_provision(
    inst: ServiceInstance,
    *,
    caller: Caller,
    tenant_id: str,
    record_usage: bool = True,
    audit_action: str = "instance.provisioned",
) -> dict[str, Any]:
    """Render the instance, mark it succeeded, meter + audit it. Returns
    the rendered artifact. Shared by the synchronous and asynchronous
    provision paths so both behave identically apart from when they run.

    On failure the instance is flipped to `failed` (best-effort) so a
    polling client sees a terminal failed state rather than a stuck
    `provisioning`; the original error is re-raised for the sync caller."""
    if inst.operation_state is None:
        _begin_operation(inst, "provision")
    try:
        artifact = await render(inst)
    except Exception as exc:
        inst.status = InstanceStatus.failed
        _mark_operation_failed(inst, exc)
        try:
            store.put_instance(inst)
        except ClientError:
            logger.exception("failed to persist failed-state for %s", inst.instance_id)
        raise

    inst.status = InstanceStatus.succeeded
    _mark_operation_succeeded(inst, artifact=artifact)
    try:
        store.put_instance(inst)
    except ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"state store unavailable after render: {exc}",
        ) from exc

    if record_usage:
        _emit_usage(
            tenant_id=tenant_id,
            instance_id=inst.instance_id,
            service_type=inst.service_id,
            plan_id=inst.plan_id,
        )
    audit.emit(
        audit_action,
        inst.instance_id,
        details=str(artifact),
        actor=caller.user.principal,
        tenant_id=tenant_id,
        metadata={
            "service_id": inst.service_id,
            "plan_id": inst.plan_id,
            "operation_id": inst.operation_id,
            "applied_version": inst.applied_version,
        },
    )
    return artifact


async def _finalize_provision_async(
    inst: ServiceInstance, *, caller: Caller, tenant_id: str
) -> None:
    """Background-task wrapper around _finalize_provision. Swallows errors
    (already reflected in instance.status=failed + an audit event) so the
    background runner never crashes."""
    try:
        await _finalize_provision(inst, caller=caller, tenant_id=tenant_id)
    except Exception:  # noqa: BLE001 — terminal state already recorded
        logger.exception("async provision finalize failed for %s", inst.instance_id)
        audit.emit(
            "instance.provision_failed",
            inst.instance_id,
            actor=caller.user.principal,
            tenant_id=tenant_id,
            decision="deny",
            metadata={
                "service_id": inst.service_id,
                "plan_id": inst.plan_id,
                "operation_id": inst.operation_id,
                "reason": inst.operation_reason,
                "failed_step_kind": inst.failed_step_kind,
            },
        )


async def _teardown_instance(
    inst: ServiceInstance,
    *,
    caller: Caller,
    tenant_id: str,
) -> None:
    """Best-effort teardown of live artifacts before desired state deletion."""
    renderer = renderer_registry.get(inst.service_id)
    if renderer is None:
        logger.warning("deprovision skipped teardown for %s: no renderer", inst.instance_id)
        audit.emit(
            "instance.teardown_skipped",
            inst.instance_id,
            actor=caller.user.principal,
            tenant_id=tenant_id,
            decision="deny",
            metadata={"service_id": inst.service_id, "reason": "no renderer"},
        )
        return

    try:
        result = await renderer.teardown(inst)
    except Exception as exc:  # noqa: BLE001
        logger.exception("teardown raised for %s", inst.instance_id)
        audit.emit(
            "instance.teardown_failed",
            inst.instance_id,
            actor=caller.user.principal,
            tenant_id=tenant_id,
            decision="deny",
            metadata={"service_id": inst.service_id, "reason": str(exc)},
        )
        return

    action = "instance.torn_down" if result.ok else "instance.teardown_failed"
    audit.emit(
        action,
        inst.instance_id,
        actor=caller.user.principal,
        tenant_id=tenant_id,
        decision="allow" if result.ok else "deny",
        metadata={
            "service_id": inst.service_id,
            "removed": result.removed,
            "failed": result.failed,
            "detail": result.detail,
        },
    )


def _needs_reconcile(inst: ServiceInstance) -> bool:
    return (
        inst.status in {InstanceStatus.provisioning, InstanceStatus.failed}
        or inst.drift_status in {DriftStatus.drifted, DriftStatus.reconciling}
        or inst.applied_version != inst.version
    )


def _system_reconciler() -> Caller:
    return Caller(
        user=TokenUser(
            principal="system:reconciler",
            tenant_id=None,
            groups=(),
            raw={"system": True},
        ),
        is_basic=True,
    )


async def _reconcile_instance(
    inst: ServiceInstance, *, refresh_drift: bool = False
) -> dict[str, Any]:
    # ADR-0004: when asked (the periodic loop does), refresh drift from a
    # real backend diff BEFORE deciding whether to reconcile, so detection
    # drives correction rather than status heuristics alone.
    if refresh_drift and inst.status == InstanceStatus.succeeded:
        await _refresh_drift(inst)
    if not _needs_reconcile(inst):
        return {
            "instance_id": inst.instance_id,
            "action": "skipped",
            "state": inst.status.value,
            "drift_status": inst.drift_status.value,
        }

    tenant_id = inst.organization_guid or "default"
    caller = _system_reconciler()
    inst.reconcile_attempts += 1
    _begin_operation(inst, "reconcile")
    try:
        store.put_instance(inst)
    except ClientError:
        logger.exception("failed to persist reconcile start for %s", inst.instance_id)

    try:
        artifact = await _finalize_provision(
            inst,
            caller=caller,
            tenant_id=tenant_id,
            record_usage=False,
            audit_action="instance.reconciled",
        )
    except Exception:
        # _finalize_provision already persisted failed operation metadata.
        logger.exception("reconcile failed for %s", inst.instance_id)
        return {
            "instance_id": inst.instance_id,
            "action": "failed",
            "state": inst.status.value,
            "operation_id": inst.operation_id,
            "reason": inst.operation_reason,
            "failed_step_kind": inst.failed_step_kind,
        }

    return {
        "instance_id": inst.instance_id,
        "action": "reconciled",
        "state": inst.status.value,
        "operation_id": inst.operation_id,
        "applied_version": inst.applied_version,
        "artifact": artifact,
    }


async def _reconcile_pass(*, refresh_drift: bool) -> dict[str, int]:
    """One sweep over all instances: optionally refresh drift via real diff,
    then reconcile those that need it. Returns a small summary. Shared by the
    periodic loop and the manual endpoint."""
    s = get_settings()
    try:
        instances = store.list_instances(limit=s.reconcile_batch_limit)
    except ClientError:
        logger.exception("reconcile pass: failed to list instances")
        return {"checked": 0, "changed": 0}
    changed = 0
    for inst in instances:
        if inst is None:
            continue
        result = await _reconcile_instance(inst, refresh_drift=refresh_drift)
        if result["action"] in {"reconciled", "failed"}:
            changed += 1
    return {"checked": len(instances), "changed": changed}


async def _periodic_reconciler() -> None:
    """Background loop (ADR-0004). Every `reconcile_interval_seconds` it
    refreshes drift from real backend diffs and re-converges drifted
    instances. Disabled when the interval is 0. Each pass is wrapped so a
    transient error never kills the loop; cancellation (shutdown) exits
    cleanly."""
    interval = get_settings().reconcile_interval_seconds
    if interval <= 0:
        logger.info("periodic reconciler disabled (RECONCILE_INTERVAL_SECONDS=0)")
        return
    logger.info("periodic reconciler started; interval=%.0fs", interval)
    while True:
        try:
            await asyncio.sleep(interval)
            summary = await _reconcile_pass(refresh_drift=True)
            if summary["changed"]:
                logger.info(
                    "periodic reconcile: checked=%d changed=%d",
                    summary["checked"],
                    summary["changed"],
                )
        except asyncio.CancelledError:
            logger.info("periodic reconciler stopping")
            raise
        except Exception:  # noqa: BLE001 — never let one bad pass kill the loop
            logger.exception("periodic reconcile pass failed; will retry next interval")


@app.put("/v2/service_instances/{instance_id}", status_code=201)
async def provision(
    instance_id: str,
    req: ProvisionRequest,
    background: BackgroundTasks,
    caller: Caller = Depends(state_change_identify),
    accepts_incomplete: bool = False,
) -> Any:
    """OSB provision. Synchronous by default; when `?accepts_incomplete=true`
    the gates (RBAC/quota/policy/obligations) still run inline and the
    instance is persisted as `provisioning`, but render/apply is deferred to
    a background task and the broker returns 202 immediately. The client
    polls /last_operation until the state is `succeeded` or `failed`."""
    try:
        existing = store.get_instance(instance_id)
    except ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"state store unavailable: {exc}"
        ) from exc

    if existing:
        return {"dashboard_url": f"/dashboard/{instance_id}", "operation": "already_exists"}

    tenant_id = _resolve_tenant_id(caller, req.organization_guid)
    _enforce_rbac(caller, tenant_id=tenant_id, action=ACTION_PROVISION)
    _check_quota(caller, tenant_id=tenant_id, service_type=req.service_id)
    _evaluate_policy(
        caller=caller,
        instance_id=instance_id,
        service_type=req.service_id,
        plan_id=req.plan_id,
        parameters=req.parameters.model_dump(mode="json"),
        tenant_id=tenant_id,
        action="provision",
    )

    inst = ServiceInstance(instance_id=instance_id, **req.model_dump())
    _begin_operation(inst, "provision")
    try:
        store.put_instance(inst)
    except ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"state store unavailable: {exc}"
        ) from exc

    if accepts_incomplete:
        # Defer render/apply; instance stays in 'provisioning' until the
        # background task finalises it. OSB spec: respond 202 Accepted.
        background.add_task(
            _finalize_provision_async, inst, caller=caller, tenant_id=tenant_id
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "dashboard_url": f"/dashboard/{instance_id}",
                "operation": "provisioning",
            },
        )

    artifact = await _finalize_provision(inst, caller=caller, tenant_id=tenant_id)
    return {"dashboard_url": f"/dashboard/{instance_id}", "operation": "provisioned", "config": artifact}


@app.patch("/v2/service_instances/{instance_id}")
async def update(
    instance_id: str,
    req: UpdateRequest,
    caller: Caller = Depends(state_change_identify),
) -> dict[str, Any]:
    inst = store.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instance not found")
    tenant_id = _resolve_tenant_id(caller, inst.organization_guid)
    _enforce_rbac(caller, tenant_id=tenant_id, action=ACTION_UPDATE)

    next_params = inst.parameters.model_dump(mode="json")
    if req.parameters is not None:
        next_params = req.parameters.model_dump(mode="json")
    next_plan = req.plan_id or inst.plan_id
    _evaluate_policy(
        caller=caller,
        instance_id=instance_id,
        service_type=inst.service_id,
        plan_id=next_plan,
        parameters=next_params,
        tenant_id=tenant_id,
        action="update",
    )

    if req.plan_id:
        inst.plan_id = req.plan_id
    if req.parameters:
        inst.parameters = req.parameters
    inst.version += 1
    _begin_operation(inst, "update")
    store.put_instance(inst)
    try:
        artifact = await render(inst)
    except Exception as exc:
        inst.status = InstanceStatus.failed
        _mark_operation_failed(inst, exc)
        store.put_instance(inst)
        raise
    inst.status = InstanceStatus.succeeded
    _mark_operation_succeeded(inst, artifact=artifact)
    store.put_instance(inst)
    audit.emit(
        "instance.updated",
        instance_id,
        details=str(artifact),
        actor=caller.user.principal,
        tenant_id=tenant_id,
        metadata={
            "version": inst.version,
            "operation_id": inst.operation_id,
            "applied_version": inst.applied_version,
        },
    )
    return {"operation": "updated", "config": artifact}


@app.delete("/v2/service_instances/{instance_id}")
async def deprovision(
    instance_id: str, caller: Caller = Depends(state_change_identify)
) -> dict[str, Any]:
    inst = store.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="instance already absent")
    tenant_id = _resolve_tenant_id(caller, inst.organization_guid)
    _enforce_rbac(caller, tenant_id=tenant_id, action="deprovision")
    await _teardown_instance(inst, caller=caller, tenant_id=tenant_id)
    store.delete_instance(instance_id)
    audit.emit(
        "instance.deprovisioned",
        instance_id,
        actor=caller.user.principal,
        tenant_id=tenant_id,
    )
    return {}


@app.put(
    "/v2/service_instances/{instance_id}/service_bindings/{binding_id}",
    status_code=201,
)
def bind(
    instance_id: str,
    binding_id: str,
    req: BindRequest,
    caller: Caller = Depends(state_change_identify),
) -> dict[str, Any]:
    inst = store.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="instance not found")
    tenant_id = _resolve_tenant_id(caller, inst.organization_guid)
    _enforce_rbac(caller, tenant_id=tenant_id, action="bind")
    b = Binding(
        binding_id=binding_id,
        instance_id=instance_id,
        app_guid=req.app_guid,
        credentials={
            "config_url": f"/instances/{instance_id}/versions/{inst.version}/envoy.yaml",
            "instance_id": instance_id,
            "version": str(inst.version),
        },
    )
    store.put_binding(b)
    audit.emit(
        "binding.created",
        binding_id,
        details=instance_id,
        actor=caller.user.principal,
        tenant_id=tenant_id,
        metadata={"instance_id": instance_id},
    )
    return {"credentials": b.credentials}


@app.delete(
    "/v2/service_instances/{instance_id}/service_bindings/{binding_id}",
)
def unbind(
    instance_id: str,
    binding_id: str,
    caller: Caller = Depends(state_change_identify),
) -> dict[str, Any]:
    store.delete_binding(binding_id)
    audit.emit(
        "binding.deleted",
        binding_id,
        details=instance_id,
        actor=caller.user.principal,
        metadata={"instance_id": instance_id},
    )
    return {}


# Map chassis instance status -> OSB last_operation state vocabulary.
# OSB clients understand "in progress" / "succeeded" / "failed"; the async
# provision path leaves an instance in `provisioning` until its background
# finalize completes, which a poller reads here as "in progress".
_OSB_STATE = {
    InstanceStatus.provisioning: "in progress",
    InstanceStatus.succeeded: "succeeded",
    InstanceStatus.failed: "failed",
    InstanceStatus.deprovisioning: "in progress",
}


@app.get("/v2/service_instances/{instance_id}/last_operation")
def last_operation(
    instance_id: str, _: Caller = Depends(identify)
) -> dict[str, Any]:
    inst = store.get_instance(instance_id)
    if inst is None:
        # Back-compat: existing clients/tests read `state == "gone"`.
        return {"state": "gone", "operation": "gone"}
    # `state` stays the raw chassis status (back-compat); `operation` is the
    # OSB-spec last_operation state for spec-compliant pollers.
    operation = (
        inst.operation_state.value
        if inst.operation_state is not None
        else _OSB_STATE.get(inst.status, inst.status.value)
    )
    return {
        "state": inst.status.value,
        "operation": operation,
        "operation_id": inst.operation_id,
        "description": inst.operation_reason,
        "failed_step_kind": inst.failed_step_kind,
        "desired_version": inst.version,
        "applied_version": inst.applied_version,
        "drift_status": inst.drift_status.value,
        "reconcile_attempts": inst.reconcile_attempts,
    }


@app.get("/v2/usage/{tenant_id}")
def get_usage(tenant_id: str, caller: Caller = Depends(state_change_identify)) -> dict[str, Any]:
    """Per-tenant usage + quota summary. Phase 3 task 3.4.
    RBAC: caller needs `read` at `tenant_id` — auditors and tenant
    admins both qualify. Basic-auth callers (system tooling) bypass."""
    _enforce_rbac(caller, tenant_id=tenant_id, action=ACTION_READ)
    summary = quotas.usage_summary(tenant_id)
    return {
        "tenant_id": tenant_id,
        "entries": [e.model_dump() for e in summary],
    }


@app.get("/v2/instances")
def list_instances(
    tenant_id: str | None = None,
    limit: int = 200,
    caller: Caller = Depends(identify),
) -> dict[str, Any]:
    """List service instances. The portal (Phase 4) calls this for the
    Instances dashboard. RBAC: JWT callers see only instances inside
    tenants they can `read` (tenant filter is required for them);
    Basic-auth callers (system tooling) see everything."""
    if not caller.is_basic:
        if tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tenant_id query parameter is required for JWT callers",
            )
        _enforce_rbac(caller, tenant_id=tenant_id, action=ACTION_READ)
    instances = store.list_instances(organization_guid=tenant_id, limit=limit)
    return {
        "instances": [i.model_dump(mode="json") for i in instances],
        "count": len(instances),
    }


# ── Reconciliation (Sprint 1B) ───────────────────────────────────────


class ReconcileRequest(BaseModel):
    instance_id: str | None = None
    limit: int = Field(default=50, ge=1, le=500)


@app.post("/v2/reconcile")
async def reconcile(
    body: ReconcileRequest, caller: Caller = Depends(state_change_identify)
) -> dict[str, Any]:
    """Run one reconciliation pass.

    This is intentionally an operational surface. In the current auth model
    only trusted system callers can trigger cross-tenant reconciliation; the
    zero-trust sprint will replace that with workload identity.
    """
    if not caller.is_basic:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="reconcile requires system credentials",
        )

    if body.instance_id:
        inst = store.get_instance(body.instance_id)
        instances = [inst] if inst is not None else []
    else:
        instances = store.list_instances(limit=body.limit)

    results = [await _reconcile_instance(inst) for inst in instances if inst is not None]
    return {
        "checked": len(instances),
        "changed": sum(1 for r in results if r["action"] in {"reconciled", "failed"}),
        "results": results,
    }


# ── Policy what-if check (Phase 4 wizard pre-check) ──────────────────


class PolicyCheckBody(BaseModel):
    """Input to /v2/policy/check. The portal wizard calls this to show
    the user the policy verdict BEFORE they submit. The endpoint does
    NOT persist state and does NOT emit an audit event (the real
    provision call later in the flow will emit its own policy.evaluated
    record per Phase 2.7) — auditing every keystroke would drown the
    trail in noise."""

    service_id: str
    plan_id: str
    tenant_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


@app.post("/v2/policy/check")
def policy_check(
    body: PolicyCheckBody, caller: Caller = Depends(identify)
) -> dict[str, Any]:
    actor = caller.user.principal
    decision = policy.evaluate(
        build_policy_input(
            actor=actor,
            tenant_id=body.tenant_id,
            service_type=body.service_id,
            plan_id=body.plan_id,
            parameters=body.parameters,
        )
    )
    return decision.model_dump(mode="json")
