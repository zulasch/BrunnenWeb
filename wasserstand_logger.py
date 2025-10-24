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

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

def send_to_influx(data_list):
    """Sendet mehrere Kanal-Messungen an InfluxDB"""
    try:
        cfg = load_config()
        influx_url = cfg.get("INFLUX_URL")
        influx_token = cfg.get("INFLUX_TOKEN")
        influx_org = cfg.get("INFLUX_ORG")
        influx_bucket = cfg.get("INFLUX_BUCKET")

        if not all([influx_url, influx_token, influx_org, influx_bucket]):
            logging.warning("⚠️ InfluxDB-Konfiguration unvollständig, Daten werden nicht gesendet.")
            return False

        with InfluxDBClient(url=influx_url, token=influx_token, org=influx_org) as client:
            write_api = client.write_api(write_options=SYNCHRONOUS)
            points = []

            for entry in data_list:
                try:
                    sensor_name = cfg.get(f"NAME_{entry.get('channel', 'A0')}", entry.get("channel", "A0"))
                    p = (
                        Point("wasserstand")
                        .tag("channel", entry.get("channel", "A0"))
                        .tag("name", sensor_name)
                        .time(entry["timestamp"], WritePrecision.S)
                        .field("Strom_in_mA", float(entry["current_mA"]))
                        .field("Wassertiefe", float(entry["level_m"]))
                        .field("Startabstich", float(entry["wasser_oberflaeche_m"]))
                        .field("Messwert_NN", float(entry["messwert_NN"]))
                        .field("Pegel_Differenz", float(entry["pegel_diff"]))
                    )
                    points.append(p)
                except Exception as e:
                    logging.error(f"❌ Fehler bei Punkt-Erstellung für {entry.get('channel')}: {e}")

            if not points:
                logging.warning("Keine gültigen Datenpunkte zum Senden.")
                return False

            write_api.write(bucket=influx_bucket, org=influx_org, record=points)
            logging.info(f"📤 {len(points)} Messpunkte erfolgreich an InfluxDB gesendet.")
            return True

    except Exception as e:
        logging.error(f"❌ Fehler beim Senden an InfluxDB: {e}")
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
        cfg = load_config()
        all_data = []

        for ch_name, chan in channels.items():
            try:
                # Kanalbezogene Parameter aus Config lesen
                cfg = load_config()
                w4 = float(cfg.get(f"WERT_4mA_{ch_name}", WERT_4mA))
                w20 = float(cfg.get(f"WERT_20mA_{ch_name}", WERT_20mA))
                shunt = float(cfg.get(f"SHUNT_OHMS_{ch_name}", SHUNT_OHMS))
                startabstich = float(cfg.get(f"STARTABSTICH_{ch_name}", STARTABSTICH))
                initial_tiefe = float(cfg.get(f"INITIAL_WASSERTIEFE_{ch_name}", INITIAL_WASSERTIEFE))
                messwert_nn = float(cfg.get(f"MESSWERT_NN_{ch_name}", MESSWERT_NN))
                sensor_name = cfg.get(f"NAME_{ch_name}", ch_name)

                # Messung
                voltage = chan.voltage
                current_mA = voltage / shunt * 1000.0
                # lineare Umrechnung 4–20mA
                if current_mA < 4: current_mA = 4
                if current_mA > 20: current_mA = 20
                level_m = w4 + (current_mA - 4) * (w20 - w4) / 16
                wasser_oberflaeche_m = startabstich + (initial_tiefe - level_m)
                messwert_NN = messwert_nn - wasser_oberflaeche_m
                pegel_diff = startabstich - wasser_oberflaeche_m
                from datetime import datetime, UTC
                timestamp = datetime.now(UTC).isoformat()

                logging.info(
                    f"🕒 {timestamp} | Kanal {ch_name} ({sensor_name}) | "
                    f"{current_mA:.2f} mA | Tiefe: {level_m:.2f} m | Δ={pegel_diff:+.2f} m"
                )

                # Daten speichern
                data = (timestamp, current_mA, level_m, wasser_oberflaeche_m, messwert_NN, pegel_diff)
                save_local(data)

                all_data.append({
                    "channel": ch_name,
                    "timestamp": timestamp,
                    "current_mA": current_mA,
                    "level_m": level_m,
                    "wasser_oberflaeche_m": wasser_oberflaeche_m,
                    "messwert_NN": messwert_NN,
                    "pegel_diff": pegel_diff,
                    "name": sensor_name
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
                sensor_name = config.get(f"NAME_{ch_data.get('channel', 'A0')}", ch_data.get("channel", "A0"))
                p = (
                    Point("wasserstand")
                    .tag("channel", ch_data.get("channel", "A0"))
                    .tag("name", sensor_name)
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
