"""Client HTTP headless pour Divoom Pixoo (API /post) — sans tkinter."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from PIL import Image


class PixooClient:
    """Pousse des frames 64×64 via Draw/SendHttpGif."""

    _REFRESH_LIMIT = 32

    def __init__(self, ip: str, size: int = 64, *, timeout: float = 3.0) -> None:
        if size not in (16, 32, 64):
            raise ValueError(f"Taille Pixoo invalide: {size}")
        self.ip = ip
        self.size = size
        self.timeout = timeout
        self._url = f"http://{ip}/post"
        self._pic_id = 1
        self._load_pic_id()

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
            raise ConnectionError(f"Pixoo {self.ip} injoignable: {exc}") from exc
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Réponse Pixoo invalide: {raw[:200]!r}") from exc
        if isinstance(data, dict) and data.get("error_code", 0) not in (0, None):
            raise RuntimeError(f"Erreur Pixoo API: {data}")
        return data if isinstance(data, dict) else {}

    def _load_pic_id(self) -> None:
        try:
            data = self._post({"Command": "Draw/GetHttpGifId"})
            self._pic_id = int(data.get("PicId", 1))
        except Exception:
            self._pic_id = 1

    def _reset_pic_id(self) -> None:
        self._post({"Command": "Draw/ResetHttpGifId"})
        self._pic_id = 0

    def set_brightness(self, brightness: int) -> None:
        brightness = max(0, min(100, int(brightness)))
        self._post({"Command": "Channel/SetBrightness", "Brightness": brightness})

    def push_image(self, image: Image.Image) -> None:
        rgb = image.convert("RGB")
        if rgb.size != (self.size, self.size):
            rgb = rgb.resize((self.size, self.size), Image.Resampling.NEAREST)

        buf = bytearray()
        pixels = rgb.load()
        for y in range(self.size):
            for x in range(self.size):
                r, g, b = pixels[x, y]
                buf.extend((r, g, b))

        self._pic_id += 1
        if self._pic_id >= self._REFRESH_LIMIT:
            self._reset_pic_id()
            self._pic_id = 1

        self._post(
            {
                "Command": "Draw/SendHttpGif",
                "PicNum": 1,
                "PicWidth": self.size,
                "PicOffset": 0,
                "PicID": self._pic_id,
                "PicSpeed": 1000,
                "PicData": base64.b64encode(buf).decode("ascii"),
            }
        )
