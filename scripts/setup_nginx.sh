#!/bin/bash
# ============================================================
# 💧 BrunnenWeb – Nginx + SSL Setup (idempotent)
# Läuft bei Erstinstallation UND bei OTA-Updates.
# ============================================================

BASE_DIR="/opt/brunnen_web"
CERT_DIR="$BASE_DIR/certs"
NGINX_CONF="/etc/nginx/sites-available/brunnen_web"
NGINX_ENABLED="/etc/nginx/sites-enabled/brunnen_web"
CERT_FILE="$CERT_DIR/brunnen.crt"
KEY_FILE="$CERT_DIR/brunnen.key"
LOG="$BASE_DIR/logs/setup_nginx.log"

mkdir -p "$BASE_DIR/logs"
echo "=== setup_nginx.sh gestartet: $(date) ===" | tee -a "$LOG"

# ── 1. nginx installieren ──────────────────────────────────
if ! command -v nginx &>/dev/null; then
  echo "Installiere nginx..." | tee -a "$LOG"
  apt-get install -y nginx >>"$LOG" 2>&1
fi

# ── 2. Zertifikats-Verzeichnis anlegen ─────────────────────
mkdir -p "$CERT_DIR"
chown brunnen:brunnen "$CERT_DIR"
chmod 750 "$CERT_DIR"

# ── 3. Selbstsigniertes Zertifikat erzeugen (falls fehlt) ──
if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
  echo "Erzeuge selbstsigniertes Zertifikat (10 Jahre)..." | tee -a "$LOG"
  CN=$(hostname -f 2>/dev/null || hostname)
  openssl req -x509 -nodes -days 3650 \
    -newkey rsa:2048 \
    -keyout "$KEY_FILE" \
    -out "$CERT_FILE" \
    -subj "/C=DE/ST=Bayern/O=BrunnenWeb/CN=$CN" >>"$LOG" 2>&1
  chown brunnen:brunnen "$CERT_FILE" "$KEY_FILE"
  chmod 644 "$CERT_FILE"
  chmod 640 "$KEY_FILE"
  echo "Zertifikat erstellt: $CERT_FILE" | tee -a "$LOG"
else
  echo "Zertifikat bereits vorhanden – wird nicht überschrieben." | tee -a "$LOG"
fi

# ── 4. nginx-Konfiguration schreiben ──────────────────────
cat > "$NGINX_CONF" << 'NGINXEOF'
# BrunnenWeb – HTTP → HTTPS Redirect + SSL Reverse Proxy
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate     /opt/brunnen_web/certs/brunnen.crt;
    ssl_certificate_key /opt/brunnen_web/certs/brunnen.key;

    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 10m;

    # Für Zertifikat-Upload via WebGUI
    client_max_body_size 10M;

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
        proxy_connect_timeout 10s;
    }
}
NGINXEOF

echo "nginx-Konfiguration geschrieben." | tee -a "$LOG"

# ── 5. Site aktivieren, Default entfernen ─────────────────
ln -sf "$NGINX_CONF" "$NGINX_ENABLED"
rm -f /etc/nginx/sites-enabled/default

# ── 6. nginx aktivieren + neu laden ───────────────────────
systemctl enable nginx >>"$LOG" 2>&1

if nginx -t >>"$LOG" 2>&1; then
  systemctl reload nginx >>"$LOG" 2>&1 || systemctl restart nginx >>"$LOG" 2>&1
  echo "nginx erfolgreich neu geladen." | tee -a "$LOG"
else
  echo "FEHLER: nginx -t schlug fehl – prüfe $LOG" | tee -a "$LOG"
  exit 1
fi

echo "=== setup_nginx.sh abgeschlossen: $(date) ===" | tee -a "$LOG"
