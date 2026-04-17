#!/bin/bash
# ============================================================
# 💧 Brunnen – Automatisches GitHub Update
# ============================================================
# Dieses Skript aktualisiert den Brunnen-Code aus GitHub
# und startet anschließend den Systemd-Service neu. 
#
# ============================================================

BASE_DIR="/opt/brunnen_web"
SERVICE="brunnen_web.service brunnen_logger.service brunnen_display.service"
USER="brunnen"
LOG="$BASE_DIR/logs/update.log"

echo "🌀 Starte GitHub Update am $(date)" | tee -a "$LOG"

# ── Betriebssystem-Updates ─────────────────────────────────
echo "🖥️  Aktualisiere Betriebssystem (apt)..." | tee -a "$LOG"
DEBIAN_FRONTEND=noninteractive apt-get update -qq >>"$LOG" 2>&1
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq >>"$LOG" 2>&1
if [ $? -eq 0 ]; then
  echo "✅ Betriebssystem erfolgreich aktualisiert." | tee -a "$LOG"
else
  echo "⚠️  apt upgrade fehlgeschlagen – Update wird trotzdem fortgesetzt." | tee -a "$LOG"
fi

cd "$BASE_DIR" || exit 1

# Prüfe Repository-Zustand
if [ ! -d ".git" ]; then
  echo "❌ Kein Git-Repository gefunden unter $BASE_DIR" | tee -a "$LOG"
  exit 1
fi

# Eigentümerschaft sicherstellen (verhindert git-Permissions-Fehler)
chown -R "$USER":"$USER" "$BASE_DIR" >>"$LOG" 2>&1

# Als Brunnen-User ausführen (sicherer)
sudo -u "$USER" git reset --hard HEAD >>"$LOG" 2>&1
sudo -u "$USER" git pull >>"$LOG" 2>&1

if [ $? -ne 0 ]; then
  echo "❌ Fehler beim Aktualisieren der Repository" | tee -a "$LOG"
  exit 1
fi

echo "✅ Repository erfolgreich aktualisiert." | tee -a "$LOG"

# Virtuelle Umgebung prüfen
if [ -d "$BASE_DIR/venv" ]; then
  echo "📦 Aktualisiere Python-Abhängigkeiten..." | tee -a "$LOG"
  source "$BASE_DIR/venv/bin/activate"
  pip install -r "$BASE_DIR/requirements.txt" >>"$LOG" 2>&1
fi

# Nginx + SSL idempotent aktualisieren (neue Config, Zertifikat nur wenn fehlend)
if [ -f "$BASE_DIR/scripts/setup_nginx.sh" ]; then
  echo "🔒 Aktualisiere nginx-Konfiguration..." | tee -a "$LOG"
  sudo bash "$BASE_DIR/scripts/setup_nginx.sh" >>"$LOG" 2>&1
fi

# ------------------------------------------------------------
# 🧩 Systemd Units deployen (z.B. Display-Service)
# ------------------------------------------------------------
SYSTEMD_DIR="/etc/systemd/system"
UNITS=(
  "brunnen_display.service"
)

for unit in "${UNITS[@]}"; do
  SRC="$BASE_DIR/deploy/systemd/$unit"
  DST="$SYSTEMD_DIR/$unit"

  if [ -f "$SRC" ]; then
    echo "🔧 Deploy systemd unit: $unit" | tee -a "$LOG"
    sudo cp "$SRC" "$DST"
    sudo chmod 644 "$DST"
  else
    echo "⚠️ Unit nicht gefunden im Repo: $SRC" | tee -a "$LOG"
  fi
done

sudo systemctl daemon-reload

# Unit beim Boot aktivieren (idempotent)
sudo systemctl enable brunnen_display.service >>"$LOG" 2>&1

# Optional: direkt neu starten, wenn sie existiert
sudo systemctl restart brunnen_display.service >>"$LOG" 2>&1


# Service neu starten
# Service-Neustart verzögern (3 Sekunden nach Abschluss)
echo "🕒 Plane Neustart in 3 Sekunden..." | tee -a "$LOG"
(sleep 3 && sudo systemctl restart $SERVICE) >/dev/null 2>&1 &
echo "✅ Update abgeschlossen – Server wird automatisch neu gestartet." | tee -a "$LOG"

if [ $? -eq 0 ]; then
  echo "✅ Dienst erfolgreich neu gestartet." | tee -a "$LOG"
else
  echo "⚠️ Fehler beim Neustart des Dienstes." | tee -a "$LOG"
fi

echo "🟢 Update abgeschlossen am $(date)" | tee -a "$LOG"
