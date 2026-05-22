#!/usr/bin/env bash
# Start ProductionAgent on http://127.0.0.1:3000 (override with PORT=...)
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install from https://www.python.org/downloads/"
  exit 1
fi

echo "Installing dependencies..."
python3 -m pip install -q -r requirements.txt

PORT="${PORT:-3000}"

# Stop a stale uvicorn on this port (common cause of 404 on /api/qa/*).
if command -v lsof >/dev/null 2>&1; then
  OLD_PIDS="$(lsof -ti ":${PORT}" 2>/dev/null || true)"
  if [ -n "${OLD_PIDS}" ]; then
    echo "Stopping existing process on port ${PORT} (reload latest code)..."
    kill ${OLD_PIDS} 2>/dev/null || true
    sleep 1
  fi
fi

echo ""
echo "Starting server at http://127.0.0.1:${PORT}"
echo "Open that URL in your browser and click \"Run agents\"."
echo "Press Ctrl+C to stop."
echo ""

# --reload can cause flaky ERR_EMPTY_RESPONSE on some Windows setups.
# Use RELOAD=1 ./run.sh to enable it.
EXTRA=""
if [ "${RELOAD:-0}" = "1" ]; then
  EXTRA="--reload"
fi

# 0.0.0.0 so Cursor port-forwarding (e.g. local port → remote :3000) works.
exec python3 -m uvicorn app.main:app $EXTRA --host 0.0.0.0 --port "$PORT"
