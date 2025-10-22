#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, socket, subprocess, functools, time
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, abort, flash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# ===== Flask =====
app = Flask(__name__, template_folder="templates")
# Geheimschlüssel (für Sessions). In Produktion in ENV legen!
app.config["SECRET_KEY"] = os.environ.get("WEBAPP_SECRET", "change-me-please")

# ===== Helpers =====
def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

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
    descriptions = {
        "STARTABSTICH": "Abstand Gelände → Wasseroberfläche beim Start [m].",
        "INITIAL_WASSERTIEFE": "Initiale Sonden-Wassertiefe [m] (z. B. 2.5).",
        "SHUNT_OHMS": "Shunt-Widerstand [Ω] (typ. 150 Ω).",
        "WERT_4mA": "Sondenwert [m] bei 4 mA (untere Grenze).",
        "WERT_20mA": "Sondenwert [m] bei 20 mA (obere Grenze).",
        "MESSWERT_NN": "Geländehöhe über NN [m].",
        "MESSINTERVAL": "Messintervall [s].",
        "INFLUX_URL": "URL des InfluxDB-Servers.",
        "INFLUX_TOKEN": "InfluxDB API-Token.",
        "INFLUX_ORG": "InfluxDB-Organisation.",
        "INFLUX_BUCKET": "InfluxDB-Bucket.",
        "ADMIN_PIN": "PIN für Web-Login (4–8 Ziffern)."
    }
    return render_template("index.html", config=cfg, descriptions=descriptions, title="Messsystem")

from pathlib import Path

@app.route("/update", methods=["POST"])
@login_required
def update_config():
    try:
        data = request.form.to_dict()
        cfg = load_config()

        # Nur bekannte Parameter aktualisieren
        for key, value in data.items():
            if key in cfg:
                try:
                    cfg[key] = float(value)
                except ValueError:
                    cfg[key] = value  # Strings (z. B. URLs)

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

        
@app.route("/service")
@login_required
def service_page():
    st = service_status("brunnen.service")
    return render_template("service.html", status=st, title="Service")

@app.route("/service/action", methods=["POST"])
@login_required
def service_action():
    action = request.form.get("action")
    if action != "restart":
        abort(400)  # Nur Restart erlaubt

    try:
        # Neustart ausführen
        subprocess.check_call(["sudo", "systemctl", "restart", "brunnen.service"])
        time.sleep(1.5)  # kurz warten, damit systemd den Dienst wieder hochfährt

        # Status prüfen
        st = service_status("brunnen.service")
        if st == "active":
            return jsonify({
                "status": "ok",
                "message": "✅ Dienst erfolgreich neu gestartet und läuft wieder."
            })
        else:
            return jsonify({
                "status": "warning",
                "message": f"⚠️ Dienst wurde neu gestartet, aktueller Status: {st}"
            })
    except subprocess.CalledProcessError as e:
        return jsonify({
            "status": "error",
            "message": f"❌ Neustart fehlgeschlagen: {e}"
        }), 500
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"❌ Unerwarteter Fehler: {e}"
        }), 500



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
        "Service": os.path.join(LOG_DIR, "brunnen.service.log"),
        "Logger": os.path.join(LOG_DIR, "wasserstand.log")
        #"Webapp": os.path.join(LOG_DIR, "webapp.log")
    }
    chosen = request.args.get("file","Service")
    path = files.get(chosen, list(files.values())[0])
    content = tail_file(path, lines=300)
    return render_template("logs.html", files=list(files.keys()), chosen=chosen, content=content, title="Logs")

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
            temp_out = subprocess.check_output(["vcgencmd", "measure_temp"]).decode().strip()
            temp = temp_out.replace("temp=", "").replace("'C", "")
        except Exception:
            temp = "?"

        # WLAN-Netzwerke abrufen
        networks = []
        try:
            result = subprocess.check_output(["nmcli", "-t", "-f", "SSID,SIGNAL", "dev", "wifi"], stderr=subprocess.DEVNULL)
            for line in result.decode().splitlines():
                parts = line.split(":")
                if len(parts) >= 2 and parts[0].strip():
                    networks.append({"ssid": parts[0], "signal": parts[1]})
        except Exception:
            pass

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




# Start
if __name__ == "__main__":
    # läuft auf 0.0.0.0:8080
    app.run(host="0.0.0.0", port=8080, debug=False)
