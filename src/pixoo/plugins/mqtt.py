"""MQTT client plugin — background thread, last-value cache."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from pixoo.plugins.base import DataSourcePlugin
from pixoo.utils.jsonpath_parser import extract_jsonpath, extract_path
from pixoo.utils.secrets import resolve_secrets

logger = logging.getLogger("pixoo.plugins.mqtt")


def _make_mqtt_client():
    import paho.mqtt.client as mqtt

    if hasattr(mqtt, "CallbackAPIVersion"):
        try:
            return mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except Exception:
            pass
    return mqtt.Client()

class MqttPlugin(DataSourcePlugin):
    name = "mqtt"
    description = "MQTT subscriber (IoT / sensors)"
    supports_streaming = True

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last: dict[str, Any] = {}
        self._client = None
        self._config: dict[str, Any] | None = None
        self._started = False

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "broker": {"type": "string", "label": "Broker host", "required": True, "default": "localhost"},
            "port": {"type": "integer", "label": "Port", "default": 1883},
            "topic": {"type": "string", "label": "Topic", "required": True},
            "username": {"type": "string", "label": "Username", "default": ""},
            "password": {"type": "string", "label": "Password", "default": ""},
            "qos": {"type": "integer", "label": "QoS", "default": 1},
            "tls": {"type": "boolean", "label": "TLS", "default": False},
            "payload_type": {
                "type": "string",
                "label": "Payload",
                "enum": ["json", "text"],
                "default": "json",
            },
            "extract_path": {"type": "string", "label": "JSONPath", "default": "$.value"},
            "fallback_value": {"type": "string", "label": "Fallback", "default": "N/A"},
            "cache_ttl": {"type": "integer", "label": "Cache TTL (s)", "default": 30},
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        cfg = resolve_secrets(dict(config))
        return bool(str(cfg.get("broker") or "").strip() and str(cfg.get("topic") or "").strip())

    def start(self, config: dict[str, Any] | None = None) -> None:
        if config:
            self._config = resolve_secrets(dict(config))
        if not self._config or self._started:
            return
        if not str(self._config.get("broker") or "").strip():
            return
        try:
            client = _make_mqtt_client()
        except ImportError:
            logger.error("paho-mqtt not installed")
            return

        cfg = self._config
        user = str(cfg.get("username") or "")
        password = str(cfg.get("password") or "")
        if user:
            client.username_pw_set(user, password)
        if cfg.get("tls"):
            client.tls_set()

        topic = str(cfg["topic"])
        payload_type = str(cfg.get("payload_type") or "json")
        path = extract_path(cfg) or "$.value"

        def on_message(_client: Any, _userdata: Any, msg: Any) -> None:
            try:
                text = msg.payload.decode("utf-8", errors="replace")
                if payload_type == "json":
                    data = json.loads(text)
                    value = extract_jsonpath(data, path, default=data)
                else:
                    value = text
                with self._lock:
                    self._last[topic] = value
                    self._last["__latest__"] = value
            except Exception as exc:
                logger.debug("MQTT parse error: %s", exc)

        def on_connect(client: Any, _userdata: Any, _flags: Any, rc: Any, *_args: Any) -> None:
            code = getattr(rc, "value", rc)
            if code == 0:
                client.subscribe(topic, qos=int(cfg.get("qos") or 1))
                logger.info("MQTT subscribed %s", topic)

        client.on_connect = on_connect
        client.on_message = on_message
        client.connect_async(str(cfg["broker"]), int(cfg.get("port") or 1883), keepalive=60)
        client.loop_start()
        self._client = client
        self._started = True

    def stop(self) -> None:
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._started = False

    def fetch_data(self, config: dict[str, Any]) -> Any:
        cfg = resolve_secrets(dict(config))
        if not self._started:
            self.start(cfg)
        topic = str(cfg.get("topic") or "")
        with self._lock:
            if topic in self._last:
                return self._last[topic]
            if "__latest__" in self._last:
                return self._last["__latest__"]
        return cfg.get("fallback_value", "N/A")


PLUGIN = MqttPlugin()
