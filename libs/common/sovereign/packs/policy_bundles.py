"""Pack OPA policy-bundle collection (Step 0.3).

The layered decision model (`sovereign.base` + `sovereign.pack.<name>` +
`sovereign.tenant.<id>`) is fully designed and tested, but the running
OPA only ever loaded `policies/` (the base bundle) — pack and tenant
layers were exercised in Rego tests via `with data...` and were a no-op
at runtime. A pack could declare `policy_bundles = [Path(...)]` and
nothing consumed them.

This module closes that gap on the discovery side: after packs register,
`collect_policy_bundle_dirs()` returns every pack's bundle directories so
a deployment can mount/push them into OPA alongside the base bundle. The
broker/control-plane surface the list on `/healthz` and an operator
(or the compose/K8s manifest) points OPA at all of them.

Keeping this as a *collection* function rather than a live OPA push keeps
the chassis decoupled from how OPA is run (sidecar with mounted volumes,
bundle API, or OPA's `--bundle` flag) — the deployment chooses. The
continuous-monitor's `opa test` gate already enforces that each bundle is
valid and covered.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .discovery import registry

logger = logging.getLogger("sovereign.packs.policy")


def collect_policy_bundle_dirs() -> list[str]:
    """Return the de-duplicated, existing policy-bundle directories from
    every registered pack, as strings (for JSON/healthz serialisation).

    Non-existent paths are skipped with a warning so a pack that ships a
    mis-pathed bundle is visible in logs rather than silently dropped."""
    seen: set[str] = set()
    out: list[str] = []
    for pack in registry.all():
        for bundle in getattr(pack, "policy_bundles", []):
            p = Path(bundle)
            key = str(p)
            if key in seen:
                continue
            seen.add(key)
            if not p.exists():
                logger.warning(
                    "pack %r declares policy bundle %s but it does not exist", pack.name, key
                )
                continue
            out.append(key)
    return sorted(out)
