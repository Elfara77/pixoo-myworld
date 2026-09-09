"""Data binding / tag resolution tests."""

from pixoo.studio.data_binding import resolve_tags


def test_simple_tags():
    assert resolve_tags("CPU {system.cpu}%", {"system.cpu": 42.0}) == "CPU 42%"
    assert resolve_tags("x {missing}", {}) == "x —"


def test_format_and_time():
    assert resolve_tags("{v:.1f}°C", {"v": 12.56}) == "12.6°C"
    out = resolve_tags("{time:%H:%M}", {})
    assert len(out) == 5 and out[2] == ":"


def test_nested_dict():
    data = {"weather": {"temperature": 11.0}, "weather.temperature": 11.0}
    assert resolve_tags("{weather.temperature:.0f}", data) == "11"
