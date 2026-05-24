"""DynamoDB-backed store for the tenant tree.

Single table `sovereign_tenants` keyed by `tenant_id` (PK). Parent
linkage is just a `parent_id` field on each item; ancestor / descendant
queries are computed in Python from the table contents.

For Phase 3 the tree is small (dozens of nodes per agency, hundreds
total) so the full-scan-and-walk approach is acceptable. If real
deployments balloon, a GSI on parent_id makes get_children() a Query
instead of a Scan.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..settings import get_settings
from .models import Tenant

TENANT_TABLE = "sovereign_tenants"


class TenantStore:
    def __init__(self) -> None:
        s = get_settings()
        self._ddb = boto3.resource(
            "dynamodb",
            region_name=s.aws_region,
            endpoint_url=s.dynamodb_endpoint,
        )
        self._table = self._ddb.Table(TENANT_TABLE)

    def ensure_table(self) -> None:
        existing = [t.name for t in self._ddb.tables.all()]
        if TENANT_TABLE in existing:
            return
        self._ddb.create_table(
            TableName=TENANT_TABLE,
            KeySchema=[{"AttributeName": "tenant_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "tenant_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()

    def put(self, tenant: Tenant) -> None:
        self._table.put_item(
            Item={"tenant_id": tenant.tenant_id, "payload": tenant.model_dump_json()}
        )

    def get(self, tenant_id: str) -> Tenant | None:
        resp = self._table.get_item(Key={"tenant_id": tenant_id})
        item = resp.get("Item")
        payload = item.get("payload") if item else None
        if not isinstance(payload, str | bytes | bytearray):
            return None
        return Tenant.model_validate(json.loads(payload))

    def delete(self, tenant_id: str) -> None:
        self._table.delete_item(Key={"tenant_id": tenant_id})

    def list_all(self) -> list[Tenant]:
        """Scan the whole table. For a tree of a few hundred nodes this
        is cheap; production may add an index if it grows."""
        try:
            resp = self._table.scan()
        except ClientError as exc:
            raise RuntimeError(f"tenant scan failed: {exc}") from exc
        out: list[Tenant] = []
        for item in resp.get("Items", []):
            payload = item.get("payload")
            if isinstance(payload, str | bytes | bytearray):
                out.append(Tenant.model_validate(json.loads(payload)))
        return out

    def get_children(self, tenant_id: str) -> list[Tenant]:
        return [t for t in self.list_all() if t.parent_id == tenant_id]

    def get_ancestors(self, tenant_id: str) -> list[Tenant]:
        """Return ancestors from immediate parent up to root, in that
        order. Empty list if `tenant_id` is a root or does not exist."""
        all_tenants = {t.tenant_id: t for t in self.list_all()}
        ancestors: list[Tenant] = []
        current = all_tenants.get(tenant_id)
        seen: set[str] = set()
        while current is not None and current.parent_id and current.parent_id not in seen:
            seen.add(current.parent_id)
            parent = all_tenants.get(current.parent_id)
            if parent is None:
                break
            ancestors.append(parent)
            current = parent
        return ancestors

    def get_descendants(self, tenant_id: str) -> list[Tenant]:
        """All tenants below `tenant_id` in the tree (transitive)."""
        all_tenants = self.list_all()
        children_by_parent: dict[str, list[Tenant]] = defaultdict(list)
        for t in all_tenants:
            if t.parent_id:
                children_by_parent[t.parent_id].append(t)
        out: list[Tenant] = []
        stack = list(children_by_parent.get(tenant_id, []))
        seen: set[str] = set()
        while stack:
            node = stack.pop()
            if node.tenant_id in seen:
                continue
            seen.add(node.tenant_id)
            out.append(node)
            stack.extend(children_by_parent.get(node.tenant_id, []))
        return out

    def is_ancestor_of(self, ancestor_id: str, descendant_id: str) -> bool:
        """True if `ancestor_id` is on the path from `descendant_id` to root."""
        return any(a.tenant_id == ancestor_id for a in self.get_ancestors(descendant_id))

    def path(self, tenant_id: str) -> list[Tenant]:
        """Root-to-tenant chain, inclusive. Empty if tenant does not exist."""
        target = self.get(tenant_id)
        if target is None:
            return []
        chain = list(reversed(self.get_ancestors(tenant_id)))
        chain.append(target)
        return chain


# Keep a no-op handle for type-checking environments that don't have
# boto3-stubs installed in the editor.
_ = Any
