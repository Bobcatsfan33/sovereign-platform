"""DynamoDB-backed store for role bindings.

Table `sovereign_role_bindings` with composite key (principal HASH,
tenant_id RANGE). Each item carries a single Role.

Lookups:
  * `roles_for(principal)`       — every binding held by a principal
  * `roles_for_tenant(tenant)`   — every binding at a given tenant
  * `principals_with_role(role)` — every principal holding `role` (anywhere)

Effective-role resolution (i.e. roles a principal holds at a tenant via
inheritance from ancestor tenants) lives in `authz.py` because it needs
to walk both this store and the TenantStore.
"""

from __future__ import annotations

import json
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..settings import get_settings
from .models import Role, RoleBinding

ROLE_BINDING_TABLE = "sovereign_role_bindings"


class RoleStore:
    def __init__(self) -> None:
        s = get_settings()
        self._ddb = boto3.resource(
            "dynamodb",
            region_name=s.aws_region,
            endpoint_url=s.dynamodb_endpoint,
        )
        self._table = self._ddb.Table(ROLE_BINDING_TABLE)

    def ensure_table(self) -> None:
        existing = [t.name for t in self._ddb.tables.all()]
        if ROLE_BINDING_TABLE in existing:
            return
        self._ddb.create_table(
            TableName=ROLE_BINDING_TABLE,
            KeySchema=[
                {"AttributeName": "principal", "KeyType": "HASH"},
                {"AttributeName": "tenant_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "principal", "AttributeType": "S"},
                {"AttributeName": "tenant_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()

    def put(self, binding: RoleBinding) -> None:
        self._table.put_item(
            Item={
                "principal": binding.principal,
                "tenant_id": binding.tenant_id,
                "payload": binding.model_dump_json(),
            }
        )

    def get(self, principal: str, tenant_id: str) -> RoleBinding | None:
        resp = self._table.get_item(Key={"principal": principal, "tenant_id": tenant_id})
        item = resp.get("Item")
        payload = item.get("payload") if item else None
        if not isinstance(payload, str | bytes | bytearray):
            return None
        return RoleBinding.model_validate(json.loads(payload))

    def delete(self, principal: str, tenant_id: str) -> None:
        self._table.delete_item(Key={"principal": principal, "tenant_id": tenant_id})

    def roles_for(self, principal: str) -> list[RoleBinding]:
        """Every binding the principal holds, across all tenants."""
        try:
            resp = self._table.query(
                KeyConditionExpression="principal = :p",
                ExpressionAttributeValues={":p": principal},
            )
        except ClientError as exc:
            raise RuntimeError(f"role lookup failed: {exc}") from exc
        out: list[RoleBinding] = []
        for item in resp.get("Items", []):
            payload = item.get("payload")
            if not isinstance(payload, str | bytes | bytearray):
                continue
            out.append(RoleBinding.model_validate(json.loads(payload)))
        return out

    def roles_for_tenant(self, tenant_id: str) -> list[RoleBinding]:
        """Every binding at this tenant (any principal, any role)."""
        try:
            resp = self._table.scan(
                FilterExpression="tenant_id = :t",
                ExpressionAttributeValues={":t": tenant_id},
            )
        except ClientError as exc:
            raise RuntimeError(f"role lookup failed: {exc}") from exc
        out2: list[RoleBinding] = []
        for item in resp.get("Items", []):
            payload = item.get("payload")
            if not isinstance(payload, str | bytes | bytearray):
                continue
            out2.append(RoleBinding.model_validate(json.loads(payload)))
        return out2

    def principals_with_role(self, role: Role) -> list[RoleBinding]:
        """Every binding for a given role (typically used for tooling /
        audit, not request-time lookups)."""
        try:
            resp = self._table.scan()
        except ClientError as exc:
            raise RuntimeError(f"role scan failed: {exc}") from exc
        out: list[RoleBinding] = []
        for item in resp.get("Items", []):
            payload = item.get("payload")
            if not isinstance(payload, str | bytes | bytearray):
                continue
            binding = RoleBinding.model_validate(json.loads(payload))
            if binding.role == role:
                out.append(binding)
        return out


_ = Any
