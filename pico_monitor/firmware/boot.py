# boot.py — Wi‑Fi + OLED init (MicroPython on Pico W)

import config


def connect_wifi():
    if getattr(config, "DEMO", 0):
        print("DEMO mode — skip WiFi")
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
        print("WiFi:", wlan.ifconfig() if wlan.isconnected() else "FAIL")
        return wlan.isconnected()
    except Exception as e:
        print("WiFi error", e)
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
        display.init(i2c, 64, 64, addr=config.OLED_ADDR)
        print("OLED OK")
    except Exception as e:
        print("OLED fallback FB:", e)
        display.init(None, 64, 64)
    return display


# MicroPython runs boot.py then main.py automatically on some builds;
# keep side-effects light.
try:
    connect_wifi()
    init_display()
except Exception as e:
    print("boot error", e)
