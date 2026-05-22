"""DynamoDB-backed store for metering records.

Mirrors the pattern used by `Store` in store.py — single-table layout, JSON
payload — but the table key shape is different: `tenant_id` (HASH) plus a
sortable `event_id` (RANGE) of the form `{ts.isoformat()}#{resource_id}#{rand}`.
That key shape gives us efficient range queries by tenant + time window,
which is what the Phase 3 quota and chargeback system will need.

Resource-level filters are applied in Python after the DynamoDB query
returns, which is acceptable while volumes are small; GSIs can be added
later if filtering by resource_id or resource_type becomes hot.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .models import Usage
from .settings import get_settings

USAGE_TABLE = "sovereign_usage"


def _event_id(usage: Usage) -> str:
    """Sortable, unique event id. Sorts lexicographically by timestamp;
    a short random suffix prevents collisions on simultaneous writes."""
    suffix = secrets.token_hex(4)
    return f"{usage.ts.isoformat()}#{usage.resource_id}#{suffix}"


class UsageStore:
    def __init__(self) -> None:
        s = get_settings()
        self._ddb = boto3.resource(
            "dynamodb",
            region_name=s.aws_region,
            endpoint_url=s.dynamodb_endpoint,
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
        self._table = self._ddb.Table(USAGE_TABLE)

    def ensure_table(self) -> None:
        existing = [t.name for t in self._ddb.tables.all()]
        if USAGE_TABLE in existing:
            return
        self._ddb.create_table(
            TableName=USAGE_TABLE,
            KeySchema=[
                {"AttributeName": "tenant_id", "KeyType": "HASH"},
                {"AttributeName": "event_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "tenant_id", "AttributeType": "S"},
                {"AttributeName": "event_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()

    def record(self, usage: Usage) -> str:
        """Persist a single Usage record. Returns the generated event_id."""
        event_id = _event_id(usage)
        self._table.put_item(
            Item={
                "tenant_id": usage.tenant_id,
                "event_id": event_id,
                "payload": usage.model_dump_json(),
            }
        )
        return event_id

    def query(
        self,
        tenant_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        resource_id: str | None = None,
        resource_type: str | None = None,
        limit: int = 100,
    ) -> list[Usage]:
        """Query usage for a tenant in the given time window, optionally
        filtered by resource_id / resource_type. Returns most recent first.

        DynamoDB does the tenant+time range scan natively via the sort key;
        resource filters are applied in Python on the returned page."""
        # Time-bounded sort-key range. Event IDs start with the ISO timestamp,
        # so lexicographic comparison matches temporal ordering.
        key_conditions: dict[str, Any] = {"tenant_id": tenant_id}
        kwargs: dict[str, Any] = {"Limit": min(max(limit, 1), 1000), "ScanIndexForward": False}

        # Time-bounded sort-key range. event_id is "{ts.isoformat()}#{resource_id}#{rand}".
        # Comparison semantics:
        #   - since inclusive: ":lo = since.isoformat()" matches "since.iso#..." because
        #     the bare ISO is lex-less-than-or-equal-to any "iso#suffix" form.
        #   - until exclusive: ":hi = until.isoformat()" (without trailing delim) excludes
        #     events at the until boundary, since "until.iso" < "until.iso#suffix".
        if since is not None and until is not None:
            kwargs["KeyConditionExpression"] = (
                "tenant_id = :tid AND event_id BETWEEN :lo AND :hi"
            )
            kwargs["ExpressionAttributeValues"] = {
                ":tid": tenant_id,
                ":lo": since.isoformat(),
                ":hi": until.isoformat(),
            }
        elif since is not None:
            kwargs["KeyConditionExpression"] = "tenant_id = :tid AND event_id >= :lo"
            kwargs["ExpressionAttributeValues"] = {":tid": tenant_id, ":lo": since.isoformat()}
        elif until is not None:
            kwargs["KeyConditionExpression"] = "tenant_id = :tid AND event_id < :hi"
            kwargs["ExpressionAttributeValues"] = {":tid": tenant_id, ":hi": until.isoformat()}
        else:
            kwargs["KeyConditionExpression"] = "tenant_id = :tid"
            kwargs["ExpressionAttributeValues"] = {":tid": tenant_id}

        try:
            response = self._table.query(**kwargs)
        except ClientError as exc:
            raise RuntimeError(f"usage query failed: {exc}") from exc

        records: list[Usage] = []
        for item in response.get("Items", []):
            payload = item.get("payload")
            if not payload:
                continue
            usage = Usage.model_validate(json.loads(payload))
            if resource_id is not None and usage.resource_id != resource_id:
                continue
            if resource_type is not None and usage.resource_type != resource_type:
                continue
            records.append(usage)
        return records
