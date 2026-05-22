from datetime import datetime, timezone
import clickhouse_connect
from .settings import get_settings

class Audit:
    def __init__(self):
        s = get_settings()
        self.enabled = True
        try:
            self.client = clickhouse_connect.get_client(host=s.clickhouse_host, port=s.clickhouse_port)
            self.client.command(f"CREATE DATABASE IF NOT EXISTS {s.clickhouse_database}")
            self.client.command(f"""
            CREATE TABLE IF NOT EXISTS {s.clickhouse_database}.events (
              ts DateTime64(3), actor String, action String, resource String, details String
            ) ENGINE = MergeTree ORDER BY (ts, action, resource)
            """)
            self.db = s.clickhouse_database
        except Exception:
            self.enabled = False

    def emit(self, action: str, resource: str, details: str = "", actor: str = "system"):
        if not self.enabled:
            return
        self.client.insert(f"{self.db}.events", [[datetime.now(timezone.utc), actor, action, resource, details]], column_names=["ts","actor","action","resource","details"])
