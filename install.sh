#!/bin/bash
# ============================================================
# 💧 Brunnen-Web Installationsskript
# Erstellt Verzeichnisse, virtuelle Umgebung, Abhängigkeiten
# und richtet den Systemd-Dienst ein.
#
# ============================================================

set -e  # Bei Fehlern abbrechen

# ------------------------------------------------------------
# 🧩 Konfiguration
# ------------------------------------------------------------
BASE_DIR="/opt/brunnen_web"
USER="brunnen"
VENV_DIR="$BASE_DIR/venv"
CONFIG_DIR="$BASE_DIR/config"
DATA_DIR="$BASE_DIR/data"
LOG_DIR="$BASE_DIR/logs"
WEB_SERVICE_FILE="/etc/systemd/system/brunnen_web.service"
LOGGER_SERVICE_FILE="/etc/systemd/system/brunnen_logger.service"

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
apt -y update && apt -y upgrade && apt install -y python3 swig liblgpio-dev python3-lgpio libgpiod3 python3-dev python3-setuptools python3-wheel build-essential python3-venv python3-pip git i2c-tools sqlite3 openvpn
ok "Systempakete aktualisiert"

section "2️⃣  Verzeichnisse & Benutzer anlegen"
git clone https://github.com/zulasch/BrunnenWeb $BASE_DIR
mkdir -p "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
id "$USER" &>/dev/null || useradd -r -s /bin/false "$USER"
chown -R "$USER:$USER" "$BASE_DIR"
ok "Verzeichnisstruktur erstellt unter $BASE_DIR"
usermod -aG i2c $USER
usermod -aG gpio $USER

SUDOERS_FILE="/etc/sudoers.d/$USER"
cat <<EOF > "$SUDOERS_FILE"
# Erlaubt dem Benutzer '$USER' kontrollierte Service-Kommandos ohne Passwort
brunnen ALL=NOPASSWD: /usr/bin/tee -a /etc/wpa_supplicant/wpa_supplicant.conf
brunnen ALL=NOPASSWD: /usr/bin/wpa_cli
brunnen ALL=NOPASSWD: /usr/bin/systemctl restart brunnen_web.service
brunnen ALL=NOPASSWD: /usr/bin/systemctl restart brunnen_logger.service
brunnen ALL=NOPASSWD: /bin/systemctl restart brunnen_web.service
brunnen ALL=NOPASSWD: /bin/systemctl restart brunnen_logger.service
brunnen ALL=NOPASSWD: /usr/bin/systemctl restart NetworkManager
brunnen ALL=NOPASSWD: $BASE_DIR/scripts/update_repo.sh
EOF

chmod 440 "$SUDOERS_FILE"

# Test, ob Datei gültig ist
if visudo -c -f "$SUDOERS_FILE" >/dev/null 2>&1; then
  ok "Sudo-Regel erfolgreich erstellt und validiert: $SUDOERS_FILE"
else
  err "Fehler in der sudoers-Datei – bitte prüfen: $SUDOERS_FILE"
fi

section "Logrotate Configuration"

cat << 'EOF' > /etc/logrotate.d/brunnen_web
/opt/brunnen_web/logs/logger.err.log
/opt/brunnen_web/logs/wasserstand.log
/opt/brunnen_web/logs/webapp.err.log
/var/log/check-vpn.log 
{
    size 5M
    rotate 7
    missingok
    notifempty
    copytruncate
    create 644 root root
}
EOF


section "3️⃣  Virtuelle Python-Umgebung einrichten"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
  ok "Virtuelle Umgebung erstellt"
else
  warn "Virtuelle Umgebung bereits vorhanden"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip
#pip install flask psutil influxdb-client adafruit-circuitpython-ads1x15 board RPi.GPIO gunicorn lgpio adafruit-circuitpython-ssd1306 pillow luma.oled adafruit-circuitpython-bmp280 requests
pip install -r requirements.txt
deactivate
ok "Python-Abhängigkeiten installiert"

section "4️⃣  Beispielkonfiguration anlegen"
CONFIG_FILE="$CONFIG_DIR/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
cat <<EOF > "$CONFIG_FILE"
{
  "NAME_A0": "Nordbrunnen ABC",
  "SENSOR_TYP_A0": "LEVEL",
  "SENSOR_EINHEIT_A0": "m",
  "WERT_4mA_A0": 0.0,
  "WERT_20mA_A0": 3.0,
  "SHUNT_OHMS_A0": 150.0,
  "STARTABSTICH_A0": 100.0,
  "INITIAL_WASSERTIEFE_A0": 25.0,
  "MESSWERT_NN_A0": 100.0,

  "NAME_A1": "Pumpentemperatur",
  "SENSOR_TYP_A1": "TEMP",
  "SENSOR_EINHEIT_A1": "°C",
  "WERT_4mA_A1": 0.0,
  "WERT_20mA_A1": 80.0,
  "SHUNT_OHMS_A1": 150.0,

  "NAME_A2": "Pumpendurchfluss",
  "SENSOR_TYP_A2": "FLOW",
  "SENSOR_EINHEIT_A2": "m3/h",
  "WERT_4mA_A2": 0.0,
  "WERT_20mA_A2": 60.0,
  "SHUNT_OHMS_A2": 150.0,

  "NAME_A3": "reserve",
  "SENSOR_TYP_A2": "LEVEL",
  "SENSOR_EINHEIT_A2": "m3/h",
  "WERT_4mA_A3": 0.0,
  "WERT_20mA_A3": 10.0,
  "SHUNT_OHMS_A3": 150.0,
  "STARTABSTICH_A3": 0,
  "INITIAL_WASSERTIEFE_A3": 0,
  "MESSWERT_NN_A3": 0,

  "MESSINTERVAL": 5.0,
  "ADMIN_PIN": 5335,
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
WEBAPP_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
ok "Zufälliger WEBAPP_SECRET generiert"

cat <<EOF > "$WEB_SERVICE_FILE"
[Unit]
Description=Brunnen Webinterface (Flask via Gunicorn)
After=network.target

[Service]
User=brunnen
Group=brunnen
SupplementaryGroups=gpio
WorkingDirectory=$BASE_DIR
ExecStart=$BASE_DIR/venv/bin/gunicorn -w 1 --threads 1 -t 180 -b 0.0.0.0:8080 webapp:app
Restart=always
Environment="PATH=$BASE_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="WEBAPP_SECRET=$WEBAPP_SECRET"
StandardError=append:$BASE_DIR/logs/webapp.err.log

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF > "$LOGGER_SERVICE_FILE"
[Unit]
Description=Brunnen Messsystem (Sensorlogger)
After=network.target

[Service]
User=brunnen
Group=brunnen
SupplementaryGroups=gpio
WorkingDirectory=$BASE_DIR
ExecStart=$BASE_DIR/venv/bin/python $BASE_DIR/wasserstand_logger.py
Restart=always
Environment="PATH=$BASE_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
StandardError=append:$BASE_DIR/logs/logger.err.log

[Install]
WantedBy=multi-user.target
EOF

ok "Systemd-Service-Datei erstellt: $WEB_SERVICE_FILE"

section "6️⃣  Start- und Stop-Skripte anlegen"

section "7️⃣  Dienst aktivieren"
systemctl daemon-reload
systemctl enable brunnen_web.service 
systemctl enable brunnen_logger.service
ok "Systemd-Dienst aktiviert"

section "8️⃣  I²C aktivieren"
if command -v raspi-config &>/dev/null; then
    raspi-config nonint do_i2c 0
    ok "I²C-Schnittstelle aktiviert"
else
    warn "raspi-config nicht gefunden – aktiviere I²C manuell"
fi

chown -R "$USER:$USER" "$BASE_DIR"

# WiFi 

rfkill unblock wifi
rfkill unblock all
ip link set wlan0 up

systemctl enable wpa_supplicant
systemctl start wpa_supplicant
systemctl enable NetworkManager
systemctl start NetworkManager


# ------------------------------------------------------------
# 🎉 Abschluss
# ------------------------------------------------------------
section "9️⃣  Starte Dienste"

systemctl restart brunnen_web.service brunnen_logger.service
systemctl status brunnen_web.service brunnen_logger.service

section "✅ Installation abgeschlossen!"
echo -e "${GREEN}${BOLD}Starte Service:${RESET} systemctl start brunnen_web.service brunnen_logger.service"
echo -e "${GREEN}${BOLD}Stoppe Service:${RESET} systemctl stop brunnen_web.service brunnen_logger.service"
echo -e "${GREEN}${BOLD}Prüfe Status:${RESET} systemctl status brunnen_web.service brunnen_logger.service"
echo -e "${GREEN}${BOLD}Logs für die Webapp anzeigen:${RESET} tail -f $BASE_DIR/logs/webapp.err.log"
echo -e "${GREEN}${BOLD}Logs für den Logger anzeigen:${RESET} tail -f $BASE_DIR/logs/logger.err.log"
echo -e "\n${BOLD}Viel Erfolg mit deinem Brunnen-Websystem! 💧${RESET}"
