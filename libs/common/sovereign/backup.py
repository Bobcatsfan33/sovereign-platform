"""DynamoDB backup / restore for the chassis tables (E4).

A table-level snapshot — raw items, schema-agnostic — so an operator can run a
restore *drill* or recover from accidental data loss, complementing the
point-in-time recovery already enabled in Terraform. Items are captured and
restored exactly as stored; any schema differences are reconciled by
`migrations.py` on the next read, so a snapshot taken under an old schema
restores cleanly into newer code.

CLI: `python -m sovereign.backup {backup,restore,drill} --bucket B --key K`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import boto3

from .settings import get_settings

#: Tables included in a full chassis snapshot.
SNAPSHOT_TABLES: tuple[str, ...] = ("sovereign_instances", "sovereign_bindings")

#: Snapshot envelope version (the backup file format, not a record schema).
SNAPSHOT_FORMAT_VERSION = 1


def _ddb() -> Any:
    s = get_settings()
    return boto3.resource(
        "dynamodb", region_name=s.aws_region, endpoint_url=s.dynamodb_endpoint
    )


def _s3() -> Any:
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.aws_region,
    )


def _json_default(o: Any) -> Any:
    # DynamoDB returns numbers as Decimal; render them as plain JSON numbers.
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def _scan_all(table: Any) -> Iterator[dict]:
    kwargs: dict[str, Any] = {}
    while True:
        resp = table.scan(**kwargs)
        yield from resp.get("Items", [])
        last = resp.get("LastEvaluatedKey")
        if not last:
            return
        kwargs["ExclusiveStartKey"] = last


def export_snapshot(tables: tuple[str, ...] = SNAPSHOT_TABLES) -> dict[str, Any]:
    """Scan each table fully (paginated) into an in-memory snapshot."""
    ddb = _ddb()
    return {
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "tables": {name: list(_scan_all(ddb.Table(name))) for name in tables},
    }


def restore_snapshot(
    snapshot: dict[str, Any], *, only: tuple[str, ...] | None = None
) -> dict[str, int]:
    """Write every item in `snapshot` back via batched puts (idempotent —
    put_item overwrites by key). Returns the restored count per table."""
    ddb = _ddb()
    counts: dict[str, int] = {}
    for name, items in snapshot["tables"].items():
        if only is not None and name not in only:
            continue
        table = ddb.Table(name)
        with table.batch_writer() as writer:
            for item in items:
                writer.put_item(Item=item)
        counts[name] = len(items)
    return counts


def write_snapshot_to_s3(bucket: str, key: str, snapshot: dict[str, Any]) -> None:
    body = json.dumps(snapshot, default=_json_default).encode()
    _s3().put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")


def read_snapshot_from_s3(bucket: str, key: str) -> dict[str, Any]:
    obj = _s3().get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def run_drill(bucket: str, key: str) -> dict[str, Any]:
    """Backup -> read back -> compare. Proves the snapshot round-trips
    through S3 without touching live data, for a scheduled restore drill."""
    snapshot = export_snapshot()
    write_snapshot_to_s3(bucket, key, snapshot)
    restored = read_snapshot_from_s3(bucket, key)
    per_table = {
        name: len(items) for name, items in snapshot["tables"].items()
    }
    ok = all(
        len(restored["tables"].get(name, [])) == count
        for name, count in per_table.items()
    )
    return {"ok": ok, "counts": per_table, "key": key}


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore", "drill"])
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args(argv)

    if args.action == "backup":
        write_snapshot_to_s3(args.bucket, args.key, export_snapshot())
        print(f"backup written to s3://{args.bucket}/{args.key}")
    elif args.action == "restore":
        counts = restore_snapshot(read_snapshot_from_s3(args.bucket, args.key))
        print(f"restored: {counts}")
    else:
        result = run_drill(args.bucket, args.key)
        print(f"drill: {result}")
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
