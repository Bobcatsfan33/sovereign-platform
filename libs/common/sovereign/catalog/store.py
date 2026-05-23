"""DynamoDB-backed CatalogStore.

Single table `sovereign_catalog` with composite key
(kind: 'service'|'connector', type_id: e.g. 'sovereign-envoy-lb' / 's3').
Both kinds in one table so the broker can list everything in two
queries (one per kind) without scanning across multiple tables.

The payload column is JSON-serialised pydantic so the schema can evolve
without DynamoDB migrations — readers ignore unknown fields, writers
emit the current shape.
"""

from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..settings import get_settings
from .models import ConnectorCatalogEntry, ServiceCatalogEntry

CATALOG_TABLE = "sovereign_catalog"


class CatalogStore:
    def __init__(self) -> None:
        s = get_settings()
        self._ddb = boto3.resource(
            "dynamodb",
            region_name=s.aws_region,
            endpoint_url=s.dynamodb_endpoint,
        )
        self._table = self._ddb.Table(CATALOG_TABLE)

    def ensure_table(self) -> None:
        existing = [t.name for t in self._ddb.tables.all()]
        if CATALOG_TABLE in existing:
            return
        self._ddb.create_table(
            TableName=CATALOG_TABLE,
            KeySchema=[
                {"AttributeName": "kind", "KeyType": "HASH"},
                {"AttributeName": "type_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "kind", "AttributeType": "S"},
                {"AttributeName": "type_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()

    # ── service entries ────────────────────────────────────────────

    def put_service(self, entry: ServiceCatalogEntry) -> None:
        self._table.put_item(
            Item={
                "kind": "service",
                "type_id": entry.service_type,
                "payload": entry.model_dump_json(by_alias=True),
            }
        )

    def get_service(self, service_type: str) -> ServiceCatalogEntry | None:
        resp = self._table.get_item(Key={"kind": "service", "type_id": service_type})
        item = resp.get("Item")
        payload = item.get("payload") if item else None
        if not isinstance(payload, str | bytes | bytearray):
            return None
        return ServiceCatalogEntry.model_validate(json.loads(payload))

    def list_services(self) -> list[ServiceCatalogEntry]:
        out: list[ServiceCatalogEntry] = []
        for item in self._query_kind("service"):
            payload = item.get("payload")
            if not isinstance(payload, str | bytes | bytearray):
                continue
            out.append(ServiceCatalogEntry.model_validate(json.loads(payload)))
        return out

    # ── connector entries ──────────────────────────────────────────

    def put_connector(self, entry: ConnectorCatalogEntry) -> None:
        self._table.put_item(
            Item={
                "kind": "connector",
                "type_id": entry.connector_type,
                "payload": entry.model_dump_json(by_alias=True),
            }
        )

    def get_connector(self, connector_type: str) -> ConnectorCatalogEntry | None:
        resp = self._table.get_item(Key={"kind": "connector", "type_id": connector_type})
        item = resp.get("Item")
        payload = item.get("payload") if item else None
        if not isinstance(payload, str | bytes | bytearray):
            return None
        return ConnectorCatalogEntry.model_validate(json.loads(payload))

    def list_connectors(self) -> list[ConnectorCatalogEntry]:
        out: list[ConnectorCatalogEntry] = []
        for item in self._query_kind("connector"):
            payload = item.get("payload")
            if not isinstance(payload, str | bytes | bytearray):
                continue
            out.append(ConnectorCatalogEntry.model_validate(json.loads(payload)))
        return out

    def delete(self, kind: str, type_id: str) -> None:
        self._table.delete_item(Key={"kind": kind, "type_id": type_id})

    # ── internal ───────────────────────────────────────────────────

    def _query_kind(self, kind: str) -> list[dict[str, Any]]:
        try:
            resp = self._table.query(
                KeyConditionExpression="#k = :k",
                ExpressionAttributeNames={"#k": "kind"},
                ExpressionAttributeValues={":k": kind},
            )
        except ClientError as exc:
            raise RuntimeError(f"catalog query failed: {exc}") from exc
        return resp.get("Items", [])
