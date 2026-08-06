"""HTTP client for Divoom Pixoo 64 (API /post) — RGB frame push."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from PIL import Image


class PixooClient:
    """Pushes 64×64 RGB frames via Draw/SendHttpGif.

    Firmware quirk (community-confirmed): ``SendHttpGif`` without a prior
    ``ResetHttpGifId`` returns ``error_code: 0`` but **does not update pixels**.
    After a few overwrites the panel looks frozen while the bridge keeps
    "succeeding". Always reset, then send a single still (``PicID=1``,
    ``PicNum=1``).

    Also force Custom channel (``Channel/SetIndex`` SelectIndex=3) so the
    device is actually showing HTTP GIF content.
    """

    _PIC_SPEED_MS = 1000
    _PIC_ID = 1
    # Custom / DIY channel — required for SendHttpGif to be visible.
    _CHANNEL_CUSTOM = 3

    def __init__(self, ip: str, size: int = 64, *, timeout: float = 3.0) -> None:
        if size not in (16, 32, 64):
            raise ValueError(f"Invalid Pixoo size: {size}")
        self.ip = ip
        self.size = size
        self.timeout = timeout
        self._url = f"http://{ip}/post"
        try:
            self._set_custom_channel()
            self._reset_gif_buffer()
        except Exception:
            pass

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Pixoo {self.ip} unreachable: {exc}") from exc
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid Pixoo response: {raw[:200]!r}") from exc
        if isinstance(data, dict) and data.get("error_code", 0) not in (0, None):
            raise RuntimeError(f"Pixoo API error: {data}")
        return data if isinstance(data, dict) else {}

    def _reset_gif_buffer(self) -> None:
        self._post({"Command": "Draw/ResetHttpGifId"})

    def _set_custom_channel(self) -> None:
        self._post(
            {"Command": "Channel/SetIndex", "SelectIndex": self._CHANNEL_CUSTOM}
        )

    def set_brightness(self, brightness: int) -> None:
        brightness = max(0, min(100, int(brightness)))
        self._post({"Command": "Channel/SetBrightness", "Brightness": brightness})

    def ping(self) -> bool:
        try:
            self._post({"Command": "Device/GetDeviceTime"})
            return True
        except Exception:
            return False

    def push_image(self, image: Image.Image, *, reset: bool = True) -> None:
        """Push a 64×64 RGB still.

        Always ``ResetHttpGifId`` then ``SendHttpGif`` PicID=1 — required for
        the panel to actually refresh. ``reset`` kept for call-site compat.
        """
        del reset  # always reset; see class docstring
        rgb = image.convert("RGB")
        if rgb.size != (self.size, self.size):
            try:
                resample = Image.Resampling.NEAREST
            except AttributeError:  # Pillow < 9
                resample = Image.NEAREST  # type: ignore[attr-defined]
            rgb = rgb.resize((self.size, self.size), resample)

        buf = bytearray()
        pixels = rgb.load()
        for y in range(self.size):
            for x in range(self.size):
                r, g, b = pixels[x, y]
                buf.extend((r, g, b))

        # Reset is mandatory: without it the device ACKs and paints nothing.
        self._reset_gif_buffer()
        self._post(
            {
                "Command": "Draw/SendHttpGif",
                "PicNum": 1,
                "PicWidth": self.size,
                "PicOffset": 0,
                "PicID": self._PIC_ID,
                "PicSpeed": self._PIC_SPEED_MS,
                "PicData": base64.b64encode(buf).decode("ascii"),
            }
        )
