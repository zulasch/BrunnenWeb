#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import sqlite3
import json
import os
import socket
import logging
import board
import reed_contact
import busio
from datetime import datetime, UTC
from adafruit_ads1x15.ads1115 import ADS1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from adafruit_ads1x15 import ads1x15
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from adafruit_bmp280 import Adafruit_BMP280_I2C
import math

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# ============================================================
# 🔧 GRUNDEINSTELLUNGEN
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.json")
DB_PATH = os.path.join(BASE_DIR, "data", "offline_cache.db")
LOGFILE = os.path.join(BASE_DIR, "logs", "wasserstand.log")

DEFAULT_CONFIG = {
    "DEVICE_ID": socket.gethostname(),
    "LOCATION": "",
    "STARTABSTICH": 0.0,
    "INITIAL_WASSERTIEFE": 0.0,
    "SHUNT_OHMS": 150.0,
    "WERT_4mA": 0.0,
    "WERT_20mA": 3.0,
    "MESSWERT_NN": 500.0,
    "MESSINTERVAL": 5,
    "INFLUX_URL": "",
    "INFLUX_TOKEN": "",
    "INFLUX_ORG": "",
    "INFLUX_BUCKET": "",
    "LOG_LEVEL": "ERROR",
    "BMP280_ENABLED": True,
    "BMP280_ADDRESS": 0x76,
    "NAME_BMP280": "Barometer",
}

# Kanal-spezifische Defaults generieren
#for ch in ["A0", "A1", "A2", "A3"]:

DEFAULT_CONFIG.setdefault("NAME_A0", "Nordbrunnen ABC")
DEFAULT_CONFIG.setdefault("SENSOR_EINHEIT_A0", "m")
DEFAULT_CONFIG.setdefault("SENSOR_TYP_A0", "LEVEL")
DEFAULT_CONFIG.setdefault("WERT_4mA_A0", 0.0)
DEFAULT_CONFIG.setdefault("WERT_20mA_A0", 3.0)
DEFAULT_CONFIG.setdefault("STARTABSTICH_A0", 100.0)
DEFAULT_CONFIG.setdefault("INITIAL_WASSERTIEFE_A0", 25.0)
DEFAULT_CONFIG.setdefault("MESSWERT_NN_A0", 100.0)
DEFAULT_CONFIG.setdefault("SHUNT_OHMS_A0", 150.0)

DEFAULT_CONFIG.setdefault("NAME_A1", "Pumpentemperatur")
DEFAULT_CONFIG.setdefault("SENSOR_EINHEIT_A1", "°C")
DEFAULT_CONFIG.setdefault("SENSOR_TYP_A1", "TEMP")
DEFAULT_CONFIG.setdefault("WERT_4mA_A1", 0.0)
DEFAULT_CONFIG.setdefault("WERT_20mA_A1", 3.0)
DEFAULT_CONFIG.setdefault("SHUNT_OHMS_A1", 150.0)

DEFAULT_CONFIG.setdefault("NAME_A2", "Pumpendurchfluss")
DEFAULT_CONFIG.setdefault("SENSOR_EINHEIT_A2", "m3/h")
DEFAULT_CONFIG.setdefault("SENSOR_TYP_A2", "FLOW")
DEFAULT_CONFIG.setdefault("WERT_4mA_A2", 0.0)
DEFAULT_CONFIG.setdefault("WERT_20mA_A2", 3.0)
DEFAULT_CONFIG.setdefault("SHUNT_OHMS_A2", 150.0)

DEFAULT_CONFIG.setdefault("NAME_A3", "reserve")
DEFAULT_CONFIG.setdefault("SENSOR_EINHEIT_A3", "m")
DEFAULT_CONFIG.setdefault("SENSOR_TYP_A3", "LEVEL")
DEFAULT_CONFIG.setdefault("WERT_4mA_A3", 0.0)
DEFAULT_CONFIG.setdefault("WERT_20mA_A3", 3.0)
DEFAULT_CONFIG.setdefault("STARTABSTICH_A3", 100.0)
DEFAULT_CONFIG.setdefault("INITIAL_WASSERTIEFE_A3", 15.0)
DEFAULT_CONFIG.setdefault("MESSWERT_NN_A3", 0.0)
DEFAULT_CONFIG.setdefault("SHUNT_OHMS_A3", 150.0)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOGFILE), logging.StreamHandler()]
)


def apply_logging_level(level_name: str):
    level = LOG_LEVELS.get(str(level_name).upper(), logging.ERROR)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)
    return level

# ============================================================
# ⚙️ KONFIGURATION LADEN
# ============================================================
def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
        except Exception as e:
            logging.error(f"Konfiguration konnte nicht gelesen werden: {e}")
            cfg = {}

    changed = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = value
            changed = True

    # Typen sicherstellen
    cfg["BMP280_ENABLED"] = str(cfg.get("BMP280_ENABLED", True)).lower() in ("1", "true", "yes", "on")
    try:
        cfg["BMP280_ADDRESS"] = int(str(cfg.get("BMP280_ADDRESS", 0x76)), 0)
    except Exception:
        cfg["BMP280_ADDRESS"] = 0x76

    if changed:
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
            logging.info("🔧 Konfiguration automatisch aktualisiert (neue Defaults ergänzt).")
        except Exception as e:
            logging.error(f"Konfiguration konnte nicht geschrieben werden: {e}")

    return cfg


config = load_config()
apply_logging_level(config.get("LOG_LEVEL", "ERROR"))
last_config_mtime = os.path.getmtime(CONFIG_PATH)

# Geräteidentifikation
DEVICE_ID        = config.get("DEVICE_ID", socket.gethostname())
LOCATION         = config.get("LOCATION", "")

# Initiale Defaults (werden pro Kanal übersteuert)
STARTABSTICH     = config.get("STARTABSTICH", 0.0)
INITIAL_WASSERTIEFE = config.get("INITIAL_WASSERTIEFE", 0.0)
SHUNT_OHMS       = config.get("SHUNT_OHMS", 150.0)
WERT_4mA         = config.get("WERT_4mA", 0.0)
WERT_20mA        = config.get("WERT_20mA", 3.0)
MESSWERT_NN      = config.get("MESSWERT_NN", 500.0)
MESSINTERVAL     = config.get("MESSINTERVAL", 5)
INFLUX_URL       = config.get("INFLUX_URL", "")
INFLUX_TOKEN     = config.get("INFLUX_TOKEN", "")
INFLUX_ORG       = config.get("INFLUX_ORG", "")
INFLUX_BUCKET    = config.get("INFLUX_BUCKET", "")

# ============================================================
# 🔁 KONFIG NEU LADEN BEI ÄNDERUNG
# ============================================================
def reload_config_if_changed():
    global config, last_config_mtime
    global DEVICE_ID, LOCATION
    global STARTABSTICH, INITIAL_WASSERTIEFE, SHUNT_OHMS
    global WERT_4mA, WERT_20mA, MESSWERT_NN, MESSINTERVAL
    global INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET

    try:
        current_mtime = os.path.getmtime(CONFIG_PATH)
        if current_mtime != last_config_mtime:
            logging.info("🔄 Neue Konfiguration erkannt — lade neu...")
            config = load_config()
            DEVICE_ID          = config.get("DEVICE_ID", DEVICE_ID)
            LOCATION           = config.get("LOCATION", LOCATION)
            STARTABSTICH       = config.get("STARTABSTICH", STARTABSTICH)
            INITIAL_WASSERTIEFE= config.get("INITIAL_WASSERTIEFE", INITIAL_WASSERTIEFE)
            SHUNT_OHMS         = config.get("SHUNT_OHMS", SHUNT_OHMS)
            WERT_4mA           = config.get("WERT_4mA", WERT_4mA)
            WERT_20mA          = config.get("WERT_20mA", WERT_20mA)
            MESSWERT_NN        = config.get("MESSWERT_NN", MESSWERT_NN)
            MESSINTERVAL       = config.get("MESSINTERVAL", MESSINTERVAL)
            INFLUX_URL         = config.get("INFLUX_URL", INFLUX_URL)
            INFLUX_TOKEN       = config.get("INFLUX_TOKEN", INFLUX_TOKEN)
            INFLUX_ORG         = config.get("INFLUX_ORG", INFLUX_ORG)
            INFLUX_BUCKET      = config.get("INFLUX_BUCKET", INFLUX_BUCKET)
            last_config_mtime  = current_mtime
            apply_logging_level(config.get("LOG_LEVEL", "ERROR"))
            setup_bmp280(config)
    except Exception as e:
        logging.error(f"Fehler beim Neuladen der Config: {e}")

# ============================================================
# 💾 SQLITE SETUP
# ============================================================
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

# Neu: robuste Offline-Queue
cur.execute("""
CREATE TABLE IF NOT EXISTS offline_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload TEXT NOT NULL
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

bmp280_sensor = None
bmp_fail_count = 0
bmp_last_init = 0.0
bmp_last_warn = 0.0

def parse_i2c_address(value, default=0x76):
    try:
        return int(str(value), 0)
    except Exception:
        return default

def setup_bmp280(cfg):
    """Initialisiere BMP280, falls aktiviert und erreichbar."""
    global bmp280_sensor, bmp_fail_count, bmp_last_init
    if not cfg.get("BMP280_ENABLED", True):
        bmp280_sensor = None
        return
    address = parse_i2c_address(cfg.get("BMP280_ADDRESS", 0x76))
    try:
        bmp280_sensor = Adafruit_BMP280_I2C(i2c, address=address)
        bmp_fail_count = 0
        bmp_last_init = time.time()
    except Exception as e:
        bmp280_sensor = None
        logging.warning(f"BMP280 nicht verfügbar: {e}")

def bmp_plausible(pressure, temp):
    # grobe Grenzen: Druck 300–1100 hPa, Temperatur -40..85°C (Sensor-Range)
    if pressure is None or math.isnan(float(pressure)) or pressure < 300 or pressure > 1100:
        return False
    if temp is not None:
        try:
            if math.isnan(float(temp)) or temp < -40 or temp > 85:
                return False
        except Exception:
            return False
    return True

def read_bmp280(cfg):
    if not bmp280_sensor:
        return None
    try:
        pressure = float(bmp280_sensor.pressure)  # hPa
        temperature = float(bmp280_sensor.temperature)  # °C
        timestamp = datetime.now(UTC).isoformat()
        name = cfg.get("NAME_BMP280", "BMP280")
        if not bmp_plausible(pressure, temperature):
            return None
        return {
            "channel": "BMP280",
            "timestamp": timestamp,
            "current_mA": None,
            "level_m": pressure,
            "wasser_oberflaeche_m": 0.0,
            "messwert_NN": 0.0,
            "pegel_diff": 0.0,
            "name": name,
            "type": "PRESSURE",
            "unit": "hPa",
            "value": pressure,
            "temperature_C": temperature,
        }
    except Exception as e:
        global bmp_fail_count, bmp_last_warn
        bmp_fail_count += 1
        now = time.time()
        if now - bmp_last_warn > 30:
            logging.error(f"Fehler beim Lesen des BMP280: {e}")
            bmp_last_warn = now
        # versuche Neuinitialisierung nach mehreren Fehlversuchen
        if bmp_fail_count >= 3 and (now - bmp_last_init) > 30:
            setup_bmp280(cfg)
        return None

# Initiales BMP280-Setup nach I2C-Initialisierung
setup_bmp280(config)

# ============================================================
# 🔌 REEDKONTAKT-SETUP
# ============================================================
REED_COUNT_FILE = os.path.join(BASE_DIR, "data", "reed_counts.json")
reed_contact.init(REED_COUNT_FILE)

# ============================================================
# 📨 OFFLINE-QUEUE HELFER
# ============================================================
def queue_insert(entry: dict):
    cur.execute("INSERT INTO offline_queue (payload) VALUES (?)", (json.dumps(entry),))
    conn.commit()

def queue_fetch_batch(limit=500):
    rows = cur.execute(
        "SELECT id, payload FROM offline_queue ORDER BY id ASC LIMIT ?",
        (limit,)
    ).fetchall()
    ids, items = [], []
    for rid, payload in rows:
        try:
            items.append(json.loads(payload))
            ids.append(rid)
        except Exception as e:
            logging.warning(f"Korrumpierter Queue-Eintrag id={rid} wird gelöscht: {e}")
            cur.execute("DELETE FROM offline_queue WHERE id=?", (rid,))
    if rows:
        conn.commit()
    return ids, items

def queue_delete_ids(ids):
    if not ids:
        return
    q = "DELETE FROM offline_queue WHERE id IN ({})".format(",".join(["?"]*len(ids)))
    cur.execute(q, ids)
    conn.commit()

# ============================================================
# 📤 INFLUX HELPERS
# ============================================================
def send_to_influx(data_list):
    """
    data_list: Liste aus Dicts mit Feldern:
      channel, timestamp, current_mA, level_m, wasser_oberflaeche_m, messwert_NN, pegel_diff, name
    """
    try:
        cfg = config
        influx_url   = cfg.get("INFLUX_URL")
        influx_token = cfg.get("INFLUX_TOKEN")
        influx_org   = cfg.get("INFLUX_ORG")
        influx_bucket= cfg.get("INFLUX_BUCKET")

        if not all([influx_url, influx_token, influx_org, influx_bucket]):
            logging.warning("⚠️ InfluxDB-Konfiguration unvollständig – überspringe Sendung.")
            return False

        with InfluxDBClient(url=influx_url, token=influx_token, org=influx_org) as client:
            write_api = client.write_api(write_options=SYNCHRONOUS)
            points = []
            for entry in data_list:
                try:
                    sensor_type = str(entry.get("type", "LEVEL")).upper()
                    unit        = entry.get("unit", "")
                    sensor_name = cfg.get(f"NAME_{entry.get('channel','A0')}", entry.get("name", entry.get("channel","A0")))
                    # Fallback: wenn "value" None ist, Level-Messwert verwenden
                    value_raw = entry.get("value")
                    if value_raw is None:
                        value_raw = entry.get("level_m")
                    try:
                        value = float(value_raw)
                    except Exception:
                        logging.warning(f"⚠️ Überspringe Punkt {entry.get('channel')}: kein numerischer Wert ({value_raw})")
                        continue

                    measurement = "barometer" if sensor_type == "PRESSURE" else "wasserstand"

                    device_id = cfg.get("DEVICE_ID", DEVICE_ID)
                    location  = cfg.get("LOCATION",  LOCATION)
                    p = (
                        Point(measurement)
                        .tag("device_id", device_id)
                        .tag("location",  location)
                        .tag("channel",   entry.get("channel","A0"))
                        .tag("name",      sensor_name)
                        .tag("type",      sensor_type)
                        .tag("unit",      unit)
                        .time(entry["timestamp"], WritePrecision.S)
                    )

                    current_ma = entry.get("current_mA")
                    if current_ma is not None:
                        try:
                            p = p.field("Strom_in_mA", float(current_ma))
                        except Exception:
                            logging.warning(f"⚠️ Stromfeld übersprungen (channel {entry.get('channel')}): {current_ma}")

                    if sensor_type == "LEVEL":
                        p = (
                            p
                            .field("Wassertiefe",     float(entry["level_m"]))
                            .field("Startabstich",    float(entry["wasser_oberflaeche_m"]))
                            .field("Messwert_NN",     float(entry["messwert_NN"]))
                            .field("Pegel_Differenz", float(entry["pegel_diff"]))
                        )
                    elif sensor_type == "TEMP":
                        p = p.field("Temperatur", value)
                    elif sensor_type == "FLOW":
                        p = p.field("Durchfluss", value)
                    elif sensor_type == "COUNTER":
                        p = p.field("Liter_gesamt", value)
                        impulse = entry.get("impulse_total")
                        if impulse is not None:
                            p = p.field("Impulse_gesamt", int(impulse))
                    elif sensor_type == "PRESSURE":
                        p = p.field("Luftdruck_hPa", value)
                        temp = entry.get("temperature_C")
                        try:
                            if temp is not None:
                                p = p.field("Temperatur", float(temp))
                        except Exception:
                            logging.warning(f"⚠️ Temperaturfeld für BMP280 übersprungen: {temp}")
                    else:
                        # Fallback für sonstige Sensoren
                        p = p.field("Messwert", value)

                    points.append(p)

                except Exception as e:
                    logging.error(f"❌ Punktfehler ({entry.get('channel')}): {e}")

            if not points:
                return False

            write_api.write(bucket=influx_bucket, org=influx_org, record=points)
            logging.info(f"📤 {len(points)} Messpunkte an InfluxDB gesendet.")
            return True

    except Exception as e:
        logging.error(f"❌ Fehler beim Senden an InfluxDB: {e}")
        return False

def flush_queue_to_influx(max_total=5000, batch_size=500):
    """Älteste Queue-Daten in Batches an Influx senden."""
    remaining = max_total
    all_ok = True
    while remaining > 0:
        ids, batch = queue_fetch_batch(min(batch_size, remaining))
        if not ids:
            break
        ok = send_to_influx(batch)
        if ok:
            queue_delete_ids(ids)
            remaining -= len(ids)
        else:
            all_ok = False
            break
    return all_ok

# ============================================================
# 🧮 HAUPTSCHLEIFE
# ============================================================
logging.info("🌊 Starte Mehrkanal-Messung mit Offline-Puffer...")

try:
    while True:
        reload_config_if_changed()
        cfg = config.copy()
        all_data = []

        for ch_name, chan in channels.items():
            try:
                # Kanal-Parameter aus Config lesen
                sensor_type    = str(cfg.get(f"SENSOR_TYP_{ch_name}", "LEVEL")).upper()
                unit           = str(cfg.get(f"SENSOR_EINHEIT_{ch_name}", "m" if sensor_type == "LEVEL" else "")).strip()

                w4             = float(cfg.get(f"WERT_4mA_{ch_name}", WERT_4mA))
                w20            = float(cfg.get(f"WERT_20mA_{ch_name}", WERT_20mA))
                shunt          = float(cfg.get(f"SHUNT_OHMS_{ch_name}", SHUNT_OHMS))
                startabstich   = float(cfg.get(f"STARTABSTICH_{ch_name}", STARTABSTICH))
                initial_tiefe  = float(cfg.get(f"INITIAL_WASSERTIEFE_{ch_name}", INITIAL_WASSERTIEFE))
                messwert_nn    = float(cfg.get(f"MESSWERT_NN_{ch_name}", MESSWERT_NN))
                sensor_name    = cfg.get(f"NAME_{ch_name}", ch_name)

                # Messung
                voltage     = chan.voltage
                current_mA  = voltage / shunt * 1000.0

                # 4–20 mA begrenzen
                current_mA = max(4.0, min(20.0, current_mA))

                # Generische lineare Skalierung: 4–20 mA -> WERT_4mA..WERT_20mA
                value = w4 + (current_mA - 4) * (w20 - w4) / 16.0

                # Default-Werte initialisieren
                level_m              = None
                wasser_oberflaeche_m = 0.0
                messwert_NN_out      = 0.0
                pegel_diff           = 0.0

                if sensor_type == "LEVEL":
                    # Klassische Wasserstand-Berechnung
                    level_m              = value
                    wasser_oberflaeche_m = startabstich + (initial_tiefe - level_m)
                    messwert_NN_out      = messwert_nn - wasser_oberflaeche_m
                    pegel_diff           = startabstich - wasser_oberflaeche_m
                else:
                    # Temperatur / Durchfluss / andere: nur generischer Messwert
                    level_m = value

                timestamp = datetime.now(UTC).isoformat()

                logging.info(
                    f"🕒 {timestamp} | {ch_name} ({sensor_name}, {sensor_type}) | "
                    f"{current_mA:.2f} mA | Wert {value:.2f} {unit or ''}"
                )

                ch_data = {
                    "channel": ch_name,
                    "timestamp": timestamp,
                    "current_mA": current_mA,
                    # Für Kompatibilität behalten wir die bekannten Felder bei:
                    "level_m": level_m if level_m is not None else 0.0,
                    "wasser_oberflaeche_m": wasser_oberflaeche_m,
                    "messwert_NN": messwert_NN_out,
                    "pegel_diff": pegel_diff,
                    "name": sensor_name,
                    # Neu:
                    "type": sensor_type,
                    "unit": unit,
                    "value": level_m
                }

                # 💾 sofort in Offline-Queue (damit nichts verloren geht)
                queue_insert(ch_data)
                all_data.append(ch_data)

            except Exception as e:
                logging.error(f"❌ Fehler bei Kanal {ch_name}: {e}")

        # BMP280 Barometer einlesen (optional)
        bmp_entry = read_bmp280(config)
        if bmp_entry:
            queue_insert(bmp_entry)
            all_data.append(bmp_entry)

        # Reedkontakt-Zähler einlesen
        try:
            reed_counts = reed_contact.get_counts()
            timestamp = datetime.now(UTC).isoformat()
            for i, gpio in enumerate([25, 27], 1):
                count = reed_counts.get(gpio, 0)
                liter_pro_impuls = float(cfg.get(f"REED_{i}_LITER_PRO_IMPULS", 1.0))
                name = cfg.get(f"REED_{i}_NAME", f"Wasserzähler {i}")
                liter_total = round(count * liter_pro_impuls, 3)
                reed_entry = {
                    "channel": f"REED{i}",
                    "gpio": gpio,
                    "timestamp": timestamp,
                    "name": name,
                    "type": "COUNTER",
                    "unit": "L",
                    "impulse_total": count,
                    "value": liter_total,
                    "current_mA": None,
                    "level_m": 0.0,
                    "wasser_oberflaeche_m": 0.0,
                    "messwert_NN": 0.0,
                    "pegel_diff": 0.0,
                }
                queue_insert(reed_entry)
                all_data.append(reed_entry)
        except Exception as e:
            logging.error(f"❌ Fehler beim Lesen der Reedkontakte: {e}")

        # Für Web-GUI letzte Messungen sichern (atomar: temp-Datei → rename)
        latest_file = os.path.join(BASE_DIR, "data", "latest_measurement.json")
        tmp_file = latest_file + ".tmp"
        try:
            with open(tmp_file, "w") as f:
                json.dump(all_data, f, indent=2)
            os.replace(tmp_file, latest_file)
        except Exception as e:
            logging.warning(f"Konnte latest_measurement.json nicht schreiben: {e}")

        # 🔄 Queue flushen (inkl. der gerade erzeugten Messungen)
        if flush_queue_to_influx(max_total=5000, batch_size=500):
            logging.info("✅ Alle gepufferten Messpunkte erfolgreich an InfluxDB gesendet.")
        else:
            logging.info("📦 Offline: Werte bleiben in der Queue und werden später nachgesendet.")

        time.sleep(float(cfg.get("MESSINTERVAL", MESSINTERVAL)))

except KeyboardInterrupt:
    logging.info("🛑 Messung manuell beendet.")
except Exception as e:
    logging.error(f"❌ Unerwarteter Fehler: {e}")
finally:
    reed_contact.shutdown()
    conn.close()
