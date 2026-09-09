"""Merlin metrics → Divoom Pixoo 64 (HTTP RGB push).

Pixoo ≠ Pico. Firmware under firmware/ is for Pico W + SSD1306 only.
"""

from .client import PixooClient
from .render import (
    ALL_SCREEN_IDS,
    KNOWN_SCREEN_IDS,
    OPTIONAL_SCREEN_IDS,
    SCREEN_IDS,
    get_screen_ids,
    render_boot_banner,
    render_screen,
    set_render_options,
    set_screens,
)

__all__ = [
    "PixooClient",
    "ALL_SCREEN_IDS",
    "KNOWN_SCREEN_IDS",
    "OPTIONAL_SCREEN_IDS",
    "SCREEN_IDS",
    "get_screen_ids",
    "render_boot_banner",
    "render_screen",
    "set_render_options",
    "set_screens",
]
