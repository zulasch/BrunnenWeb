#!/bin/bash
BASE_DIR="/root/brunnen_web"
VENV_DIR="/root/brunnen_web/venv"
LOG_DIR="$BASE_DIR/logs"

cd "$BASE_DIR"

echo "🚀 Starte Brunnen-System..."

"$VENV_DIR/bin/python" wasserstand_logger.py >> "$LOG_DIR/wasserstand_logger.log" 2>&1 &
"$VENV_DIR/bin/python" webapp.py >> "$LOG_DIR/webapp.log" 2>&1 &

echo $! > "$BASE_DIR/data/webapp.pid"
pgrep -f wasserstand_logger.py > "$BASE_DIR/data/logger.pid"

echo "✅ Brunnen-System gestartet."
