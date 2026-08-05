# boot.py — OLED FIRST, then Wi‑Fi (MicroPython on Pico W)
# MicroPython runs boot.py then main.py on soft-reset / power-up.
#
# Order matters: never block on Wi‑Fi before a visible boot pattern.
# This firmware is for Pico W + SSD1306 only — not a Divoom Pixoo.

import config

WIFI_OK = False


def _make_i2c(soft=False):
    """Hardware I2C preferred; SoftI2C fallback if scan is empty / fails."""
    from machine import Pin

    scl = Pin(config.I2C_SCL)
    sda = Pin(config.I2C_SDA)
    if soft:
        from machine import SoftI2C

        return SoftI2C(scl=scl, sda=sda, freq=100000)
    from machine import I2C

    return I2C(
        getattr(config, "I2C_ID", 0),
        scl=scl,
        sda=sda,
        freq=400000,
    )


def _try_oled(i2c):
    import display

    addrs = []
    try:
        addrs = list(i2c.scan())
    except Exception as e:
        print("I2C scan err:", e)
    print("I2C scan:", [hex(a) for a in addrs] if addrs else "(none)")
    addr = getattr(config, "OLED_ADDR", 0x3C)
    if addrs and addr not in addrs:
        # Some modules answer 0x3D
        if 0x3D in addrs:
            addr = 0x3D
            print("using OLED addr 0x3D")
        else:
            print("warn: OLED_ADDR", hex(addr), "not in scan — trying anyway")
    display.init(i2c, 64, 64, addr=addr)
    display.max_contrast()
    return True


def init_display():
    import display

    ok = False
    for soft in (False, True):
        try:
            i2c = _make_i2c(soft=soft)
            print("I2C mode:", "SoftI2C" if soft else "I2C")
            _try_oled(i2c)
            ok = True
            break
        except Exception as e:
            print("OLED init failed (%s):" % ("soft" if soft else "hw"), e)

    if not ok:
        # Software FB — nothing visible on real glass; banners still no-op safely.
        print("OLED unavailable — software FB only")
        display.init(None, 64, 64)

    # ALWAYS paint before Wi‑Fi — checkerboard proves glass works.
    try:
        display.draw_boot_test_pattern("BOOT")
    except Exception as e:
        print("boot pattern error", e)
        try:
            display.draw_status_banner("PICO BOOT")
        except Exception as e2:
            print("splash error", e2)
    return display


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


# Side-effects on import / boot: display → pattern → Wi‑Fi → status
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
