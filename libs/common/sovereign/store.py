import json
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError
from .models import ServiceInstance, Binding
from .settings import get_settings

class Store:
    def __init__(self):
        s = get_settings()
        self.ddb = boto3.resource(
            "dynamodb",
            region_name=s.aws_region,
            endpoint_url=s.dynamodb_endpoint,
            aws_access_key_id="local",
            aws_secret_access_key="local",
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
        instance.updated_at = datetime.now(timezone.utc).isoformat()
        self.instances.put_item(Item={"instance_id": instance.instance_id, "payload": instance.model_dump_json()})

    def delete_instance(self, instance_id: str):
        self.instances.delete_item(Key={"instance_id": instance_id})

    def put_binding(self, binding: Binding):
        self.bindings.put_item(Item={"binding_id": binding.binding_id, "payload": binding.model_dump_json()})

    def get_binding(self, binding_id: str) -> Binding | None:
        r = self.bindings.get_item(Key={"binding_id": binding_id})
        item = r.get("Item")
        return Binding.model_validate(json.loads(item["payload"])) if item else None

    def delete_binding(self, binding_id: str):
        self.bindings.delete_item(Key={"binding_id": binding_id})
