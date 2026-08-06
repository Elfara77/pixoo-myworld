"""HTTP client for Divoom Pixoo 64 (API /post) — RGB frame push."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from PIL import Image


class PixooClient:
    """Pushes 64×64 RGB frames via Draw/SendHttpGif."""

    _REFRESH_LIMIT = 32

    # PicSpeed for still updates: low so any queued GIF slot does not linger ~1s.
    _PIC_SPEED_MS = 10

    def __init__(self, ip: str, size: int = 64, *, timeout: float = 3.0) -> None:
        if size not in (16, 32, 64):
            raise ValueError(f"Invalid Pixoo size: {size}")
        self.ip = ip
        self.size = size
        self.timeout = timeout
        self._url = f"http://{ip}/post"
        self._pic_id = 0
        # Drop leftover animation frames from a prior process, then start clean.
        try:
            self._reset_pic_id()
        except Exception:
            self._pic_id = 0

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

    def _reset_pic_id(self) -> None:
        self._post({"Command": "Draw/ResetHttpGifId"})
        self._pic_id = 0

    def set_brightness(self, brightness: int) -> None:
        brightness = max(0, min(100, int(brightness)))
        self._post({"Command": "Channel/SetBrightness", "Brightness": brightness})

    def ping(self) -> bool:
        try:
            self._post({"Command": "Device/GetDeviceTime"})
            return True
        except Exception:
            return False

    def push_image(self, image: Image.Image, *, reset: bool = False) -> None:
        """Push a 64×64 RGB still. ``reset=True`` clears the GIF buffer (layout changes)."""
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

        next_id = self._pic_id + 1
        if reset or next_id >= self._REFRESH_LIMIT:
            self._reset_pic_id()
            next_id = 1
        self._pic_id = next_id

        self._post(
            {
                "Command": "Draw/SendHttpGif",
                "PicNum": 1,
                "PicWidth": self.size,
                "PicOffset": 0,
                "PicID": self._pic_id,
                "PicSpeed": self._PIC_SPEED_MS,
                "PicData": base64.b64encode(buf).decode("ascii"),
            }
        )
