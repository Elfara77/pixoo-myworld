"""WebSocket plugin unit tests (no real socket)."""

from pixoo.plugins.websocket import WebSocketPlugin


def test_websocket_validate_and_last_value():
    plug = WebSocketPlugin()
    assert plug.validate_config({"url": "wss://example.com/ws"})
    assert not plug.validate_config({"url": "ftp://bad"})
    plug._last = 123.4
    # prevent thread start
    plug._thread = type("T", (), {"is_alive": lambda self: True})()
    assert plug.fetch_data({"url": "wss://example.com/ws", "fallback_value": "N/A"}) == 123.4
