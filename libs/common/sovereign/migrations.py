"""Payload schema versioning + lazy migration framework (E4).

Records are persisted as JSON payloads (DynamoDB single-table). Purely
additive fields are already safe — Pydantic ignores unknown keys and fills
new fields from defaults — but a *structural* change (renaming a field,
reshaping nested data, backfilling a derived value) cannot be expressed that
way without silently corrupting old rows.

This module stamps every payload with a `schema_version` and upgrades older
payloads to the current shape *on read*, applying each registered step in
order. So a deploy that changes a record's shape ships a migration here
instead of doing an offline table rewrite, and a half-migrated table keeps
serving because every read normalises to the current version.

To add a migration when you bump a record's shape:

    @register_migration("instance", from_version=1)
    def _v1_to_v2(payload: dict) -> dict:
        return {**payload, "region": payload.pop("aws_region", "us-east-1")}

then raise CURRENT_SCHEMA_VERSIONS["instance"] to 2 and the model default.
"""

from __future__ import annotations

from collections.abc import Callable

#: Current schema version per record kind. A write stamps this; a read
#: upgrades anything older to it.
CURRENT_SCHEMA_VERSIONS: dict[str, int] = {"instance": 1, "binding": 1}

#: kind -> {from_version: fn(payload) -> payload at from_version + 1}
_MIGRATIONS: dict[str, dict[int, Callable[[dict], dict]]] = {}


class SchemaMigrationError(RuntimeError):
    """A payload could not be brought to the current schema version."""


def register_migration(
    kind: str, *, from_version: int
) -> Callable[[Callable[[dict], dict]], Callable[[dict], dict]]:
    """Register the function that upgrades a `kind` payload from
    `from_version` to `from_version + 1`."""

    def decorator(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        _MIGRATIONS.setdefault(kind, {})[from_version] = fn
        return fn

    return decorator


def migrate_payload(raw: dict, *, kind: str) -> dict:
    """Return a copy of `raw` upgraded to the current schema version for
    `kind`. A payload with no `schema_version` is treated as v1 (legacy rows
    written before versioning). The input dict is never mutated.

    Raises SchemaMigrationError if a payload is newer than this code
    understands (fail closed rather than drop unknown shape) or if an
    intermediate migration step is missing."""
    current = CURRENT_SCHEMA_VERSIONS.get(kind)
    if current is None:
        raise SchemaMigrationError(f"unknown record kind {kind!r}")

    version = int(raw.get("schema_version", 1))
    if version > current:
        raise SchemaMigrationError(
            f"{kind} payload is schema v{version} but this build only "
            f"understands up to v{current}; deploy the newer code first"
        )

    payload = dict(raw)
    steps = _MIGRATIONS.get(kind, {})
    while version < current:
        step = steps.get(version)
        if step is None:
            raise SchemaMigrationError(
                f"no migration registered for {kind} v{version} -> v{version + 1}"
            )
        payload = step(payload)
        version += 1

    payload["schema_version"] = current
    return payload
