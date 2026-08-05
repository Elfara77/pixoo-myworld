#!/usr/bin/env python3
"""Mac/Linux preview of Pico 64×64 screens → PNG (no hardware needed).

Usage:
  cd pico_monitor
  python3 preview.py              # write previews/*.png for all 6 screens + offline
  python3 preview.py --demo       # same (DEMO metrics)
  open previews/01_sys.png

Requires: Pillow (pip install pillow). Falls back to raw .pbm if missing.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
FW = os.path.join(ROOT, "firmware")
OUT = os.path.join(ROOT, "previews")


class MonoVLSB:
    """Minimal MicroPython-compatible MONO_VLSB framebuffer."""

    def __init__(self, buf: bytearray, w: int, h: int):
        self.buf = buf
        self.width = w
        self.height = h

    def _i(self, x: int, y: int) -> tuple[int, int] | None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return None
        return (x + (y >> 3) * self.width, y & 7)

    def fill(self, c: int) -> None:
        v = 0xFF if c else 0x00
        for i in range(len(self.buf)):
            self.buf[i] = v

    def pixel(self, x: int, y: int, c: int) -> None:
        t = self._i(x, y)
        if not t:
            return
        i, bit = t
        if c:
            self.buf[i] |= 1 << bit
        else:
            self.buf[i] &= ~(1 << bit)

    def fill_rect(self, x: int, y: int, w: int, h: int, c: int) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.pixel(xx, yy, c)

    def rect(self, x: int, y: int, w: int, h: int, c: int) -> None:
        for xx in range(x, x + w):
            self.pixel(xx, y, c)
            self.pixel(xx, y + h - 1, c)
        for yy in range(y, y + h):
            self.pixel(x, yy, c)
            self.pixel(x + w - 1, yy, c)

    def hline(self, x: int, y: int, w: int, c: int) -> None:
        for xx in range(x, x + w):
            self.pixel(xx, y, c)

    def vline(self, x: int, y: int, h: int, c: int) -> None:
        for yy in range(y, y + h):
            self.pixel(x, yy, c)

    def line(self, x0: int, y0: int, x1: int, y1: int, c: int) -> None:
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.pixel(x0, y0, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def blit(self, src, x: int, y: int, key: int = -1) -> None:
        # unused by icons path (pixel loop), kept for API parity
        pass


class FrameBufMod:
    MONO_VLSB = 0

    class FrameBuffer(MonoVLSB):
        def __init__(self, buf, w, h, fmt):
            super().__init__(buf, w, h)


def _install_shims() -> None:
    sys.path.insert(0, FW)
    sys.modules["framebuf"] = FrameBufMod()  # type: ignore
    # micropython const shim for ssd1306 import if ever pulled
    import types

    mp = types.ModuleType("micropython")

    def const(x):
        return x

    mp.const = const  # type: ignore
    sys.modules["micropython"] = mp


def _fb_to_png(fb: MonoVLSB, path: str, scale: int = 8) -> None:
    w, h = fb.width, fb.height
    try:
        from PIL import Image
    except ImportError:
        # Portable bitmap fallback
        pbm = path.rsplit(".", 1)[0] + ".pbm"
        with open(pbm, "wb") as f:
            f.write(f"P4\n{w} {h}\n".encode())
            row_bytes = (w + 7) // 8
            out = bytearray(row_bytes * h)
            for y in range(h):
                for x in range(w):
                    t = fb._i(x, y)
                    assert t
                    i, bit = t
                    if fb.buf[i] & (1 << bit):
                        out[y * row_bytes + (x >> 3)] |= 0x80 >> (x & 7)
            f.write(out)
        print("wrote", pbm, "(install pillow for PNG)")
        return

    img = Image.new("1", (w, h), 0)
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = fb._i(x, y)
            assert t
            i, bit = t
            px[x, y] = 1 if (fb.buf[i] & (1 << bit)) else 0
    img = img.resize((w * scale, h * scale), Image.NEAREST)
    # OLED look: white on black
    img = img.convert("L").point(lambda v: 255 if v else 0)
    img.save(path)
    print("wrote", path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Preview Pico OLED screens → PNG")
    ap.add_argument("--out", default=OUT, help="output directory")
    ap.add_argument("--scale", type=int, default=8)
    args = ap.parse_args()

    _install_shims()
    os.makedirs(args.out, exist_ok=True)

    import config

    config.DEMO = 1

    import display
    import router_client
    import screens

    display.init(None, 64, 64)
    router_client.init()
    mgr = screens.manager()
    mgr.update_data(router_client.fetch_all_metrics())

    # Offline banner sample
    display.draw_offline_banner("ROUTER OFFLINE")
    _fb_to_png(display.fb(), os.path.join(args.out, "00_offline.png"), args.scale)

    names = ("sys", "graph", "top", "tmp", "pie", "srv")
    for i, (fn, name) in enumerate(zip(screens.SCREENS, names), start=1):
        # refresh demo so graphs move a bit
        time.sleep(0.05)
        mgr.update_data(router_client.fetch_all_metrics())
        fn()
        _fb_to_png(
            display.fb(),
            os.path.join(args.out, f"{i:02d}_{name}.png"),
            args.scale,
        )

    print("OK — open", args.out)
    print("NOTE: Merlin /metrics.json ≠ OLED. Flash firmware/ to the Pico W.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
