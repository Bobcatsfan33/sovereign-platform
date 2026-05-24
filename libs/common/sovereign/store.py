import json
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

from .models import Binding, ServiceInstance
from .settings import get_settings


class Store:
    def __init__(self):
        s = get_settings()
        # Credentials come from boto3's standard credential chain — env
        # vars in dev (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, set to
        # 'local' in .env.example for DynamoDB Local), IAM role in
        # production. No hardcoded secrets.
        self.ddb = boto3.resource(
            "dynamodb",
            region_name=s.aws_region,
            endpoint_url=s.dynamodb_endpoint,
        )
        self.instances = self.ddb.Table("sovereign_instances")
        self.bindings = self.ddb.Table("sovereign_bindings")

    def ensure_tables(self):
        existing = [t.name for t in self.ddb.tables.all()]
        if "sovereign_instances" not in existing:
            self.ddb.create_table(
                TableName="sovereign_instances",
                KeySchema=[{"AttributeName": "instance_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "instance_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            ).wait_until_exists()
        if "sovereign_bindings" not in existing:
            self.ddb.create_table(
                TableName="sovereign_bindings",
                KeySchema=[{"AttributeName": "binding_id", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "binding_id", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            ).wait_until_exists()

    def get_instance(self, instance_id: str) -> ServiceInstance | None:
        try:
            r = self.instances.get_item(Key={"instance_id": instance_id})
            item = r.get("Item")
            return ServiceInstance.model_validate(json.loads(item["payload"])) if item else None
        except ClientError:
            return None

    def put_instance(self, instance: ServiceInstance):
        instance.updated_at = datetime.now(UTC).isoformat()
        self.instances.put_item(Item={"instance_id": instance.instance_id, "payload": instance.model_dump_json()})

    def delete_instance(self, instance_id: str):
        self.instances.delete_item(Key={"instance_id": instance_id})

    def list_instances(
        self,
        *,
        organization_guid: str | None = None,
        limit: int = 200,
    ) -> list[ServiceInstance]:
        """Return up to `limit` instances visible to the caller.

        DynamoDB has no native filter on JSON payload fields, so we scan
        and filter in Python. This is fine while volumes are small; once
        instances grow beyond ~10k a GSI on organization_guid will be
        added (Phase 5 work). The scan is bounded by `limit` so the cost
        is predictable."""
        items: list[ServiceInstance] = []
        kwargs: dict = {"Limit": min(max(limit, 1), 1000)}
        try:
            response = self.instances.scan(**kwargs)
        except ClientError:
            return []
        for row in response.get("Items", []):
            payload = row.get("payload")
            if not isinstance(payload, str | bytes | bytearray):
                continue
            inst = ServiceInstance.model_validate(json.loads(payload))
            if organization_guid is not None and inst.organization_guid != organization_guid:
                continue
            items.append(inst)
            if len(items) >= limit:
                break
        return items

    def put_binding(self, binding: Binding):
        self.bindings.put_item(Item={"binding_id": binding.binding_id, "payload": binding.model_dump_json()})

    def get_binding(self, binding_id: str) -> Binding | None:
        r = self.bindings.get_item(Key={"binding_id": binding_id})
        item = r.get("Item")
        return Binding.model_validate(json.loads(item["payload"])) if item else None

    def delete_binding(self, binding_id: str):
        self.bindings.delete_item(Key={"binding_id": binding_id})
