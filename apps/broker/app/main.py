import secrets
import httpx
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sovereign.models import ProvisionRequest, UpdateRequest, BindRequest, ServiceInstance, Binding, InstanceStatus, RenderRequest
from sovereign.store import Store
from sovereign.audit import Audit
from sovereign.settings import get_settings

app = FastAPI(title="Sovereign Open Service Broker", version="0.1.0")
security = HTTPBasic(auto_error=False)
store = Store()
audit = Audit()

CATALOG = {
  "services": [{
    "id": "sovereign-envoy-lb",
    "name": "sovereign-envoy-lb",
    "description": "Self-service Envoy-based regional/multi-region load balancer",
    "bindable": True,
    "plans": [
      {"id":"standard-regional","name":"standard-regional","description":"Regional Envoy pool"},
      {"id":"multi-region","name":"multi-region","description":"Active-active regional Envoy pools"},
      {"id":"sidecar","name":"sidecar","description":"App-local sidecar load balancing"}
    ]
  }]
}

def auth(creds: HTTPBasicCredentials | None = Depends(security)):
    s = get_settings()
    if creds is None:
        return
    if not (secrets.compare_digest(creds.username, s.broker_username) and secrets.compare_digest(creds.password, s.broker_password)):
        raise HTTPException(status_code=401, detail="invalid credentials")

@app.on_event("startup")
def startup():
    store.ensure_tables()

@app.get("/healthz")
def healthz():
    return {"status":"ok"}

@app.get("/v2/catalog", dependencies=[Depends(auth)])
def catalog():
    return CATALOG

async def render(instance: ServiceInstance):
    s = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{s.control_plane_url}/render", json=RenderRequest(instance=instance).model_dump(mode="json"))
        r.raise_for_status()
        return r.json()

@app.put("/v2/service_instances/{instance_id}", status_code=201, dependencies=[Depends(auth)])
async def provision(instance_id: str, req: ProvisionRequest):
    existing = store.get_instance(instance_id)
    if existing:
        return {"dashboard_url": f"/dashboard/{instance_id}", "operation": "already_exists"}
    inst = ServiceInstance(instance_id=instance_id, **req.model_dump())
    store.put_instance(inst)
    artifact = await render(inst)
    inst.status = InstanceStatus.succeeded
    store.put_instance(inst)
    audit.emit("instance.provisioned", instance_id, str(artifact))
    return {"dashboard_url": f"/dashboard/{instance_id}", "operation": "provisioned", "config": artifact}

@app.patch("/v2/service_instances/{instance_id}", dependencies=[Depends(auth)])
async def update(instance_id: str, req: UpdateRequest):
    inst = store.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="instance not found")
    if req.plan_id:
        inst.plan_id = req.plan_id
    if req.parameters:
        inst.parameters = req.parameters
    inst.version += 1
    store.put_instance(inst)
    artifact = await render(inst)
    audit.emit("instance.updated", instance_id, str(artifact))
    return {"operation":"updated", "config": artifact}

@app.delete("/v2/service_instances/{instance_id}", dependencies=[Depends(auth)])
def deprovision(instance_id: str):
    if store.get_instance(instance_id):
        store.delete_instance(instance_id)
        audit.emit("instance.deprovisioned", instance_id)
    return {}

@app.put("/v2/service_instances/{instance_id}/service_bindings/{binding_id}", status_code=201, dependencies=[Depends(auth)])
def bind(instance_id: str, binding_id: str, req: BindRequest):
    inst = store.get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="instance not found")
    b = Binding(binding_id=binding_id, instance_id=instance_id, app_guid=req.app_guid, credentials={
        "config_url": f"/instances/{instance_id}/versions/{inst.version}/envoy.yaml",
        "instance_id": instance_id,
        "version": str(inst.version)
    })
    store.put_binding(b)
    audit.emit("binding.created", binding_id, instance_id)
    return {"credentials": b.credentials}

@app.delete("/v2/service_instances/{instance_id}/service_bindings/{binding_id}", dependencies=[Depends(auth)])
def unbind(instance_id: str, binding_id: str):
    store.delete_binding(binding_id)
    audit.emit("binding.deleted", binding_id, instance_id)
    return {}

@app.get("/v2/service_instances/{instance_id}/last_operation", dependencies=[Depends(auth)])
def last_operation(instance_id: str):
    inst = store.get_instance(instance_id)
    return {"state": inst.status.value if inst else "gone"}
