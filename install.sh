#!/bin/bash
# ============================================================
# 💧 Brunnen-Web Installationsskript
# Erstellt Verzeichnisse, virtuelle Umgebung, Abhängigkeiten
# und richtet den Systemd-Dienst ein.
# ============================================================

set -e  # Bei Fehlern abbrechen

# ------------------------------------------------------------
# 🧩 Konfiguration
# ------------------------------------------------------------
BASE_DIR="/opt/brunnen"
USER="brunnen"
VENV_DIR="$BASE_DIR/venv"
CONFIG_DIR="$BASE_DIR/config"
DATA_DIR="$BASE_DIR/data"
LOG_DIR="$BASE_DIR/logs"
SCRIPT_DIR="$BASE_DIR/scripts"
SERVICE_FILE="/etc/systemd/system/brunnen.service"

# ------------------------------------------------------------
# 🎨 Farben & Formatierung
# ------------------------------------------------------------
GREEN="\e[32m"
YELLOW="\e[33m"
RED="\e[31m"
BLUE="\e[36m"
BOLD="\e[1m"
RESET="\e[0m"

# ------------------------------------------------------------
# 🧭 Hilfsfunktion
# ------------------------------------------------------------
section() {
  echo -e "\n${BLUE}${BOLD}=== $1 ===${RESET}"
}

ok() {
  echo -e "  ${GREEN}✔${RESET} $1"
}

warn() {
  echo -e "  ${YELLOW}⚠${RESET} $1"
}

err() {
  echo -e "  ${RED}✖${RESET} $1"
}

# ------------------------------------------------------------
# 🚀 Installation
# ------------------------------------------------------------
section "Starte Installation des Brunnen-Systems"

section "1️⃣  Systempakete installieren"
apt update -y && apt install -y python3 python3-venv python3-pip git i2c-tools sqlite3
ok "Systempakete aktualisiert"

section "2️⃣  Verzeichnisse & Benutzer anlegen"
git clone https://github.com/zulasch/BrunnenWeb $BASE_DIR
mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR" "$SCRIPT_DIR"
id "$USER" &>/dev/null || useradd -r -s /bin/false "$USER"
chown -R "$USER:$USER" "$BASE_DIR"
ok "Verzeichnisstruktur erstellt unter $BASE_DIR"

section "3️⃣  Virtuelle Python-Umgebung einrichten"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
  ok "Virtuelle Umgebung erstellt"
else
  warn "Virtuelle Umgebung bereits vorhanden"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install flask psutil influxdb-client adafruit-circuitpython-ads1x15 board
deactivate
ok "Python-Abhängigkeiten installiert"

section "4️⃣  Beispielkonfiguration anlegen"
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
ok "Beispielkonfiguration erstellt unter $CONFIG_FILE"
else
  warn "Konfiguration bereits vorhanden"
fi

section "5️⃣  Systemd-Service konfigurieren"
cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Brunnen Messsystem (Logger + Webinterface)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$BASE_DIR
ExecStart=$SCRIPT_DIR/start_brunnen.sh
Restart=always
RestartSec=5
StandardOutput=append:$LOG_DIR/brunnen.service.log
StandardError=append:$LOG_DIR/brunnen.service.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
ok "Systemd-Service-Datei erstellt: $SERVICE_FILE"

section "6️⃣  Start- und Stop-Skripte anlegen"
cat <<EOF > "$SCRIPT_DIR/start_brunnen.sh"
#!/bin/bash
cd "$BASE_DIR"
echo "🚀 Starte Brunnen-System ..."
source "$VENV_DIR/bin/activate"
nohup python3 wasserstand_logger.py >> "$LOG_DIR/wasserstand_logger.log" 2>&1 &
nohup python3 webapp.py >> "$LOG_DIR/webapp.log" 2>&1 &
EOF

cat <<EOF > "$SCRIPT_DIR/stop_brunnen.sh"
#!/bin/bash
pkill -f wasserstand_logger.py 2>/dev/null
pkill -f webapp.py 2>/dev/null
echo "🛑 Brunnen-System gestoppt."
EOF

chmod +x "$SCRIPT_DIR/"*.sh
ok "Start-/Stop-Skripte bereitgestellt"

section "7️⃣  Dienst aktivieren"
systemctl daemon-reload
systemctl enable brunnen.service
ok "Systemd-Dienst aktiviert"

# ------------------------------------------------------------
# 🎉 Abschluss
# ------------------------------------------------------------
section "✅ Installation abgeschlossen!"
echo -e "${GREEN}${BOLD}Starte Service:${RESET} sudo systemctl start brunnen.service"
echo -e "${GREEN}${BOLD}Prüfe Status:${RESET} sudo systemctl status brunnen.service"
echo -e "${GREEN}${BOLD}Logs anzeigen:${RESET} tail -f $LOG_DIR/brunnen.service.log"
echo -e "\n${BOLD}Viel Erfolg mit deinem Brunnen-Websystem! 💧${RESET}"
