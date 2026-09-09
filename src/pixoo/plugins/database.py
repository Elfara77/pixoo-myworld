"""SQL / NoSQL database plugin (SQLAlchemy + optional pymongo)."""

from __future__ import annotations

import logging
from typing import Any

from pixoo.plugins.base import DataSourcePlugin
from pixoo.utils.jsonpath_parser import extract_jsonpath, extract_path
from pixoo.utils.secrets import resolve_secrets

logger = logging.getLogger("pixoo.plugins.database")


class DatabasePlugin(DataSourcePlugin):
    name = "database"
    description = "Query SQLite / Postgres / MySQL / MongoDB"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": {
                "type": "string",
                "label": "DB type",
                "enum": ["sqlite", "postgres", "mysql", "mongodb"],
                "default": "sqlite",
            },
            "connection_string": {
                "type": "string",
                "label": "Connection string",
                "required": True,
                "default": "sqlite:///./data/metrics.db",
            },
            "query": {
                "type": "string",
                "label": "SQL / Mongo filter JSON",
                "required": True,
                "default": "SELECT 1 AS value",
            },
            "params_json": {"type": "string", "label": "SQL params JSON", "default": "{}"},
            "collection": {"type": "string", "label": "Mongo collection", "default": ""},
            "extract_path": {"type": "string", "label": "JSONPath on rows", "default": "$[0].value"},
            "fallback_value": {"type": "string", "label": "Fallback", "default": "N/A"},
            "cache_ttl": {"type": "integer", "label": "Cache TTL (s)", "default": 60},
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        cfg = resolve_secrets(dict(config))
        db_type = str(cfg.get("type") or "sqlite")
        if not str(cfg.get("connection_string") or "").strip():
            return False
        if db_type == "mongodb":
            return bool(str(cfg.get("collection") or "").strip())
        return bool(str(cfg.get("query") or "").strip())

    def fetch_data(self, config: dict[str, Any]) -> Any:
        cfg = resolve_secrets(dict(config))
        db_type = str(cfg.get("type") or "sqlite").lower()
        fallback = cfg.get("fallback_value", "N/A")
        path = extract_path(cfg) or "$[0].value"

        if db_type == "mongodb":
            return self._fetch_mongo(cfg, path, fallback)

        try:
            from sqlalchemy import create_engine, text
        except ImportError as exc:
            raise RuntimeError("sqlalchemy required for database plugin") from exc

        import json

        params_raw = cfg.get("params") or cfg.get("params_json") or "{}"
        params = json.loads(params_raw) if isinstance(params_raw, str) else dict(params_raw or {})
        engine = create_engine(str(cfg["connection_string"]), pool_pre_ping=True)
        try:
            with engine.connect() as conn:
                result = conn.execute(text(str(cfg["query"])), params)
                rows = [dict(r._mapping) for r in result]
        finally:
            engine.dispose()

        if not rows:
            return fallback
        extracted = extract_jsonpath(rows, path, default=None)
        return fallback if extracted is None else extracted

    def _fetch_mongo(self, cfg: dict[str, Any], path: str, fallback: Any) -> Any:
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise RuntimeError("pymongo required for mongodb type") from exc
        import json

        client = MongoClient(str(cfg["connection_string"]), serverSelectionTimeoutMS=5000)
        try:
            # connection_string may include db; else use default
            db = client.get_default_database()
            if db is None:
                db = client["pixoo"]
            coll = db[str(cfg["collection"])]
            query_raw = cfg.get("query") or "{}"
            query = json.loads(query_raw) if isinstance(query_raw, str) else dict(query_raw)
            docs = list(coll.find(query).limit(20))
            for d in docs:
                d.pop("_id", None)
        finally:
            client.close()
        if not docs:
            return fallback
        extracted = extract_jsonpath(docs, path, default=None)
        return fallback if extracted is None else extracted


PLUGIN = DatabasePlugin()
