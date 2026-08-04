"""Builtin plugin: API REST + JSONPath."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from jsonpath_ng import parse as jsonpath_parse

from ..base import DataSourcePlugin, FetchContext


class RestJsonPathPlugin(DataSourcePlugin):
    id = "rest_jsonpath"
    name = "API REST (JSONPath)"
    description = "GET HTTP + extraction JSONPath (jsonpath-ng)"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "title": "URL",
                    "default": "https://httpbin.org/json",
                },
                "jsonpath": {
                    "type": "string",
                    "title": "JSONPath",
                    "default": "$.slideshow.author",
                },
                "timeout_s": {"type": "number", "title": "Timeout (s)", "default": 5.0},
                "headers_json": {
                    "type": "string",
                    "title": "Headers JSON (optionnel)",
                    "default": "{}",
                },
            },
            "required": ["url", "jsonpath"],
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        url = str(config.get("url") or "").strip()
        path = str(config.get("jsonpath") or "").strip()
        if not url or not path:
            return False
        try:
            jsonpath_parse(path)
        except Exception:
            return False
        headers_raw = config.get("headers_json") or "{}"
        try:
            h = json.loads(headers_raw) if isinstance(headers_raw, str) else headers_raw
            return isinstance(h, dict)
        except Exception:
            return False

    def fetch_data(self, config: dict[str, Any], context: FetchContext | None = None) -> Any:
        url = str(config.get("url") or "")
        path = str(config.get("jsonpath") or "$")
        timeout = max(0.5, float(config.get("timeout_s") or 5))
        headers_raw = config.get("headers_json") or "{}"
        headers = json.loads(headers_raw) if isinstance(headers_raw, str) else dict(headers_raw)
        headers = {**{"User-Agent": "pixoo-studio/0.2"}, **headers}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        matches = jsonpath_parse(path).find(data)
        if not matches:
            return None
        value = matches[0].value
        # si string non numérique, renvoyer dict pour debug UI
        num = self.extract_numeric(value)
        if num is not None:
            return num
        return {"value": value, "raw": value}


PLUGIN = RestJsonPathPlugin()
