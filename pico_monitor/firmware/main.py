# main.py — uasyncio fetch + 6-screen rotation
#
# Merlin /metrics.json alone does NOT light the OLED — this firmware must
# run on the Pico W (Wi‑Fi + I2C SSD1306).

import config
import display
import router_client
import screens

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio  # CPython preview


def _ensure_runtime():
    """Init display/wifi if boot.py did not run (mpremote exec, CPython)."""
    if display.fb() is None:
        try:
            from boot import init_display, connect_wifi

            init_display()
            connect_wifi()
        except Exception as e:
            print("runtime init:", e)
            display.init(None)
    display.ensure_fb()
    router_client.init()


def _offline_message(mgr):
    err = mgr.error
    if err == "wifi":
        return "WIFI FAIL"
    if err == "offline" or mgr.data.get("_offline"):
        return "ROUTER OFFLINE"
    if err:
        return str(err)[:16]
    return None


async def fetch_task(mgr):
    while True:
        try:
            # Re-check WiFi on device (skip in DEMO / host preview)
            if not getattr(config, "DEMO", 0):
                try:
                    import network

                    wlan = network.WLAN(network.STA_IF)
                    if not wlan.isconnected():
                        mgr.set_error("wifi")
                        await asyncio.sleep(getattr(config, "FETCH_INTERVAL_S", 3))
                        continue
                except ImportError:
                    pass

            data = router_client.fetch_all_metrics()
            if data.get("_offline"):
                mgr.set_error("offline")
                mgr.data = data
            else:
                mgr.update_data(data)
        except Exception as e:
            print("Fetch error:", e)
            mgr.set_error("offline")
        await asyncio.sleep(getattr(config, "FETCH_INTERVAL_S", 3))


async def display_task(mgr):
    idx = 0
    blink = False
    while True:
        try:
            msg = _offline_message(mgr)
            if msg:
                display.set_blink(blink)
                blink = not blink
                display.draw_offline_banner(msg)
            else:
                screens.SCREENS[idx]()
                idx = (idx + 1) % len(screens.SCREENS)
        except Exception as e:
            print("Display error:", e)
            try:
                display.draw_status_banner("UI ERROR")
            except Exception:
                pass
        await asyncio.sleep(getattr(config, "SCREEN_INTERVAL_S", 4))


async def main():
    _ensure_runtime()
    mgr = screens.manager()
    # Paint immediately — never leave a black panel waiting on first fetch.
    try:
        display.draw_boot_test_pattern("WAIT")
    except Exception:
        display.draw_status_banner("WAIT DATA")
    if getattr(config, "DEMO", 0):
        mgr.update_data(router_client.fetch_all_metrics())

    # Avoid asyncio.gather — missing on some MicroPython uasyncio builds.
    try:
        create = asyncio.create_task
    except AttributeError:
        create = None

    screen_every = max(2.0, float(getattr(config, "SCREEN_INTERVAL_S", 5)))

    if create is not None:
        create(fetch_task(mgr))
        await display_task(mgr)
    else:
        # Very old uasyncio: cooperative manual loop
        while True:
            try:
                data = router_client.fetch_all_metrics()
                if data.get("_offline"):
                    mgr.set_error("offline")
                    mgr.data = data
                else:
                    mgr.update_data(data)
            except Exception:
                mgr.set_error("offline")
            msg = _offline_message(mgr)
            if msg:
                display.set_blink(True)
                display.draw_offline_banner(msg)
                await asyncio.sleep(screen_every)
            else:
                for fn in screens.SCREENS:
                    fn()
                    await asyncio.sleep(screen_every)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AttributeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
