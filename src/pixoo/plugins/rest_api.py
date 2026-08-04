"""Generic REST API plugin with JSONPath, auth, retries, cache hints."""

from __future__ import annotations

import base64
import json
from typing import Any

from pixoo.plugins.base import DataSourcePlugin
from pixoo.utils.jsonpath_parser import extract_jsonpath, extract_path, validate_jsonpath
from pixoo.utils.network_utils import clamp_timeout, http_client, validate_url, with_retries
from pixoo.utils.secrets import resolve_secrets


class RestApiPlugin(DataSourcePlugin):
    name = "rest_api"
    description = "HTTP REST client with JSONPath extraction"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "url": {"type": "string", "label": "API URL", "required": True},
            "method": {
                "type": "string",
                "label": "Method",
                "enum": ["GET", "POST", "PUT", "DELETE"],
                "default": "GET",
            },
            "extract_path": {
                "type": "string",
                "label": "JSONPath",
                "required": True,
                "default": "$.data",
            },
            "timeout": {"type": "integer", "label": "Timeout (s)", "default": 5},
            "retries": {"type": "integer", "label": "Retries", "default": 3},
            "cache_ttl": {"type": "integer", "label": "Cache TTL (s)", "default": 60},
            "fallback_value": {"type": "string", "label": "Fallback", "default": ""},
            "headers_json": {"type": "string", "label": "Headers JSON", "default": "{}"},
            "params_json": {"type": "string", "label": "Query params JSON", "default": "{}"},
            "body_json": {"type": "string", "label": "Body JSON", "default": ""},
            "auth_type": {
                "type": "string",
                "label": "Auth",
                "enum": ["none", "bearer", "basic", "api_key"],
                "default": "none",
            },
            "auth_token": {"type": "string", "label": "Token / password", "default": ""},
            "auth_username": {"type": "string", "label": "Basic username", "default": ""},
            "api_key_name": {"type": "string", "label": "API key name", "default": "X-API-Key"},
            "api_key_in": {
                "type": "string",
                "label": "API key location",
                "enum": ["header", "query"],
                "default": "header",
            },
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        cfg = resolve_secrets(dict(config))
        if not validate_url(str(cfg.get("url") or "")):
            return False
        path = extract_path(cfg)
        if path and not validate_jsonpath(path):
            return False
        method = str(cfg.get("method") or "GET").upper()
        return method in ("GET", "POST", "PUT", "DELETE")

    def _parse_json_field(self, raw: Any, default: Any) -> Any:
        if raw is None or raw == "":
            return default
        if isinstance(raw, (dict, list)):
            return raw
        return json.loads(str(raw))

    def _apply_auth(self, headers: dict[str, str], params: dict[str, Any], config: dict[str, Any]) -> None:
        auth_type = str(config.get("auth_type") or "none").lower()
        token = str(config.get("auth_token") or "")
        if auth_type == "bearer" and token:
            headers["Authorization"] = f"Bearer {token}"
        elif auth_type == "basic":
            user = str(config.get("auth_username") or "")
            blob = base64.b64encode(f"{user}:{token}".encode()).decode()
            headers["Authorization"] = f"Basic {blob}"
        elif auth_type == "api_key" and token:
            name = str(config.get("api_key_name") or "X-API-Key")
            if str(config.get("api_key_in") or "header") == "query":
                params[name] = token
            else:
                headers[name] = token

    def fetch_data(self, config: dict[str, Any]) -> Any:
        cfg = resolve_secrets(dict(config))
        url = str(cfg["url"])
        method = str(cfg.get("method") or "GET").upper()
        timeout = clamp_timeout(cfg.get("timeout"), 5)
        retries = int(cfg.get("retries") if cfg.get("retries") is not None else 3)
        headers = self._parse_json_field(cfg.get("headers") or cfg.get("headers_json"), {})
        if not isinstance(headers, dict):
            headers = {}
        headers = {str(k): str(v) for k, v in headers.items()}
        params = self._parse_json_field(cfg.get("params") or cfg.get("params_json"), {})
        if not isinstance(params, dict):
            params = {}
        body = self._parse_json_field(cfg.get("body") or cfg.get("body_json"), None)
        self._apply_auth(headers, params, cfg)

        def _do() -> Any:
            with http_client(timeout=timeout) as client:
                resp = client.request(method, url, headers=headers, params=params, json=body)
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "")
                if "json" in ctype or resp.text[:1] in "{[":
                    return resp.json()
                return resp.text

        data = with_retries(_do, retries=retries)
        path = extract_path(cfg)
        if not path:
            return data
        extracted = extract_jsonpath(data, path, default=None)
        if extracted is None and "fallback_value" in cfg:
            fb = cfg.get("fallback_value")
            return None if fb == "" else fb
        return extracted

    def extract_value(self, data: Any) -> Any:
        return data


PLUGIN = RestApiPlugin()
