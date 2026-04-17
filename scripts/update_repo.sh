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

# Hilfsfunktion: Ausgabe geht gleichzeitig auf stdout (→ WebGUI) und ins Logfile
log() { echo "$@" | tee -a "$LOG"; }
run() { "$@" 2>&1 | tee -a "$LOG"; return "${PIPESTATUS[0]}"; }

log "🌀 Starte GitHub Update am $(date)"

# ── Betriebssystem-Updates ─────────────────────────────────
log "🖥️  Aktualisiere Betriebssystem (apt)..."
run DEBIAN_FRONTEND=noninteractive apt-get update
run DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
if [ ${PIPESTATUS[0]} -eq 0 ]; then
  log "✅ Betriebssystem erfolgreich aktualisiert."
else
  log "⚠️  apt upgrade fehlgeschlagen – Update wird trotzdem fortgesetzt."
fi

cd "$BASE_DIR" || exit 1

# Prüfe Repository-Zustand
if [ ! -d ".git" ]; then
  log "❌ Kein Git-Repository gefunden unter $BASE_DIR"
  exit 1
fi

# Eigentümerschaft sicherstellen (verhindert git-Permissions-Fehler)
log "🔑 Prüfe Dateiberechtigungen..."
chown -R "$USER":"$USER" "$BASE_DIR" 2>&1 | tee -a "$LOG"

# Als Brunnen-User ausführen (sicherer)
log "📥 git reset --hard HEAD..."
run sudo -u "$USER" git reset --hard HEAD

log "📥 git pull..."
run sudo -u "$USER" git pull

if [ ${PIPESTATUS[0]} -ne 0 ]; then
  log "❌ Fehler beim Aktualisieren der Repository"
  exit 1
fi

log "✅ Repository erfolgreich aktualisiert."

# Virtuelle Umgebung prüfen
if [ -d "$BASE_DIR/venv" ]; then
  log "📦 Aktualisiere Python-Abhängigkeiten..."
  source "$BASE_DIR/venv/bin/activate"
  run pip install -r "$BASE_DIR/requirements.txt"
fi

# Nginx + SSL idempotent aktualisieren (neue Config, Zertifikat nur wenn fehlend)
if [ -f "$BASE_DIR/scripts/setup_nginx.sh" ]; then
  log "🔒 Aktualisiere nginx-Konfiguration..."
  run sudo bash "$BASE_DIR/scripts/setup_nginx.sh"
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
    log "🔧 Deploy systemd unit: $unit"
    run sudo cp "$SRC" "$DST"
    sudo chmod 644 "$DST"
  else
    log "⚠️ Unit nicht gefunden im Repo: $SRC"
  fi
done

run sudo systemctl daemon-reload

# Unit beim Boot aktivieren (idempotent)
run sudo systemctl enable brunnen_display.service

# Display-Service neu starten
run sudo systemctl restart brunnen_display.service

# Service-Neustart verzögern (3 Sekunden nach Abschluss)
log "🕒 Plane Neustart in 3 Sekunden..."
(sleep 3 && sudo systemctl restart $SERVICE) >/dev/null 2>&1 &
log "✅ Update abgeschlossen – Server wird automatisch neu gestartet."
log "🟢 Update abgeschlossen am $(date)"
