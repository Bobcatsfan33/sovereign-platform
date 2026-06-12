# Reference Deployment (S-4)

One always-on, hardened deployment that the existing hourly continuous-monitor
CI cron probes — converting the SSP from scaffold into continuous evidence.
FedRAMP 20x is continuous-evidence based; an assessor needs a running system,
and the hourly cron needs something real to monitor.

## What it runs

The full **strict production posture**, via the overlay in this directory:

- `ENV=production`, **OIDC verified** (`REQUIRE_OIDC=true`), **shared bearer off**
  (`SHARED_BEARER_AUTH_ENABLED=false`) — inherited from `../k8s/production.yaml`;
- **mesh mTLS strict** (`MTLS_REQUIRED=true`, `MESH_MTLS_STRICT=true`) — the
  `posture-patch.yaml` in this overlay;
- **generated credentials** (the `replace-me` secrets in `sovereign-runtime`
  and the OIDC issuer/audience are filled per-environment, never committed).

## Stand it up (k3s single node is sufficient, ~\$50/mo)

```bash
# 1. Deploy SPIRE first (sidecars go NotReady without SVIDs):
kubectl apply -f ../k8s/spire.yaml
# 2. Fill the real OIDC issuer/audience + generated secrets into sovereign-runtime,
#    then apply the overlay:
kubectl apply -k .
```

## Wire continuous monitoring

The hourly `continuous monitor` job in `.github/workflows/ci.yml` already runs
`scripts/continuous_monitor.py` against `AUDIT_SERVICE_URL`. Point that repo
secret at the reference deployment's audit-service URL (and set
`SOVEREIGN_BEARER_TOKEN` to an OIDC token for it). Results are emitted as JSON
and archived as CI run artifacts.

## Exit gate

The hourly job runs against the live reference URL for 30 consecutive days with
results archived — the KSI story in miniature. The reference runs the
production posture (OIDC on, shared bearer off, mTLS strict, generated
credentials) so what is monitored is what ships.
