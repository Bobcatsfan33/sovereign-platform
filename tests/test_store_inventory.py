"""State-store inventory indexing tests."""

from __future__ import annotations

import pytest
from moto import mock_aws
from sovereign.models import LbParameters, ServiceInstance
from sovereign.store import Store


def _instance(instance_id: str, organization_guid: str | None) -> ServiceInstance:
    return ServiceInstance(
        instance_id=instance_id,
        service_id="sovereign-envoy-lb",
        plan_id="standard-regional",
        organization_guid=organization_guid,
        parameters=LbParameters(),
    )


@mock_aws
def test_instances_table_has_organization_guid_gsi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sovereign import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(settings_mod.Settings, "dynamodb_endpoint", None)
    store = Store()
    store.ensure_tables()

    description = store.instances.meta.client.describe_table(
        TableName=store.instances.name
    )["Table"]
    indexes = {
        idx["IndexName"]: idx
        for idx in description.get("GlobalSecondaryIndexes", [])
    }

    assert Store.ORG_INDEX in indexes
    assert indexes[Store.ORG_INDEX]["KeySchema"] == [
        {"AttributeName": "organization_guid", "KeyType": "HASH"}
    ]


@mock_aws
def test_put_instance_projects_organization_guid_for_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sovereign import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(settings_mod.Settings, "dynamodb_endpoint", None)
    store = Store()
    store.ensure_tables()

    store.put_instance(_instance("i1", "agency-x"))

    row = store.instances.get_item(Key={"instance_id": "i1"})["Item"]
    assert row["organization_guid"] == "agency-x"


@mock_aws
def test_list_instances_filters_by_organization_guid_gsi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sovereign import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setattr(settings_mod.Settings, "dynamodb_endpoint", None)
    store = Store()
    store.ensure_tables()
    store.put_instance(_instance("i1", "agency-x"))
    store.put_instance(_instance("i2", "agency-y"))
    store.put_instance(_instance("i3", None))

    got = store.list_instances(organization_guid="agency-x")

    assert [inst.instance_id for inst in got] == ["i1"]
