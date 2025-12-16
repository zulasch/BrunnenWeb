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
lgpio.gpio_claim_input(chip, BUTTON_GPIO)
lgpio.gpio_set_pull_up_down(chip, BUTTON_GPIO, lgpio.SET_PULL_UP)

# --- OLED ---
I2C_ADDR = 0x3C
serial = i2c(port=1, address=I2C_ADDR)
device = sh1106(serial, width=128, height=64, rotate=0)

# Optional: schmale Default-Font (Pillow)
font = ImageFont.load_default()

CHANNEL_ORDER = ["A0", "A1", "A2", "A3"]
channel_idx = -1

display_on = False
last_press = 0.0
AUTO_OFF_S = 90

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

def draw_screen(ch, row, status_code, status_msg):
    with canvas(device) as draw:
        # Header
        name = (row.get("name") if row else ch) if row else ch
        draw.text((0, 0), f"{ch} {name}"[:21], font=font, fill=255)

        # Values
        if row:
            ma   = row.get("current_mA")
            lvl  = row.get("level_m")
            nn   = row.get("messwert_NN")
            dlt  = row.get("pegel_diff")
            ts   = row.get("timestamp","")

            draw.text((0, 14), f"I: {ma:5.2f} mA" if isinstance(ma,(int,float)) else "I: --", font=font, fill=255)
            draw.text((0, 26), f"T: {lvl:5.2f} m"  if isinstance(lvl,(int,float)) else "T: --", font=font, fill=255)
            draw.text((0, 38), f"NN:{nn:6.2f} m"   if isinstance(nn,(int,float))  else "NN: --", font=font, fill=255)
            draw.text((0, 50), f"d:{dlt:+5.2f} m"  if isinstance(dlt,(int,float)) else "d: --", font=font, fill=255)
        else:
            draw.text((0, 22), "Keine Daten", font=font, fill=255)

        # Status (rechts unten)
        st = status_code
        if status_msg:
            st = f"{status_code}:{status_msg}"
        draw.text((0, 56), st[:21], font=font, fill=255)

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

        # fallende Flanke (1 -> 0)
        if last_state == 1 and state == 0:
            if now - last_edge_time > 0.25:  # debounce
                last_edge_time = now
                last_press = now

                oled_show()
                # Kanal weiterschalten
                channel_idx = (channel_idx + 1) % len(CHANNEL_ORDER)

        last_state = state

        # Wenn Display an: aktualisieren
        if display_on:
            measurements = read_latest_measurements()
            ch = CHANNEL_ORDER[channel_idx]
            row = get_channel_data(measurements, ch)
            st_code, st_msg = compute_status(measurements)
            draw_screen(ch, row, st_code, st_msg)

            # Auto-off
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
