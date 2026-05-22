#!/usr/bin/env bash
# Start ProductionAgent on http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install from https://www.python.org/downloads/"
  exit 1
fi

echo "Installing dependencies..."
python3 -m pip install -q -r requirements.txt

PORT="${PORT:-8000}"
echo ""
echo "Starting server at http://127.0.0.1:${PORT}"
echo "Open that URL in your browser and click \"Run agents\"."
echo "Press Ctrl+C to stop."
echo ""

exec python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port "$PORT"
