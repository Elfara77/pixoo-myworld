# Pico W monitor — configuration
#
# Hosts:
#   This device's Wi‑Fi LAN IP is typically 192.168.52.4 (see deploy
#   PICO_MERLIN_HOST). That is NOT where metrics are fetched from.
#   ROUTER_HOST below is the Merlin router serving /metrics.json.

# Wi‑Fi (Pico joins LAN to reach Merlin metrics HTTP)
WIFI_SSID = "YOUR_SSID"
WIFI_PASSWORD = "YOUR_PASSWORD"

# Merlin metrics HTTP (deployed by deploy_monitor.sh onto the router)
# Must match PICO_ROUTER_HOST / PICO_METRICS_PORT in .deploy.env
ROUTER_HOST = "192.168.50.1"
ROUTER_PORT = 8088
METRICS_PATH = "/metrics.json"

# Timing (borrowed from working Pixoo cadence: sample ~3s, screen ~4–8s)
FETCH_INTERVAL_S = 3
SCREEN_INTERVAL_S = 5
HISTORY_LEN = 64  # graph points (~2–3 min at 3s fetch)

# Temp alert thresholds (°C)
TEMP_CPU_ALERT = 85
TEMP_WIFI_ALERT = 65

# DEMO=1 → fake metrics, no Wi‑Fi required (host preview / bench)
DEMO = 0

# I2C OLED (SSD1306 64×64)
I2C_ID = 0
I2C_SCL = 5
I2C_SDA = 4
OLED_ADDR = 0x3C
