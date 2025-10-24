#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import sqlite3
from datetime import datetime
import board
import busio
from adafruit_ads1x15.ads1115 import ADS1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_ads1x15 import ads1x15
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import json
import os
import logging

# ============================================================
# 🔧 GRUNDEINSTELLUNGEN
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.json")
DB_PATH = os.path.join(BASE_DIR, "data", "offline_cache.db")
LOGFILE = os.path.join(BASE_DIR, "logs", "wasserstand.log")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOGFILE),
        logging.StreamHandler()
    ]
)

# ============================================================
# ⚙️ KONFIGURATION LADEN
# ============================================================
def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

config = load_config()
last_config_mtime = os.path.getmtime(CONFIG_PATH)

# Initiale Variablen
STARTABSTICH = config.get("STARTABSTICH", 0.0)
INITIAL_WASSERTIEFE = config.get("INITIAL_WASSERTIEFE", 0.0)
SHUNT_OHMS = config.get("SHUNT_OHMS", 150.0)
WERT_4mA = config.get("WERT_4mA", 0.0)
WERT_20mA = config.get("WERT_20mA", 3.0)
MESSWERT_NN = config.get("MESSWERT_NN", 500.0)
MESSINTERVAL = config.get("MESSINTERVAL", 5)
INFLUX_URL = config.get("INFLUX_URL", "")
INFLUX_TOKEN = config.get("INFLUX_TOKEN", "")
INFLUX_ORG = config.get("INFLUX_ORG", "")
INFLUX_BUCKET = config.get("INFLUX_BUCKET", "")

# ============================================================
# 🔁 KONFIG NEU LADEN BEI ÄNDERUNG
# ============================================================
def reload_config_if_changed():
    global config, last_config_mtime
    global STARTABSTICH, INITIAL_WASSERTIEFE, SHUNT_OHMS
    global WERT_4mA, WERT_20mA, MESSWERT_NN, MESSINTERVAL
    global INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET

    try:
        current_mtime = os.path.getmtime(CONFIG_PATH)
        if current_mtime != last_config_mtime:
            logging.info("🔄 Neue Konfiguration erkannt — lade neu...")
            config = load_config()
            STARTABSTICH = config.get("STARTABSTICH", STARTABSTICH)
            INITIAL_WASSERTIEFE = config.get("INITIAL_WASSERTIEFE", INITIAL_WASSERTIEFE)
            SHUNT_OHMS = config.get("SHUNT_OHMS", SHUNT_OHMS)
            WERT_4mA = config.get("WERT_4mA", WERT_4mA)
            WERT_20mA = config.get("WERT_20mA", WERT_20mA)
            MESSWERT_NN = config.get("MESSWERT_NN", MESSWERT_NN)
            MESSINTERVAL = config.get("MESSINTERVAL", MESSINTERVAL)
            INFLUX_URL = config.get("INFLUX_URL", INFLUX_URL)
            INFLUX_TOKEN = config.get("INFLUX_TOKEN", INFLUX_TOKEN)
            INFLUX_ORG = config.get("INFLUX_ORG", INFLUX_ORG)
            INFLUX_BUCKET = config.get("INFLUX_BUCKET", INFLUX_BUCKET)
            last_config_mtime = current_mtime
    except Exception as e:
        logging.error(f"Fehler beim Neuladen der Config: {e}")

# ============================================================
# 💾 SQLITE SETUP
# ============================================================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS measurements (
    timestamp TEXT,
    current_mA REAL,
    level_m REAL,
    wasser_oberflaeche_m REAL,
    messwert_NN REAL,
    pegel_diff REAL
)
""")
conn.commit()

# ============================================================
# 🧠 SENSOR SETUP (mehrere Kanäle)
# ============================================================
i2c = busio.I2C(board.SCL, board.SDA)
ads = ADS(i2c)
ads.gain = 1

channels = {
    "A0": AnalogIn(ads, ads1x15.Pin.A0),
    "A1": AnalogIn(ads, ads1x15.Pin.A1),
    "A2": AnalogIn(ads, ads1x15.Pin.A2),
    "A3": AnalogIn(ads, ads1x15.Pin.A3),
}

# ============================================================
# 🔍 HELFERFUNKTIONEN
# ============================================================
def read_current_mA():
    return chan.voltage / SHUNT_OHMS * 1000.0

def current_to_level(current_mA):
    """4–20 mA → physikalische Messgröße"""
    if current_mA < 4: current_mA = 4
    if current_mA > 20: current_mA = 20
    return WERT_4mA + (current_mA - 4) * (WERT_20mA - WERT_4mA) / 16

def check_influx_reachable():
    try:
        with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
            return client.ping()
    except Exception:
        return False

def save_local(data):
    cur.execute("INSERT INTO measurements VALUES (?, ?, ?, ?, ?, ?)", data)
    conn.commit()

def read_current_mA():
    voltage = chan.voltage
    current_mA = voltage / SHUNT_OHMS * 1000.0
    return voltage, current_mA

def send_to_influx(data_list):
    if not all([INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET]):
        logging.warning("⚠️ InfluxDB nicht konfiguriert — speichere lokal.")
        return False
    if not check_influx_reachable():
        logging.warning("⚠️ InfluxDB nicht erreichbar — speichere lokal.")
        return False

    client = None
    write_api = None
    try:
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=5000)
        write_api = client.write_api(write_options=SYNCHRONOUS)

        for d in data_list:
            p = (
                Point("wasserstand")
                .time(d["timestamp"], WritePrecision.S)
                .field("Strom_in_mA", d["current_mA"])
                .field("Wassertiefe", d["level_m"])
                .field("Startabstich", d["wasser_oberflaeche_m"])
                .field("Messwert_NN", d["messwert_NN"])
                .field("Pegel_Differenz", d["pegel_diff"])
            )
            write_api.write(bucket=INFLUX_BUCKET, record=p)
        return True

    except Exception as e:
        logging.error(f"Fehler beim Schreiben in InfluxDB: {e}")
        return False

    finally:
        try:
            if isinstance(write_api, WriteApi):
                write_api.__del__()
        except Exception:
            pass
        if client:
            client.__del__()

# ============================================================
# 🧮 HAUPTSCHLEIFE (mehrkanalig)
# ============================================================
logging.info("🌊 Starte Mehrkanal-Messung...")

try:
    while True:
        reload_config_if_changed()
        all_data = []

        for ch_name, chan in channels.items():
            try:
                voltage = chan.voltage
                current_mA = voltage / SHUNT_OHMS * 1000.0
                level_m = current_to_level(current_mA)
                wasser_oberflaeche_m = STARTABSTICH + (INITIAL_WASSERTIEFE - level_m)
                messwert_NN = MESSWERT_NN - wasser_oberflaeche_m
                pegel_diff = STARTABSTICH - wasser_oberflaeche_m
                from datetime import datetime, UTC
                timestamp = datetime.now(UTC).isoformat()

                logging.info(
                    f"🕒 {timestamp} | Kanal {ch_name} | {current_mA:.2f} mA | "
                    f"Wassertiefe: {level_m:.2f} m | "
                    f"Wasseroberfläche: {wasser_oberflaeche_m:.2f} m u. Gelände | "
                    f"Messwert NN: {messwert_NN:.2f} m ü. NN | Δ={pegel_diff:+.2f} m"
                )

                data = (timestamp, current_mA, level_m, wasser_oberflaeche_m, messwert_NN, pegel_diff)
                save_local(data)

                all_data.append({
                    "channel": ch_name,
                    "timestamp": timestamp,
                    "current_mA": current_mA,
                    "level_m": level_m,
                    "wasser_oberflaeche_m": wasser_oberflaeche_m,
                    "messwert_NN": messwert_NN,
                    "pegel_diff": pegel_diff
                })
            except Exception as e:
                logging.error(f"❌ Fehler bei Kanal {ch_name}: {e}")

        # Speichere letzte Messungen (für Webapp)
        latest_file = os.path.join(BASE_DIR, "data", "latest_measurement.json")
        try:
            with open(latest_file, "w") as f:
                json.dump(all_data, f, indent=2)
        except Exception as e:
            logging.warning(f"Konnte latest_measurement.json nicht schreiben: {e}")

        # Sende an Influx (alle Kanäle)
        cached = cur.execute("SELECT * FROM measurements").fetchall()
        points = []

        for ch_data in all_data:
            try:
                p = (
                    Point("wasserstand")
                    .tag("channel", ch_data.get("channel", "A0"))
                    .time(ch_data["timestamp"], WritePrecision.S)
                    .field("Strom_in_mA", ch_data["current_mA"])
                    .field("Wassertiefe", ch_data["level_m"])
                    .field("Startabstich", ch_data["wasser_oberflaeche_m"])
                    .field("Messwert_NN", ch_data["messwert_NN"])
                    .field("Pegel_Differenz", ch_data["pegel_diff"])
                )
                points.append(p)
            except Exception as e:
                logging.error(f"Fehler beim Erstellen des Influx-Punkts ({ch_data.get('channel')}): {e}")

        if send_to_influx(all_data):
            cur.execute("DELETE FROM measurements")
            conn.commit()
            logging.info("✅ Daten aller Kanäle an InfluxDB gesendet.")
        else:
            logging.info("📦 Werte lokal zwischengespeichert.")

        time.sleep(MESSINTERVAL)

except KeyboardInterrupt:
    logging.info("🛑 Messung manuell beendet.")
    conn.close()
except Exception as e:
    logging.error(f"❌ Unerwarteter Fehler: {e}")
    conn.close()
