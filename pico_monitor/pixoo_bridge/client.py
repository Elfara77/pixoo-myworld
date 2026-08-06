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

    Live-dashboard pattern (Divoom / community): every still is a *replace*, not
    an animation frame. Always ``ResetHttpGifId`` then ``SendHttpGif`` with
    ``PicID=1``, ``PicNum=1``, ``PicOffset=0``, low ``PicSpeed``.

    Quirks that cause flashes if ignored:
    - Incrementing ``PicID`` queues GIF slots; older layouts briefly play through.
    - High ``PicSpeed`` (e.g. 1000) makes any queued slot linger ~1s.
    - Some firmwares only reliably replace when PicID stays 1 after each reset.
    """

    # Still updates: keep low so a stray queued slot cannot linger visibly.
    _PIC_SPEED_MS = 10

    def __init__(self, ip: str, size: int = 64, *, timeout: float = 3.0) -> None:
        if size not in (16, 32, 64):
            raise ValueError(f"Invalid Pixoo size: {size}")
        self.ip = ip
        self.size = size
        self.timeout = timeout
        self._url = f"http://{ip}/post"
        # Drop leftover animation frames from a prior process, then start clean.
        try:
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
        """Push a 64×64 RGB still as a single-frame GIF replacement.

        Always resets the GIF buffer and sends ``PicID=1`` (community live-
        dashboard pattern). ``reset`` is kept for call-site compatibility; it
        does not skip the reset — partial resets were still flashing on device.

        Cost: 2 HTTP POSTs per frame (~1 Hz) — acceptable on LAN vs ghost frames.
        """
        del reset  # always reset; see docstring
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

        # Clear buffer then PicID=1 — never queue multi-frame animations.
        self._reset_gif_buffer()
        self._post(
            {
                "Command": "Draw/SendHttpGif",
                "PicNum": 1,
                "PicWidth": self.size,
                "PicOffset": 0,
                "PicID": 1,
                "PicSpeed": self._PIC_SPEED_MS,
                "PicData": base64.b64encode(buf).decode("ascii"),
            }
        )
