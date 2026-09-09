"""Pixel-friendly font helpers."""

from __future__ import annotations

from functools import lru_cache

from PIL import ImageFont


@lru_cache(maxsize=8)
def get_font(size_token: int = 1) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Return a cached font. size_token: 1=bitmap default, 2/3=TTF if available."""
    if size_token <= 1:
        return ImageFont.load_default()
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, 8 if size_token == 2 else 14)
        except OSError:
            continue
    return ImageFont.load_default()


def preload_fonts() -> None:
    for s in (1, 2, 3):
        get_font(s)
