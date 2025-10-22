#!/bin/bash
# ============================================================
# 💧 Brunnen – Automatisches GitHub Update
# ============================================================
# Dieses Skript aktualisiert den Brunnen-Code aus GitHub
# und startet anschließend den Systemd-Service neu.
# ============================================================

BASE_DIR="/opt/brunnen_web"
SERVICE="brunnen.service"
USER="brunnen"
LOG="$BASE_DIR/logs/update.log"

echo "🌀 Starte GitHub Update am $(date)" | tee -a "$LOG"

cd "$BASE_DIR" || exit 1

# Prüfe Repository-Zustand
if [ ! -d ".git" ]; then
  echo "❌ Kein Git-Repository gefunden unter $BASE_DIR" | tee -a "$LOG"
  exit 1
fi

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

# Service neu starten
echo "🔄 Starte Dienst neu..." | tee -a "$LOG"
sudo systemctl restart "$SERVICE"

if [ $? -eq 0 ]; then
  echo "✅ Dienst erfolgreich neu gestartet." | tee -a "$LOG"
else
  echo "⚠️ Fehler beim Neustart des Dienstes." | tee -a "$LOG"
fi

echo "🟢 Update abgeschlossen am $(date)" | tee -a "$LOG"
