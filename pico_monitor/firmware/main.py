# main.py — uasyncio fetch + 6-screen rotation

import config
import display
import router_client
import screens

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio  # CPython preview


async def fetch_task(mgr):
    while True:
        try:
            data = router_client.fetch_all_metrics()
            if data.get("_offline"):
                mgr.set_error("offline")
            else:
                mgr.update_data(data)
        except Exception as e:
            print("Fetch error:", e)
            mgr.set_error(str(e))
        await asyncio.sleep(getattr(config, "FETCH_INTERVAL_S", 3))


async def display_task(mgr):
    idx = 0
    blink = False
    while True:
        if mgr.error == "offline" or (mgr.data.get("_offline") and not mgr.data.get("cpu")):
            display.set_blink(blink)
            blink = not blink
            display.draw_offline_banner("ROUTER OFFLINE")
        else:
            screens.SCREENS[idx]()
            idx = (idx + 1) % len(screens.SCREENS)
        await asyncio.sleep(getattr(config, "SCREEN_INTERVAL_S", 4))


async def main():
    # Ensure display + client ready (boot.py may have run already)
    if display.fb() is None:
        try:
            from boot import init_display, connect_wifi

            connect_wifi()
            init_display()
        except Exception:
            display.init(None)
    router_client.init()
    mgr = screens.manager()
    # seed demo immediately
    if getattr(config, "DEMO", 0):
        mgr.update_data(router_client.fetch_all_metrics())
    await asyncio.gather(fetch_task(mgr), display_task(mgr))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AttributeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
