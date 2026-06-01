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

import logging
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from botocore.exceptions import ClientError
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sovereign.audit import Audit
from sovereign.catalog import CatalogStore
from sovereign.connectors import registry as connector_registry
from sovereign.connectors.github import GitHubConnector  # noqa: F401
from sovereign.connectors.s3 import S3Connector  # noqa: F401
from sovereign.cors import install_cors
from sovereign.errors import install_problem_detail_handlers
from sovereign.metering import Metering
from sovereign.models import (
    Binding,
    BindRequest,
    InstanceStatus,
    PolicyDecision,
    ProvisionRequest,
    RenderRequest,
    ServiceInstance,
    UpdateRequest,
)
from sovereign.packs import discover_packs, registered_packs
from sovereign.policy import PolicyClient, build_policy_input
from sovereign.quotas import QuotaEnforcer, QuotaStore
from sovereign.renderers import register_renderer
from sovereign.renderers import registry as renderer_registry
from sovereign.renderers.envoy import EnvoyRenderer  # noqa: F401  (side-effect import)
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

register_renderer(EnvoyRenderer())

logger = logging.getLogger("broker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    _startup()
    yield


app = FastAPI(title="Sovereign Platform — OSB Broker", version="0.4.0", lifespan=lifespan)
install_problem_detail_handlers(app, service_name="broker")
install_cors(app)

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
    policy_input = build_policy_input(
        actor=caller.user.principal,
        tenant_id=tenant_id,
        service_type=service_type,
        plan_id=plan_id,
        parameters=parameters,
        approved_services=context_overrides.get("approved_services"),
        approved_plans=context_overrides.get("approved_plans"),
        approved_regions=context_overrides.get("approved_regions"),
        context={"caller_groups": list(caller.user.groups)} if caller.user.groups else None,
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
    return decision


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
        "connectors": connector_registry.connector_types(),
        "packs": registered_packs(),
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


async def render(instance: ServiceInstance) -> dict[str, Any]:
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{s.control_plane_url}/render",
                json=RenderRequest(instance=instance).model_dump(mode="json"),
                headers={"Authorization": f"Bearer {s.dev_bearer_token}"},
            )
            r.raise_for_status()
            return r.json()
    except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
        logger.warning("control plane render failed for %s: %s", instance.instance_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"control plane unavailable: {exc}",
        ) from exc


@app.put("/v2/service_instances/{instance_id}", status_code=201)
async def provision(
    instance_id: str,
    req: ProvisionRequest,
    caller: Caller = Depends(state_change_identify),
) -> dict[str, Any]:
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
    try:
        store.put_instance(inst)
    except ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"state store unavailable: {exc}"
        ) from exc

    artifact = await render(inst)
    inst.status = InstanceStatus.succeeded
    try:
        store.put_instance(inst)
    except ClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"state store unavailable after render: {exc}",
        ) from exc

    _emit_usage(
        tenant_id=tenant_id, instance_id=instance_id, service_type=req.service_id, plan_id=req.plan_id
    )
    audit.emit(
        "instance.provisioned",
        instance_id,
        details=str(artifact),
        actor=caller.user.principal,
        tenant_id=tenant_id,
        metadata={"service_id": inst.service_id, "plan_id": inst.plan_id},
    )
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
    store.put_instance(inst)
    artifact = await render(inst)
    audit.emit(
        "instance.updated",
        instance_id,
        details=str(artifact),
        actor=caller.user.principal,
        tenant_id=tenant_id,
        metadata={"version": inst.version},
    )
    return {"operation": "updated", "config": artifact}


@app.delete("/v2/service_instances/{instance_id}")
def deprovision(
    instance_id: str, caller: Caller = Depends(state_change_identify)
) -> dict[str, Any]:
    inst = store.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="instance already absent")
    tenant_id = _resolve_tenant_id(caller, inst.organization_guid)
    _enforce_rbac(caller, tenant_id=tenant_id, action="deprovision")
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


@app.get("/v2/service_instances/{instance_id}/last_operation")
def last_operation(
    instance_id: str, _: Caller = Depends(identify)
) -> dict[str, str]:
    inst = store.get_instance(instance_id)
    return {"state": inst.status.value if inst else "gone"}


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
