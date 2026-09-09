"""MQTT plugin unit tests (no real broker)."""

from pixoo.plugins.mqtt import MqttPlugin


def test_mqtt_validate_and_fallback():
    plug = MqttPlugin()
    cfg = {"broker": "127.0.0.1", "topic": "sensors/temp", "fallback_value": "N/A"}
    assert plug.validate_config(cfg)
    assert not plug.validate_config({"broker": "", "topic": "x"})
    plug._last["sensors/temp"] = 22.5
    plug._started = True
    assert plug.fetch_data(cfg) == 22.5
    assert plug.fetch_data({**cfg, "topic": "missing"}) == "N/A" or plug.fetch_data(
        {**cfg, "topic": "missing", "fallback_value": "N/A"}
    ) == "N/A"
