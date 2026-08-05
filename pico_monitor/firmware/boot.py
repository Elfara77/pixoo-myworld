# boot.py — Wi‑Fi + OLED init (MicroPython on Pico W)
# MicroPython runs boot.py then main.py on soft-reset / power-up.

import config

WIFI_OK = False


def connect_wifi():
    global WIFI_OK
    if getattr(config, "DEMO", 0):
        print("DEMO mode — skip WiFi")
        WIFI_OK = True
        return True
    try:
        import network
        import time

        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            print("WiFi connecting to", config.WIFI_SSID)
            wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
            for _ in range(40):
                if wlan.isconnected():
                    break
                time.sleep(0.25)
        WIFI_OK = bool(wlan.isconnected())
        print("WiFi:", wlan.ifconfig() if WIFI_OK else "FAIL")
        return WIFI_OK
    except Exception as e:
        print("WiFi error", e)
        WIFI_OK = False
        return False


def init_display():
    import display

    try:
        from machine import Pin, I2C

        i2c = I2C(
            config.I2C_ID,
            scl=Pin(config.I2C_SCL),
            sda=Pin(config.I2C_SDA),
            freq=400000,
        )
        addrs = []
        try:
            addrs = i2c.scan()
        except Exception:
            pass
        print("I2C scan:", [hex(a) for a in addrs] if addrs else "(none)")
        if addrs and config.OLED_ADDR not in addrs:
            print("warn: OLED_ADDR", hex(config.OLED_ADDR), "not in scan — trying anyway")
        display.init(i2c, 64, 64, addr=config.OLED_ADDR)
        print("OLED OK")
    except Exception as e:
        print("OLED init failed:", e)
        # Software FB — nothing visible on real glass; main will keep trying banners.
        display.init(None, 64, 64)
    # Always paint something immediately so a hung main.py is not a black panel.
    try:
        display.draw_status_banner("PICO BOOT")
    except Exception as e:
        print("splash error", e)
    return display


# Side-effects on import / boot
try:
    init_display()
    connect_wifi()
    import display

    if getattr(config, "DEMO", 0):
        display.draw_status_banner("DEMO MODE")
    elif WIFI_OK:
        display.draw_status_banner("WIFI OK")
    else:
        display.draw_status_banner("WIFI FAIL")
except Exception as e:
    print("boot error", e)
