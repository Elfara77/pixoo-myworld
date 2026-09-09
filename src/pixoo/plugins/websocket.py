"""WebSocket client plugin — background thread, last-value cache."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from pixoo.plugins.base import DataSourcePlugin
from pixoo.utils.jsonpath_parser import extract_jsonpath, extract_path
from pixoo.utils.network_utils import validate_url
from pixoo.utils.secrets import resolve_secrets

logger = logging.getLogger("pixoo.plugins.websocket")


class WebSocketPlugin(DataSourcePlugin):
    name = "websocket"
    description = "WebSocket stream client"
    supports_streaming = True

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._config: dict[str, Any] | None = None

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "url": {"type": "string", "label": "WebSocket URL", "required": True},
            "ping_interval": {"type": "integer", "label": "Ping interval", "default": 20},
            "ping_timeout": {"type": "integer", "label": "Ping timeout", "default": 10},
            "payload_type": {
                "type": "string",
                "label": "Payload",
                "enum": ["json", "text"],
                "default": "json",
            },
            "extract_path": {"type": "string", "label": "JSONPath", "default": "$.price"},
            "fallback_value": {"type": "string", "label": "Fallback", "default": "N/A"},
            "cache_ttl": {"type": "integer", "label": "Cache TTL (s)", "default": 5},
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        return validate_url(str(config.get("url") or ""), allow_ws=True)

    def start(self, config: dict[str, Any] | None = None) -> None:
        if config:
            self._config = resolve_secrets(dict(config))
        if not self._config or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="pixoo-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self) -> None:
        try:
            import websocket
        except ImportError:
            logger.error("websocket-client not installed")
            return
        assert self._config is not None
        cfg = self._config
        url = str(cfg["url"])
        path = extract_path(cfg) or "$.price"
        payload_type = str(cfg.get("payload_type") or "json")
        ping_interval = int(cfg.get("ping_interval") or 20)
        ping_timeout = int(cfg.get("ping_timeout") or 10)

        while not self._stop.is_set():
            try:
                ws = websocket.create_connection(
                    url,
                    ping_interval=ping_interval,
                    ping_timeout=ping_timeout,
                    timeout=10,
                )
                while not self._stop.is_set():
                    try:
                        raw = ws.recv()
                    except Exception:
                        break
                    if not raw:
                        continue
                    try:
                        if payload_type == "json":
                            data = json.loads(raw)
                            value = extract_jsonpath(data, path, default=data)
                        else:
                            value = raw
                        with self._lock:
                            self._last = value
                    except Exception as exc:
                        logger.debug("WS parse: %s", exc)
                try:
                    ws.close()
                except Exception:
                    pass
            except Exception as exc:
                logger.warning("WS reconnect after error: %s", exc)
                time.sleep(2)

    def fetch_data(self, config: dict[str, Any]) -> Any:
        cfg = resolve_secrets(dict(config))
        if not (self._thread and self._thread.is_alive()):
            self.start(cfg)
        with self._lock:
            if self._last is not None:
                return self._last
        return cfg.get("fallback_value", "N/A")


PLUGIN = WebSocketPlugin()
