#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, socket, subprocess, functools, time
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort, flash
import mosfet_control
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
SCHEDULE_FILE = os.path.join(BASE_DIR, "config", "output_schedule.json")
NAMES_FILE = os.path.join(BASE_DIR, "config", "output_names.json")

# 🔧 Standard-Konfiguration – wird mit lokaler config.json gemerged
DEFAULT_CONFIG = {
    "MESSINTERVAL": 5,
    "ADMIN_PIN": 1234,
    "INFLUX_URL": "",
    "INFLUX_TOKEN": "",
    "INFLUX_ORG": "",
    "INFLUX_BUCKET": "",
}

# Kanal-spezifische Defaults generieren
#for ch in ["A0", "A1", "A2", "A3"]:

DEFAULT_CONFIG.setdefault(f"NAME_A0", "Nordbrunnen ABC")
DEFAULT_CONFIG.setdefault(f"SENSOR_EINHEIT_A0", "m")
DEFAULT_CONFIG.setdefault(f"SENSOR_TYP_A0", "LEVEL")
DEFAULT_CONFIG.setdefault(f"WERT_4mA_A0", 0.0,)
DEFAULT_CONFIG.setdefault(f"WERT_20mA_A0", 3.0)
DEFAULT_CONFIG.setdefault(f"STARTABSTICH_A0", 100.0)
DEFAULT_CONFIG.setdefault(f"INITIAL_WASSERTIEFE_A0", 25.0)
DEFAULT_CONFIG.setdefault(f"MESSWERT_NN_A0", 100.0)
DEFAULT_CONFIG.setdefault(f"SHUNT_OHMS_A0", 150.0)
DEFAULT_CONFIG.setdefault(f"TEST123_A0", 100.0,)

DEFAULT_CONFIG.setdefault(f"NAME_A1", "Pumpentemperatur")
DEFAULT_CONFIG.setdefault(f"SENSOR_EINHEIT_A1", "°C")
DEFAULT_CONFIG.setdefault(f"SENSOR_TYP_A1", "TEMP")
DEFAULT_CONFIG.setdefault(f"WERT_4mA_A1", 0.0)
DEFAULT_CONFIG.setdefault(f"WERT_20mA_A1", 3.0)
DEFAULT_CONFIG.setdefault(f"SHUNT_OHMS_A1", 150.0)

DEFAULT_CONFIG.setdefault(f"NAME_A2", "Pumpendurchfluss")
DEFAULT_CONFIG.setdefault(f"SENSOR_EINHEIT_A2", "m3/h")
DEFAULT_CONFIG.setdefault(f"SENSOR_TYP_A2", "FLOW")
DEFAULT_CONFIG.setdefault(f"WERT_4mA_A2", 0.0)
DEFAULT_CONFIG.setdefault(f"WERT_20mA_A2", 3.0)
DEFAULT_CONFIG.setdefault(f"SHUNT_OHMS_A2", 150.0)

DEFAULT_CONFIG.setdefault(f"NAME_A3", "reserve")
DEFAULT_CONFIG.setdefault(f"SENSOR_EINHEIT_A3", "m")
DEFAULT_CONFIG.setdefault(f"SENSOR_TYP_A3", "LEVEL")
DEFAULT_CONFIG.setdefault(f"WERT_4mA_A3", 0.0)
DEFAULT_CONFIG.setdefault(f"WERT_20mA_A3", 3.0)
DEFAULT_CONFIG.setdefault(f"STARTABSTICH_A3", 100.0)
DEFAULT_CONFIG.setdefault(f"INITIAL_WASSERTIEFE_A3", 15.0)
DEFAULT_CONFIG.setdefault(f"MESSWERT_NN_A3", 00.0)
DEFAULT_CONFIG.setdefault(f"SHUNT_OHMS_A3", 150.0)


# ===== Flask =====
app = Flask(__name__, template_folder="templates")
# Geheimschlüssel (für Sessions). In Produktion in ENV legen!
app.config["SECRET_KEY"] = os.environ.get("WEBAPP_SECRET", "change-me-please")

# ===== Helpers =====
def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE) as f:
            return json.load(f)
    return []


def save_schedule(data):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_names():
    if os.path.exists(NAMES_FILE):
        with open(NAMES_FILE) as f:
            return json.load(f)
    return {str(i): f"Kanal {i+1}" for i in range(8)}


def save_names(data):
    with open(NAMES_FILE, "w") as f:
        json.dump(data, f, indent=2)
        

def load_config():
    # Leere Basis
    cfg = {}

    # 1️⃣ Lokale config.json einlesen (wenn vorhanden)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
        except Exception as e:
            # Notfall: kaputte Datei -> mit leerem Dict weitermachen
            print(f"Warnung: Konnte config.json nicht lesen: {e}")

    # 2️⃣ Defaults ergänzen
    changed = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = value
            changed = True

    # 3️⃣ (Optional) Ungültige Keys aufräumen:
    allowed_keys = set(DEFAULT_CONFIG.keys()) | {k for k in cfg.keys() if k.startswith("NAME_")}
    for key in list(cfg.keys()):
        if key not in allowed_keys:
            cfg.pop(key)
            changed = True

    # 4️⃣ Wenn sich was geändert hat -> wieder speichern
    if changed:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)

    return cfg


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)

def get_ip():
    try:
        return subprocess.check_output(["hostname", "-I"]).decode().split()[0]
    except Exception:
        return "Unbekannt"

def i2c_status() -> bool:
    # 0 = enabled, 1 = disabled (raspi-config nonint)
    try:
        out = subprocess.check_output(["raspi-config", "nonint", "get_i2c"]).decode().strip()
        return out == "0"
    except Exception:
        return False

def service_status(name="brunnen.service"):
    try:
        out = subprocess.check_output(["systemctl", "is-active", name]).decode().strip()
        return out  # active, inactive, failed, activating...
    except subprocess.CalledProcessError:
        return "unknown"

def tail_file(path, lines=200):
    try:
        return subprocess.check_output(["tail", "-n", str(lines), path]).decode(errors="ignore")
    except Exception as e:
        return f"(Kein Zugriff auf {path} – {e})"

# ===== Auth (PIN) =====
def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("auth_ok"):
            return view(*args, **kwargs)
        return redirect(url_for("login", next=request.path))
    return wrapped

@app.route("/login", methods=["GET","POST"])
def login():
    cfg = load_config()
    required_pin = str(cfg.get("ADMIN_PIN", "1234"))
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin == required_pin:
            session["auth_ok"] = True
            nxt = request.args.get("next") or url_for("index")
            return redirect(nxt)
        flash("Falsche PIN.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ===== Pages =====
@app.route("/")
@login_required
def index():
    cfg = load_config()

    # Basisbeschreibungen – ohne Kanalendung
    base_descriptions = {
        "NAME": "Bezeichnung oder Standort dieses Sensors.",
        "SENSOR_TYP": "Art des Sensors (z. B. LEVEL, TEMP, FLOW).",
        "SENSOR_EINHEIT": "Einheit des Messwerts (z. B. m, °C, m3/h).",
        "STARTABSTICH": "Abstand Gelände → Wasseroberfläche beim Start [m].",
        "INITIAL_WASSERTIEFE": "Initiale Wassertiefe [m] (z. B. 2.5).",
        "SHUNT_OHMS": "Shunt-Widerstand [Ω] (typ. 150 Ω).",
        "WERT_4mA": "Messwert bei 4 mA (untere Grenze).",
        "WERT_20mA": "Messwert bei 20 mA (obere Grenze).",
        "MESSWERT_NN": "Geländehöhe über NN [m].",
        "MESSINTERVAL": "Messintervall [s].",
        "ADMIN_PIN": "PIN für Web-Login (4–8 Ziffern)."
    }


    # Automatische Erweiterung: Für alle Kanalvarianten
    descriptions = {}
    for key in cfg.keys():
        # Suche, ob der Key auf einem bekannten Basisschlüssel basiert
        for base_key, desc in base_descriptions.items():
            if key.startswith(base_key):
                descriptions[key] = desc
                break
        else:
            # kein Treffer → leere Beschreibung
            descriptions[key] = ""

    return render_template("index.html", config=cfg, descriptions=descriptions, title="Messsystem")

from pathlib import Path

@app.route("/update", methods=["POST"])
@login_required
def update_config():
    try:
        data = request.form.to_dict()
        cfg = load_config()

        # Felder, die immer als Text behandelt werden sollen
        string_keys = ["ADMIN_PIN", "WEB_USER", "WEB_PASS"]

        for key, value in data.items():
            if key in cfg:
                if key in string_keys:
                    cfg[key] = value.strip()
                else:
                    try:
                        cfg[key] = float(value)
                    except ValueError:
                        cfg[key] = value

        save_config(cfg)

        # 🔔 Signal an Logger: neue Konfiguration liegt vor
        BASE_DATA_DIR = os.path.join(BASE_DIR, "data")
        FLAG_FILE = os.path.join(BASE_DATA_DIR, "config_update.flag")
        LAST_UPDATE_FILE = os.path.join(BASE_DATA_DIR, "last_config_update")

        Path(BASE_DATA_DIR).mkdir(exist_ok=True)
        Path(FLAG_FILE).touch()

        # 🔍 Prüfen, ob Logger wirklich reagiert hat
        if Path(LAST_UPDATE_FILE).exists():
                    return jsonify({"success": True, "message": "✅ Änderungen gespeichert und aktiv im Messsystem."})
        else:
            return jsonify({"success": True, "message": "💾 Gespeichert"})

    except Exception as e:
        app.logger.exception("Fehler beim Speichern der Konfiguration:")
        return jsonify({"success": False, "message": f"❌ Fehler: {e}"}), 500


@app.route("/outputs")
@login_required
def outputs_page():
    return render_template("outputs.html", title="MOSFET-Steuerung")

@app.route("/outputs/names", methods=["GET", "POST"])
@login_required
def outputs_names():
    if request.method == "POST":
        data = request.form.to_dict()
        save_names(data)
        return jsonify({"success": True, "message": "✅ Namen gespeichert"})
    return jsonify(load_names())

@app.route("/outputs/set/<int:channel>/<int:state>", methods=["POST"])
@login_required
def set_output(channel, state):
    mosfet_control.set_output(channel, bool(state))
    return jsonify({"success": True, "message": f"Kanal {channel+1} {'AN' if state else 'AUS'}"})

@app.route("/outputs/state")
@login_required
def outputs_state():
    state_dict = mosfet_control.get_state() or {}
    # Sicherstellen, dass wir etwas zurückgeben
    if not state_dict:
        state_dict = {i: False for i in range(8)}
    ordered = [state_dict.get(i, False) for i in sorted(state_dict.keys())]
    return jsonify(ordered)

    
@app.route("/outputs/schedule", methods=["GET", "POST", "DELETE"])
@login_required
def outputs_schedule():
    """GET = Liste aller Zeitpläne, POST = neuen hinzufügen, DELETE = löschen"""
    if request.method == "GET":
        return jsonify(load_schedule())

    if request.method == "POST":
        job = {
            "channel": int(request.form["channel"]),
            "time": request.form["time"],
            "state": int(request.form["state"]),
        }
        data = load_schedule()
        data.append(job)
        save_schedule(data)
        return jsonify({"success": True, "message": "✅ Zeitplan gespeichert"})

    if request.method == "DELETE":
        ch = request.args.get("channel")
        t = request.args.get("time")
        data = [j for j in load_schedule() if not (str(j["channel"]) == ch and j["time"] == t)]
        save_schedule(data)
        return jsonify({"success": True, "message": "🗑️ Zeitplan gelöscht"})


@app.route("/service")
@login_required
def service_page():
    st = service_status("brunnen.service")
    return render_template("service.html", status=st, title="Service")

@app.route("/service/action", methods=["POST"])
@login_required
def service_action():
    """Startet oder prüft definierte Systemd-Dienste (Logger/WebApp)."""
    service = request.form.get("service")
    action = request.form.get("action")

    valid_services = {
        "logger": "brunnen_logger.service",
        "web": "brunnen_web.service"
    }

    if service not in valid_services or action not in ("status", "restart"):
        abort(400)

    service_name = valid_services[service]

    try:
        if action == "status":
            st = service_status(service)
            return jsonify({"status": "ok", "message": st})

        # Wenn die WebApp sich selbst neu startet → gleich Erfolg melden
        if service in ("brunnen_web.service", "web"):
            subprocess.Popen(
                ["sudo", "systemctl", "restart", "brunnen_web.service"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return jsonify({
                "status": "ok",
                "message": "🔄 WebApp wird neu gestartet. Bitte warte ein paar Sekunden und lade neu."
            })
        
        if action == "status":
            st = service_status(service_name)
            return jsonify({"status": "ok", "message": st})

        # 🔄 Neustart ausführen
        result = subprocess.run(
            ["sudo", "/bin/systemctl", "restart", service_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        time.sleep(3)
        st = service_status(service_name)

        if result.returncode == 0:
            return jsonify({
                "status": "ok",
                "message": f"✅ {service_name} erfolgreich neu gestartet ({st})"
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"❌ Fehler: {result.stderr.strip() or result.stdout.strip()}"
            }), 500

    except Exception as e:
        return jsonify({"status": "error", "message": f"❌ Unerwarteter Fehler: {e}"}), 500

@app.route("/update-system", methods=["POST"])
@login_required
def update_system():
    """Startet das GitHub-Update-Skript."""
    script_path = "/opt/brunnen_web/scripts/update_repo.sh"
    if not os.path.exists(script_path):
        return jsonify({"success": False, "message": f"Skript nicht gefunden: {script_path}"}), 404

    try:
        result = subprocess.check_output(
            ["sudo", script_path],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=180
        )
        return jsonify({"success": True, "message": result})
    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "message": e.output}), 500
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/logs")
@login_required
def logs_page():
    # wählbare Logs
    files = {
        "Service": os.path.join(LOG_DIR, "webapp.err.log"),
        "Logger": os.path.join(LOG_DIR, "logger.err.log")
        #"Webapp": os.path.join(LOG_DIR, "webapp.log")
    }
    chosen = request.args.get("file","Service")
    path = files.get(chosen, list(files.values())[0])
    content = tail_file(path, lines=30)
    return render_template("logs.html", files=list(files.keys()), chosen=chosen, content=content, title="Logs")

@app.route("/database", methods=["GET", "POST"])
@login_required
def db_config_page():
    cfg = load_config()
    db_keys = ["INFLUX_URL", "INFLUX_TOKEN", "INFLUX_ORG", "INFLUX_BUCKET"]
    db_config = {k: cfg.get(k, "") for k in db_keys}

    descriptions = {
        "INFLUX_URL": "URL des InfluxDB-Servers, z. B. http://192.168.1.50:8086",
        "INFLUX_TOKEN": "API-Token der InfluxDB-Instanz.",
        "INFLUX_ORG": "Organisation (Org-Name in InfluxDB).",
        "INFLUX_BUCKET": "Ziel-Bucket für Messdaten."
    }

    if request.method == "POST":
        for key in db_keys:
            if key in request.form:
                db_config[key] = request.form[key]
                cfg[key] = request.form[key]
        save_config(cfg)
        flash("✅ InfluxDB-Konfiguration gespeichert.", "success")
        return redirect(url_for("db_config_page"))

    return render_template("database.html", config=db_config, descriptions=descriptions, title="Datenbank")


# ===== Aktuelle Messwerte =====
@app.route("/measurements")
@login_required
def measurements_page():
    # Pfad zur temporären Datei, die der Logger schreiben soll
    data_file = os.path.join(BASE_DIR, "data", "latest_measurement.json")
    data = {
        "timestamp": "—",
        "voltage_V": 0,
        "current_mA": 0,
        "depth_m": 0,
        "water_surface_m": 0,
        "nn_level_m": 0,
        "delta_m": 0
    }
    if os.path.exists(data_file):
        try:
            with open(data_file, "r") as f:
                data = json.load(f)
        except Exception as e:
            data["timestamp"] = f"Fehler beim Lesen: {e}"
    return render_template("measurements.html", data=data, title="Aktuelle Messwerte")

# API-Endpunkt für AJAX-Abfragen
@app.route("/api/measurements")
@login_required
def measurements_api():
    data_file = os.path.join(BASE_DIR, "data", "latest_measurement.json")
    if os.path.exists(data_file):
        try:
            with open(data_file, "r") as f:
                data = json.load(f)
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)})
    return jsonify({"error": "Keine Messdaten gefunden"})

# Systemstatus

@app.route("/systemstatus")
@login_required
def systemstatus_page():
    # Systeminfos abrufen
    import psutil, platform, socket, subprocess, time
    from datetime import timedelta

    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        uptime_seconds = time.time() - psutil.boot_time()
        uptime = str(timedelta(seconds=int(uptime_seconds)))
        hostname = socket.gethostname()
        ip = subprocess.getoutput("hostname -I").split()[0]
        wifi = subprocess.getoutput("iwgetid -r") or "nicht verbunden"
        try:
            temps = psutil.sensors_temperatures()
            if "cpu_thermal" in temps:
                temp = round(temps["cpu_thermal"][0].current, 1)
            elif "coretemp" in temps:
                temp = round(temps["coretemp"][0].current, 1)
            else:
                temp = "?"
        except Exception:
            temp = "?"

        # 🔍 WLAN-Netzwerke abrufen
        networks = []
        try:
            result = subprocess.check_output(
                ["nmcli", "-t", "-f", "SSID,SIGNAL", "dev", "wifi"],
                stderr=subprocess.DEVNULL
            )
            for line in result.decode().splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and parts[0].strip():
                    networks.append({"ssid": parts[0], "signal": parts[1]})
        except Exception as e:
            networks = [{"ssid": f"Fehler: {e}", "signal": 0}]

        # Systemdaten zusammenstellen
        data = {
            "hostname": hostname,
            "ip": ip,
            "wifi": wifi,
            "cpu": cpu,
            "temp": temp,
            "ram_used": round(ram.used/1024/1024, 1),
            "ram_total": round(ram.total/1024/1024, 1),
            "disk_used": round(disk.used/1024/1024/1024, 1),
            "disk_total": round(disk.total/1024/1024/1024, 1),
            "disk_percent": disk.percent,
            "uptime": uptime,
            "os": platform.platform(),
            "networks": networks
        }
        return render_template("systemstatus.html", title="Systemstatus", sys=data)
    except Exception as e:
        return f"Fehler beim Laden des Systemstatus: {e}", 500

@app.route("/wifi/configure", methods=["POST"])
@login_required
def wifi_configure():
    ssid = (request.form.get("ssid", "") or request.form.get("ssid_manual", "")).strip()
    psk = request.form.get("psk", "").strip()

    if not ssid:
        return jsonify({"status": "error", "message": "❌ SSID darf nicht leer sein."})
    if not psk:
        return jsonify({"status": "error", "message": "❌ Passwort darf nicht leer sein."})

    try:
        config_block = f'\nnetwork={{\n  ssid="{ssid}"\n  psk="{psk}"\n}}\n'

        # 🔹 Schreibe sicher über 'tee' (läuft mit root-Rechten)
        subprocess.run(
            ["sudo", "-n", "tee", "-a", "/etc/wpa_supplicant/wpa_supplicant.conf"],
            input=config_block.encode(),
            check=True,
        )

        # 🔹 WLAN-Dienste neu starten
        subprocess.run(["sudo", "-n", "wpa_cli", "-i", "wlan0", "reconfigure"], check=False)
        subprocess.run(["sudo", "-n", "systemctl", "restart", "NetworkManager"], check=False)

        return jsonify({
            "status": "ok",
            "message": f"✅ WLAN wird mit „{ssid}“ verbunden..."
        })

    except subprocess.CalledProcessError as e:
        return jsonify({
            "status": "error",
            "message": f"❌ Fehler beim Schreiben der WLAN-Konfiguration: {e}"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"❌ Unerwarteter Fehler: {e}"
        })




# Ausgänge Zeitsteuerung

from threading import Thread
from datetime import datetime
import json, time

SCHEDULE_FILE = os.path.join(BASE_DIR, "config", "output_schedule.json")

def load_schedule():
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE) as f:
            return json.load(f)
    return []

def save_schedule(data):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def scheduler_loop():
    while True:
        now = datetime.now().strftime("%H:%M")
        schedule = load_schedule()
        for job in schedule:
            if job["time"] == now:
                mosfet_control.set_output(job["channel"], job["state"])
        time.sleep(60)

Thread(target=scheduler_loop, daemon=True).start()


# Start
if __name__ == "__main__":
    # läuft auf 0.0.0.0:8080
    app.run(host="0.0.0.0", port=8080, debug=False)
