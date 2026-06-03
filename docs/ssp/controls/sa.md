# SA — System and Services Acquisition

| Control | Status | Implementation | Evidence |
| --- | --- | --- | --- |
| **SA-3** System Development Life Cycle | implemented (chassis side) | The chassis follows the test-driven development loop documented in `~/.claude/rules/common/development-workflow.md`. Every feature ships with tests; every commit references its roadmap task. |  |
| **SA-8** Security and Privacy Engineering Principles | implemented | The chassis enforces least privilege (AC-6), fail-closed defaults (the policy client fails closed on any OPA error; the audit-service buffers rather than dropping on ClickHouse failure), and structured error handling (SI-11). |  |
| **SA-9** External System Services | implemented (boundary documented) | External services consumed by the chassis: ClickHouse cluster (audit), DynamoDB (state), S3 (artefacts), OPA (policy), agency IdP (identity). All are inside the authorisation boundary except the IdP. See [`../boundary-and-data-flow.md`](../boundary-and-data-flow.md). |  |
| **SA-10** Developer Configuration Management | implemented | Source control: GitHub with branch protection. Build manifests: `pyproject.toml`, `apps/portal/package.json`, container Dockerfiles. Every change goes through the CI gate. |  |
| **SA-11** Developer Testing and Evaluation | implemented | 218 Python tests, 42 OPA tests, 7 portal a11y tests on every PR. Coverage gate at 80% (Python) and 100% (OPA base bundle). | `.github/workflows/ci.yml` |
| **SA-15** Development Process, Standards, and Tools | implemented | Coding standards in `~/.claude/rules/{python,typescript}/`. Lint (ruff, eslint) + type-check (mypy, tsc) on every PR. |  |
| **SA-22** Unsupported System Components | implemented (image tags pinned) | Service Dockerfiles pin base-image major/minor lines, Kubernetes uses non-`latest` image tags, and OPA is pinned to `openpolicyagent/opa:1.6.0-rootless`. | `apps/*/Dockerfile`; `deploy/k8s/production.yaml`; `docker-compose.yml` |
