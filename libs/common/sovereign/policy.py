"""OPA policy engine client.

Phase 2: every provision/update request passes through this client
before the renderer runs. The broker builds a policy input document
from the OSB request, calls `data.sovereign.decision` on OPA, and
either proceeds (allow) or rejects with 403 (deny).

OPA exposes its decision API as:

    POST {opa_url}/{opa_decision_path}
    { "input": <input doc> }

…and returns:

    { "result": { "allow": bool, "denies": [...], "matched_layers": [...] } }

`PolicyClient.evaluate()` does the round-trip and returns a typed
`PolicyDecision`. On transport failure the client fails closed — a
deny with reason "policy engine unavailable" rather than allow-by-
default. This is the secure default for a compliance gate; operators
who want a tolerated-policy-outage path can flip the explicit flag.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import PolicyDecision, PolicyRequest
from .settings import get_settings

logger = logging.getLogger("sovereign.policy")


def build_policy_input(
    *,
    actor: str,
    tenant_id: str,
    service_type: str,
    plan_id: str,
    parameters: dict[str, Any],
    context: dict[str, Any] | None = None,
    approved_services: list[str] | None = None,
    approved_plans: dict[str, list[str]] | None = None,
    approved_regions: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the input document the chassis sends to OPA.

    `approved_services`, `approved_plans`, and `approved_regions` are
    per-tenant gates evaluated by `sovereign.base.allowed_services` and
    `sovereign.base.gov_region`. Phase 3 will populate them from the
    per-tenant config; for now callers pass None to opt out of those
    specific checks (CM-7 then permits any service that's catalog-
    registered, and the default GovCloud region set applies)."""
    doc: dict[str, Any] = {
        "actor": actor,
        "tenant_id": tenant_id,
        "service_type": service_type,
        "plan_id": plan_id,
        "parameters": dict(parameters),
        "context": context or {},
    }
    if approved_services is not None:
        doc["approved_services"] = list(approved_services)
    if approved_plans is not None:
        doc["approved_plans"] = dict(approved_plans)
    if approved_regions is not None:
        doc["approved_regions"] = list(approved_regions)
    return doc


class PolicyClient:
    """HTTP client to OPA. One instance per service is sufficient."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        decision_path: str | None = None,
        timeout: float = 3.0,
        fail_closed: bool = True,
    ) -> None:
        s = get_settings()
        self._base_url = (base_url or s.opa_url).rstrip("/")
        self._decision_path = (decision_path or s.opa_decision_path).lstrip("/")
        self._timeout = timeout
        self._fail_closed = fail_closed
        self._client = httpx.Client(timeout=timeout)

    def evaluate(self, policy_input: dict[str, Any]) -> PolicyDecision:
        """Send `policy_input` to OPA and return a PolicyDecision.

        Failures (network error, non-2xx, malformed response) translate
        to a deny PolicyDecision with the failure cited in `denies` and
        `reason` so the audit trail records exactly what happened. The
        broker treats every deny identically — a 403 with the denies in
        the body — so policy outages surface as "request rejected: policy
        engine unavailable" rather than as a 500 stacktrace."""
        url = f"{self._base_url}/{self._decision_path}"
        try:
            response = self._client.post(url, json={"input": policy_input})
        except httpx.HTTPError as exc:
            logger.warning("OPA call failed: %s", exc)
            return self._unavailable(f"transport error: {exc}")

        if response.status_code != 200:
            logger.warning(
                "OPA returned %s: %s", response.status_code, response.text[:200]
            )
            return self._unavailable(
                f"OPA returned {response.status_code}"
            )

        try:
            body = response.json()
            result = body.get("result")
        except Exception as exc:  # noqa: BLE001
            logger.warning("malformed OPA response: %s", exc)
            return self._unavailable(f"malformed response: {exc}")

        if result is None:
            # OPA returns {"result": null} when the decision path is
            # undefined — most commonly because no `default allow := false`
            # is in place. Treat as deny so a missing policy never silently
            # admits a request.
            return PolicyDecision(
                allow=False,
                reason="policy decision undefined",
                denies=["policy decision undefined (check sovereign.decision)"],
                matched_layers=[],
            )

        allow = bool(result.get("allow", False))
        denies = list(result.get("denies", []))
        matched_layers = list(result.get("matched_layers", []))
        reason = "; ".join(denies) if denies else ""

        return PolicyDecision(
            allow=allow,
            reason=reason,
            denies=denies,
            matched_layers=matched_layers,
        )

    def _unavailable(self, detail: str) -> PolicyDecision:
        if not self._fail_closed:
            logger.warning("policy engine unavailable but fail_closed=False; allowing")
            return PolicyDecision(allow=True, reason=f"policy bypass: {detail}")
        return PolicyDecision(
            allow=False,
            reason=f"policy engine unavailable: {detail}",
            denies=[f"policy engine unavailable: {detail}"],
            matched_layers=["transport"],
        )

    def close(self) -> None:
        self._client.close()


# Convenience: build a PolicyRequest from the typed model and the chassis
# input shape. Useful for code paths that want to log the request as a
# model rather than as a free dict.
def policy_request_from_input(policy_input: dict[str, Any]) -> PolicyRequest:
    return PolicyRequest(
        tenant_id=policy_input.get("tenant_id", ""),
        actor=policy_input.get("actor", ""),
        action="provision",
        resource=policy_input.get("service_type", ""),
        attributes=policy_input,
    )
