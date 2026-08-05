"""Merlin metrics → Divoom Pixoo 64 (HTTP RGB push).

Pixoo ≠ Pico. Firmware under firmware/ is for Pico W + SSD1306 only.
"""

from .client import PixooClient
from .render import SCREEN_IDS, render_boot_banner, render_screen, set_render_options

__all__ = [
    "PixooClient",
    "SCREEN_IDS",
    "render_boot_banner",
    "render_screen",
    "set_render_options",
]
