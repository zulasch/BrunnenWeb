#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, time, sqlite3, subprocess
from datetime import datetime, timezone

import lgpio

from luma.core.interface.serial import i2c
from luma.oled.device import sh1106
from luma.core.render import canvas
from PIL import ImageFont

BASE_DIR = "/opt/brunnen_web"
LATEST_JSON = os.path.join(BASE_DIR, "data", "latest_measurement.json")
DB_PATH     = os.path.join(BASE_DIR, "data", "offline_cache.db")

# --- GPIO Button ---
BUTTON_GPIO = 16  # Pin 36
chip = lgpio.gpiochip_open(0)
lgpio.gpio_claim_input(
    chip,
    BUTTON_GPIO,
    lgpio.SET_PULL_UP
)


# --- OLED ---
I2C_ADDR = 0x3C
serial = i2c(port=1, address=I2C_ADDR)
device = sh1106(serial, width=128, height=64, rotate=0)

# Optional: schmale Default-Font (Pillow)
font = ImageFont.load_default()

BASE_CHANNELS = ["A0", "A1", "A2", "A3"]
CHANNEL_ORDER = list(BASE_CHANNELS)
channel_idx = -1

display_on = False
last_press = 0.0
AUTO_OFF_S = 90

CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.json")

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def get_sensor_type(cfg, ch):
    # ch z.B. "A0"
    if ch == "BMP280":
        return "PRESSURE"
    return (cfg.get(f"SENSOR_TYP_{ch}", "ANALOG") or "ANALOG").strip().upper()

def systemctl_is_active(unit: str) -> bool:
    try:
        out = subprocess.check_output(["systemctl", "is-active", unit], text=True).strip()
        return out == "active"
    except Exception:
        return False

def read_latest_measurements():
    """
    Erwartet Liste von Dicts (so wie wasserstand_logger.py schreibt) :contentReference[oaicite:4]{index=4}
    """
    if not os.path.exists(LATEST_JSON):
        return []
    try:
        with open(LATEST_JSON, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def get_channel_data(measurements, ch):
    for row in measurements:
        if row.get("channel") == ch:
            return row
    return None

def parse_ts(ts: str):
    # Logger schreibt ISO (UTC) :contentReference[oaicite:5]{index=5}
    try:
        # Python: "2025-.." +00:00 kompatibel
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def offline_queue_count():
    if not os.path.exists(DB_PATH):
        return 0
    try:
        conn = sqlite3.connect(DB_PATH, timeout=1)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM offline_queue")
        n = int(cur.fetchone()[0])
        conn.close()
        return n
    except Exception:
        return 0

def compute_status(measurements):
    """
    Einfacher “Systemstatus” fürs Display:
    - Logger/Web aktiv?
    - Messwerte frisch?
    - Offline-Queue hat Rückstau?
    """
    logger_ok = systemctl_is_active("brunnen_logger.service")
    web_ok    = systemctl_is_active("brunnen_web.service")

    qn = offline_queue_count()

    fresh_ok = False
    # Prüfe "frisch": irgendein Kanal hat Timestamp < 2 Minuten alt (oder du setzt auf 2*MESSINTERVAL)
    newest = None
    for row in measurements:
        dt = parse_ts(row.get("timestamp",""))
        if dt and (newest is None or dt > newest):
            newest = dt

    if newest:
        age_s = (datetime.now(timezone.utc) - newest).total_seconds()
        fresh_ok = age_s < 120

    if logger_ok and web_ok and fresh_ok and qn == 0:
        return ("OK", None)
    # Priorisierte Fehleranzeige
    if not logger_ok:
        return ("ERR", "Logger down")
    if not web_ok:
        return ("ERR", "Web down")
    if not fresh_ok:
        return ("WARN", "Stale data")
    if qn > 0:
        return ("WARN", f"Queue {qn}")
    return ("WARN", "Check")

def oled_show():
    global display_on
    if not display_on:
        device.show()
        display_on = True

def oled_hide():
    global display_on
    if display_on:
        device.hide()
        display_on = False

SENSOR_LABELS = {
    "LEVEL":  "Wasserlevel",
    "TEMP":   "Temperatur",
    "FLOW":   "Durchfluss",
    "PRESSURE": "Luftdruck",
    "ANALOG": "Analog"
}

def sensor_label(sensor_type):
    return SENSOR_LABELS.get(sensor_type, sensor_type)

def format_value_by_type(sensor_type, row):
    if not row:
        return "Messwert: --"

    st = (sensor_type or "").strip().upper()

    # Basiswert, den dein Logger schon liefert
    v = row.get("level_m")

    if st == "LEVEL":
        return f"Messwert: {v:.2f} m" if isinstance(v, (int, float)) else "Messwert: --"

    if st == "TEMP":
        # aktuell kommt Temperatur (noch) nicht als eigenes Feld -> nutze level_m
        return f"Messwert: {v:.1f} °C" if isinstance(v, (int, float)) else "Messwert: --"

    if st == "FLOW":
        # aktuell kommt Durchfluss (noch) nicht als eigenes Feld -> nutze level_m
        return f"Messwert: {v:.2f} L/min" if isinstance(v, (int, float)) else "Messwert: --"

    if st == "PRESSURE":
        pressure = row.get("value", row.get("level_m"))
        temp = row.get("temperature_C")
        if isinstance(pressure, (int, float)):
            base = f"Druck: {pressure:.1f} hPa"
            if isinstance(temp, (int, float)):
                base += f" {temp:.1f}C"
            return base
        return "Messwert: --"

    if st == "ANALOG":
        ma = row.get("current_mA")
        return f"Messwert: {ma:.2f} mA" if isinstance(ma, (int, float)) else "Messwert: --"

    return "Messwert: --"


def available_channels(cfg, measurements):
    """Stellt Kanäle zusammen, BMP280 nur wenn aktiviert und Messung vorhanden."""
    chans = list(BASE_CHANNELS)
    has_bmp = cfg.get("BMP280_ENABLED") and any(r.get("channel") == "BMP280" for r in measurements)
    if has_bmp:
        chans.append("BMP280")
    return chans



def draw_screen(ch, row, sensor_type):
    with canvas(device) as draw:
        # 1) Kanalnummer
        draw.text((0, 0), f"Kanal: {ch}", font=font, fill=255)

        # 2) Kanalname (kommt bei dir aus latest_measurement.json als "name")
        name = (row.get("name") if row else "") or ""
        draw.text((0, 16), f"Name: {name}"[:21], font=font, fill=255)

        # 3) Sensortyp (Label)
        draw.text((0, 32), f"Typ: {sensor_label(sensor_type)}"[:21], font=font, fill=255)

        # 4) Messwert je nach Sensortyp
        value_text = format_value_by_type(sensor_type, row)
        draw.text((0, 48), value_text[:21], font=font, fill=255)


def button_pressed() -> bool:
    # Active-low
    return lgpio.gpio_read(chip, BUTTON_GPIO) == 0

def main():
    global channel_idx, last_press

    # Start: Display aus
    oled_hide()

    # Entprellung
    last_state = 1
    last_edge_time = 0.0

    while True:
        now = time.time()
        state = lgpio.gpio_read(chip, BUTTON_GPIO)
        cfg = load_config()
        measurements = read_latest_measurements()
        current_channels = available_channels(cfg, measurements)
        if not current_channels:
            current_channels = list(BASE_CHANNELS)
        if channel_idx >= len(current_channels):
            channel_idx = 0

        # fallende Flanke (1 -> 0)
        if last_state == 1 and state == 0:
            if now - last_edge_time > 0.25:  # debounce
                last_edge_time = now
                last_press = now

                oled_show()
                # Kanal weiterschalten
                channel_idx = (channel_idx + 1) % len(current_channels)

        last_state = state

        # Wenn Display an: aktualisieren
        if display_on:
            # Kanal bestimmen
            ch = current_channels[channel_idx]
            row = get_channel_data(measurements, ch)

            # 🔹 Punkt 4: Config laden + Sensortyp ermitteln
            sensor_type = get_sensor_type(cfg, ch)

            # 🔹 Neue Anzeige (4 Zeilen)
            draw_screen(ch, row, sensor_type)

            # Auto-Off
            if now - last_press > AUTO_OFF_S:
                oled_hide()


        time.sleep(0.1)

if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            oled_hide()
        except Exception:
            pass
        lgpio.gpiochip_close(chip)
