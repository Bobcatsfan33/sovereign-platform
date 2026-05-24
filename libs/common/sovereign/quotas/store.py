"""DynamoDB-backed QuotaStore.

Single table `sovereign_quotas` with composite key (tenant_id HASH,
scope RANGE). One item per (tenant, scope) tuple. List-by-tenant uses
a Query on the partition key.
"""

from __future__ import annotations

import json

import boto3
from botocore.exceptions import ClientError

from ..settings import get_settings
from .models import Quota

QUOTA_TABLE = "sovereign_quotas"


class QuotaStore:
    def __init__(self) -> None:
        s = get_settings()
        self._ddb = boto3.resource(
            "dynamodb",
            region_name=s.aws_region,
            endpoint_url=s.dynamodb_endpoint,
        )
        self._table = self._ddb.Table(QUOTA_TABLE)

    def ensure_table(self) -> None:
        existing = [t.name for t in self._ddb.tables.all()]
        if QUOTA_TABLE in existing:
            return
        self._ddb.create_table(
            TableName=QUOTA_TABLE,
            KeySchema=[
                {"AttributeName": "tenant_id", "KeyType": "HASH"},
                {"AttributeName": "scope", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "tenant_id", "AttributeType": "S"},
                {"AttributeName": "scope", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()

    def put(self, quota: Quota) -> None:
        self._table.put_item(
            Item={
                "tenant_id": quota.tenant_id,
                "scope": quota.scope,
                "payload": quota.model_dump_json(),
            }
        )

    def get(self, tenant_id: str, scope: str) -> Quota | None:
        resp = self._table.get_item(Key={"tenant_id": tenant_id, "scope": scope})
        item = resp.get("Item")
        payload = item.get("payload") if item else None
        if not isinstance(payload, str | bytes | bytearray):
            return None
        return Quota.model_validate(json.loads(payload))

    def delete(self, tenant_id: str, scope: str) -> None:
        self._table.delete_item(Key={"tenant_id": tenant_id, "scope": scope})

    def list_for_tenant(self, tenant_id: str) -> list[Quota]:
        try:
            resp = self._table.query(
                KeyConditionExpression="tenant_id = :t",
                ExpressionAttributeValues={":t": tenant_id},
            )
        except ClientError as exc:
            raise RuntimeError(f"quota query failed: {exc}") from exc
        out: list[Quota] = []
        for item in resp.get("Items", []):
            payload = item.get("payload")
            if not isinstance(payload, str | bytes | bytearray):
                continue
            out.append(Quota.model_validate(json.loads(payload)))
        return out
