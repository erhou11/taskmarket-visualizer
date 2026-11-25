#!/bin/bash
# One-click deploy for the Taskmarket visualizer (static, scheduled build).
# Target: hk-node-02, served at https://952121.xyz/taskmarket/
# Only ADDS files: /opt/taskmarket-viz/ (generator) and
# /opt/quizapp/www/taskmarket/ (generated static output, a new subdir of the
# existing 952121.xyz web root). It never edits nginx or any quiz-app file.
set -e
SRC_DIR=/opt/taskmarket-viz
OUT_DIR=/opt/quizapp/www/taskmarket

mkdir -p "$SRC_DIR" "$OUT_DIR"
SELF="$(cd "$(dirname "$0")" && pwd)/generate.py"
[ "$SELF" != "$SRC_DIR/generate.py" ] && cp "$SELF" "$SRC_DIR/generate.py" || true

# Isolated venv just for Pillow (og.png). The generator works without it too.
if [ ! -x "$SRC_DIR/venv/bin/python3" ]; then
  python3 -m venv "$SRC_DIR/venv" || true
  "$SRC_DIR/venv/bin/pip" install --quiet pillow || true
fi
PY="$SRC_DIR/venv/bin/python3"
[ -x "$PY" ] || PY=python3

# First generation
"$PY" "$SRC_DIR/generate.py" "$OUT_DIR"
chmod 755 "$OUT_DIR"
find "$OUT_DIR" -type f -exec chmod 644 {} +

# Cron: regenerate every 15 minutes (requirement: at least hourly)
( crontab -l 2>/dev/null | grep -v 'taskmarket-viz/generate.py' || true
  echo "*/15 * * * * $PY $SRC_DIR/generate.py $OUT_DIR >> /var/log/taskmarket-viz.log 2>&1"
) | crontab -

echo "Deployed. Live at https://952121.xyz/taskmarket/"
