# CM — Configuration Management

The chassis treats every provisioned resource's configuration as an
**immutable artefact**. The control plane renders the Envoy bootstrap,
validates it against the Pydantic Envoy-v3 subset, and writes it under
a versioned S3 key (`instances/{id}/v{n}/envoy.yaml`). The OSB binding
returns the versioned config URL — clients never resolve to "latest".

The platform's own configuration follows the same discipline: services
are deployed as container images tagged with the git SHA, the OPA
policy bundle is read-only mounted from `policies/`, and the catalogue
ships as code (CatalogStore is seeded from in-repo definitions on
startup).

## Control mapping

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| **CM-2** Baseline Configuration | implemented | The baseline is the git revision that built the running image. Container images are tagged `{repo}:{sha}` in CI; `latest` is set on push-to-main so rollback is `docker tag :sha :latest`. The Envoy config baseline for each instance is the immutable S3 artefact at v1. | `.github/workflows/ci.yml::docker-build`; `apps/control-plane/app/main.py::render` |
| **CM-2(2)** Automation Support | implemented | Every change to the chassis goes through the GitHub Actions pipeline: ruff + mypy + pytest + opa test + (Phase 5.2) trivy + multi-service docker build. Merges to `main` are blocked until all jobs pass. | `.github/workflows/ci.yml` |
| **CM-3** Configuration Change Control | implemented | Every chassis change lands as a git commit with a structured message (feat/fix/chore + roadmap task ref). The `policy.evaluated` audit event records the policy-bundle version at evaluation time. Service-pack policy bundles are versioned in the pack manifest (Phase 1.9). | `git log --oneline`; `libs/common/sovereign/packs/__init__.py` |
| **CM-3(2)** Test, Validate, and Document Changes | implemented | The 218-test pytest suite + 42 OPA tests + 7 portal a11y tests run on every PR. Every roadmap task lands as one commit with documentation in the commit body. | `.github/workflows/ci.yml::test`, `policy-test`, `portal` |
| **CM-4** Impact Analyses | implemented (process) | The pack registration system (Phase 1.9) makes the per-pack impact surface explicit — a pack's `pack.toml` declares its renderers, connectors, catalogue entries, and policy bundles. The continuous monitor (5.2) verifies that registered packs and the running set match. | `libs/common/sovereign/packs/__init__.py` |
| **CM-5** Access Restrictions for Change | implemented | Code changes require a PR review (GitHub branch protection — agency operational config, not in this repo). The OPA policy bundle is read-only mounted (`./policies:/policies:ro`); the chassis container has no write capability against the bundle. | `docker-compose.yml::opa` |
| **CM-6** Configuration Settings | implemented | All settings load from `Settings` class (`libs/common/sovereign/settings.py`) which reads typed env vars with safe defaults. The Settings class also implements the production sentinel check: dev-default values (`dev-token`, `broker`/`broker`, `minioadmin`) log ERROR when ENV=production. | `libs/common/sovereign/settings.py::get_settings`; `tests/test_settings.py::test_production_logs_warning_for_dev_defaults` |
| **CM-7** Least Functionality | implemented | The `sovereign.base.allowed_services` policy rejects any service_type or plan_id not in the tenant's approved list. Combined with the `discover_packs` mechanism (Phase 1.9 pack registration), tenants only see and can provision services from explicitly-installed packs. | `policies/base/allowed_services.rego`; `policies/tests/allowed_services_test.rego` |
| **CM-8** System Component Inventory | implemented | DynamoDB carries the live inventory of every provisioned instance (`store.list_instances()`) and its rendered config version. The portal Instances dashboard surfaces the same data for human review. | `libs/common/sovereign/store.py::list_instances`; `apps/portal/src/pages/Instances.tsx` |
| **CM-8(2)** Automated Maintenance | implemented (continuous reconciliation) | The continuous monitor (5.2) reconciles DynamoDB-claimed state against S3-rendered artefacts every hour and pages on-call when they diverge. | `scripts/continuous-monitor.py::check_state_drift` |
| **CM-9** Configuration Management Plan | implemented | This SSP chapter, plus the README's "Core design" section, plus the per-pack manifest schema. | `docs/ssp/controls/cm.md` (this file); `README.md` |
| **CM-10** Software Usage Restrictions | inherited | License compliance for chassis components (FastAPI, OPA, ClickHouse, Tailwind) is documented in the agency's open-source review (organizational). |  |
| **CM-11** User-Installed Software | implemented | Tenants cannot install software on the chassis itself; they can only request the service types the catalogue exposes. The OPA `allowed_services` rule (CM-7) enforces this. | Same as CM-7. |

## High overlay

| Additional | Note |
| --- | --- |
| CM-3(7) Review System Changes | Pair every PR with a security-reviewer-agent run; add to PR template (POA&M 5.2-E). |
| CM-8(3) Automated Unauthorised Component Detection | Trivy scan in CI (Phase 5.2) flags unexpected packages; pair with an SBOM diff. |
