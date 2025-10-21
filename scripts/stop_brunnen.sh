#!/bin/bash
BASE_DIR="/root/brunnen_web"
DATA_DIR="$BASE_DIR/data"

if [ -f "$DATA_DIR/webapp.pid" ]; then
  kill $(cat "$DATA_DIR/webapp.pid") 2>/dev/null
  rm "$DATA_DIR/webapp.pid"
fi

if [ -f "$DATA_DIR/logger.pid" ]; then
  kill $(cat "$DATA_DIR/logger.pid") 2>/dev/null
  rm "$DATA_DIR/logger.pid"
fi

pkill -f wasserstand_logger.py 2>/dev/null
pkill -f webapp.py 2>/dev/null

echo "🛑 Brunnen-System gestoppt."
