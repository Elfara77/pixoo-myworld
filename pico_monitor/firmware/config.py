# Pico W monitor — configuration

# Wi‑Fi (Pico joins LAN to reach Merlin metrics HTTP)
WIFI_SSID = "YOUR_SSID"
WIFI_PASSWORD = "YOUR_PASSWORD"

# Merlin metrics HTTP (deployed by deploy_monitor.sh)
# Prefer LAN IP of router — defaults match asus_merlin deploy habit
ROUTER_HOST = "192.168.50.1"
ROUTER_PORT = 8088
METRICS_PATH = "/metrics.json"

# Timing
FETCH_INTERVAL_S = 3
SCREEN_INTERVAL_S = 4
HISTORY_LEN = 64  # graph points (~2–3 min at 3s fetch)

# Temp alert thresholds (°C)
TEMP_CPU_ALERT = 85
TEMP_WIFI_ALERT = 65

# DEMO=1 → fake metrics, no Wi‑Fi required (host preview / bench)
DEMO = 0

# I2C OLED
I2C_ID = 0
I2C_SCL = 5
I2C_SDA = 4
OLED_ADDR = 0x3C
