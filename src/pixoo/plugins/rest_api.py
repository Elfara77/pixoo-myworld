"""Generic REST API plugin with JSONPath extraction."""

from __future__ import annotations

import json
from typing import Any

import httpx
from jsonpath_ng import parse as jsonpath_parse

from pixoo.plugins.base import DataSourcePlugin


class RestApiPlugin(DataSourcePlugin):
    name = "rest_api"
    description = "HTTP GET/POST + JSONPath value extraction"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "url": {"type": "string", "label": "API URL", "required": True},
            "method": {
                "type": "string",
                "label": "Method",
                "enum": ["GET", "POST"],
                "default": "GET",
            },
            "jsonpath": {
                "type": "string",
                "label": "JSONPath",
                "required": True,
                "default": "$.data",
            },
            "timeout": {"type": "integer", "label": "Timeout (s)", "default": 5},
            "headers_json": {"type": "string", "label": "Headers JSON", "default": "{}"},
            "body_json": {"type": "string", "label": "POST body JSON", "default": ""},
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        if not str(config.get("url") or "").strip():
            return False
        path = str(config.get("jsonpath") or "").strip()
        if not path:
            return False
        try:
            jsonpath_parse(path)
        except Exception:
            return False
        method = str(config.get("method") or "GET").upper()
        return method in ("GET", "POST")

    def fetch_data(self, config: dict[str, Any]) -> Any:
        url = str(config["url"])
        method = str(config.get("method") or "GET").upper()
        timeout = float(config.get("timeout") or 5)
        headers_raw = config.get("headers_json") or "{}"
        headers = json.loads(headers_raw) if isinstance(headers_raw, str) else dict(headers_raw)
        headers = {**{"User-Agent": "pixoo-engine/2.0"}, **headers}
        body_raw = config.get("body_json") or ""
        json_body = json.loads(body_raw) if body_raw else None
        with httpx.Client(timeout=timeout) as client:
            if method == "POST":
                resp = client.post(url, headers=headers, json=json_body)
            else:
                resp = client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        matches = jsonpath_parse(str(config["jsonpath"])).find(data)
        if not matches:
            return None
        return matches[0].value


PLUGIN = RestApiPlugin()
