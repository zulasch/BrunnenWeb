#!/bin/bash
# ============================================================
#  Brunnen-Web Installationsskript
#  Erstellt alle benötigten Verzeichnisse, venv, Abhängigkeiten
#  und Systemd-Dienste.
# ============================================================

set -e  # Bei Fehlern abbrechen

BASE_DIR="/opt/brunnenweb"
USER="brunnen"
VENV_DIR="$BASE_DIR/venv"
CONFIG_DIR="$BASE_DIR/config"
DATA_DIR="$BASE_DIR/data"
LOG_DIR="$BASE_DIR/logs"
SCRIPT_DIR="$BASE_DIR/scripts"
TEMPLATE_DIR="$BASE_DIR/templates"

SERVICE_FILE="/etc/systemd/system/brunnen.service"

echo "🔧 Starte Installation des Brunnen-Systems ..."

# ============================================================
# 1️⃣ Grundlegende Pakete installieren
# ============================================================
echo "📦 Aktualisiere Systempakete..."
apt update -y
apt install -y python3 python3-venv python3-pip git i2c-tools sqlite3


# ============================================================
# 2️⃣ Projektverzeichnis erstellen
# ============================================================
echo "📁 Erstelle Verzeichnisstruktur unter $BASE_DIR ..."
mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR" "$SCRIPT_DIR" "$TEMPLATE_DIR"
useradd -r -s /bin/false $USER || true
chown -R $USER:$USER $BASE_DIR

# ============================================================
# 3️⃣ Virtuelle Umgebung
# ============================================================
if [ ! -d "$VENV_DIR" ]; then
    echo "🐍 Erstelle virtuelle Python-Umgebung..."
    python3 -m venv "$VENV_DIR"
fi

echo "📦 Installiere Python-Abhängigkeiten..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install adafruit-circuitpython-ads1x15 influxdb-client flask board
deactivate

# ============================================================
# 4️⃣ Beispielkonfiguration anlegen (falls nicht vorhanden)
# ============================================================
CONFIG_FILE="$CONFIG_DIR/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
cat <<EOF > "$CONFIG_FILE"
{
  "STARTABSTICH": 10.0,
  "INITIAL_WASSERTIEFE": 2.5,
  "SHUNT_OHMS": 150.0,
  "WERT_4mA": 0.0,
  "WERT_20mA": 3.0,
  "MESSWERT_NN": 530.0,
  "MESSINTERVAL": 5,
  "INFLUX_URL": "",
  "INFLUX_TOKEN": "",
  "INFLUX_ORG": "",
  "INFLUX_BUCKET": ""
}
EOF
fi

# ============================================================
# 5️⃣ Systemd-Service anlegen
# ============================================================
echo "⚙️  Erstelle systemd-Service $SERVICE_FILE ..."
cat <<EOF | tee "$SERVICE_FILE" > /dev/null
[Unit]
Description=Brunnen Messsystem (Logger + Webinterface)
After=network.target

[Service]
Type=forking
User=root
WorkingDirectory=$BASE_DIR
ExecStart=$SCRIPT_DIR/start_brunnen.sh
ExecStop=$SCRIPT_DIR/stop_brunnen.sh
Restart=always
RestartSec=10
StandardOutput=append:$LOG_DIR/brunnen.service.log
StandardError=append:$LOG_DIR/brunnen.service.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# ============================================================
# 6️⃣ Beispiel-Start-/Stop-Skripte erzeugen
# ============================================================
echo "🚀 Erstelle Start- und Stop-Skripte..."

cat <<EOF > "$SCRIPT_DIR/start_brunnen.sh"
#!/bin/bash
BASE_DIR="$BASE_DIR"
VENV_DIR="$VENV_DIR"
LOG_DIR="$LOG_DIR"

cd "\$BASE_DIR"

echo "🚀 Starte Brunnen-System ..."
"\$VENV_DIR/bin/python" wasserstand_logger.py >> "\$LOG_DIR/wasserstand_logger.log" 2>&1 &
"\$VENV_DIR/bin/python" webapp.py >> "\$LOG_DIR/webapp.log" 2>&1 &

echo \$! > "\$DATA_DIR/webapp.pid"
pgrep -f wasserstand_logger.py > "\$DATA_DIR/logger.pid"
EOF

cat <<EOF > "$SCRIPT_DIR/stop_brunnen.sh"
#!/bin/bash
BASE_DIR="$BASE_DIR"
DATA_DIR="$DATA_DIR"

if [ -f "\$DATA_DIR/webapp.pid" ]; then
  kill \$(cat "\$DATA_DIR/webapp.pid") 2>/dev/null && rm "\$DATA_DIR/webapp.pid"
fi
if [ -f "\$DATA_DIR/logger.pid" ]; then
  kill \$(cat "\$DATA_DIR/logger.pid") 2>/dev/null && rm "\$DATA_DIR/logger.pid"
fi

pkill -f wasserstand_logger.py 2>/dev/null
pkill -f webapp.py 2>/dev/null

echo "🛑 Brunnen-System gestoppt."
EOF

chmod +x "$SCRIPT_DIR/start_brunnen.sh" "$SCRIPT_DIR/stop_brunnen.sh"

# ============================================================
# 7️⃣ Dienste aktivieren
# ============================================================
echo "🔄 Aktiviere Brunnen-Service..."
systemctl daemon-reload
systemctl enable brunnen.service

# ============================================================
# 8️⃣ Abschluss
# ============================================================
echo "✅ Installation abgeschlossen!"
echo "Starte Dienst mit:  sudo systemctl start brunnen.service"
echo "Prüfe Status mit:  sudo systemctl status brunnen.service"
echo "Logs:              tail -f $LOG_DIR/brunnen.service.log"



