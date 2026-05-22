#!/usr/bin/env bash
# Quick diagnostics when the browser shows ERR_EMPTY_RESPONSE on localhost.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
echo "=== ProductionAgent doctor (port ${PORT}) ==="
echo

echo "1. Python"
python3 --version || { echo "FAIL: python3 not found"; exit 1; }

echo
echo "2. Dependencies"
python3 -c "import fastapi, uvicorn, httpx, pydantic" 2>/dev/null && echo "OK" || {
  echo "Installing requirements..."
  python3 -m pip install -q -r requirements.txt
}

echo
echo "3. App import"
python3 -c "from app.main import app; print('OK:', app.title)"

echo
echo "4. Port ${PORT}"
if command -v lsof >/dev/null 2>&1; then
  if lsof -i ":${PORT}" 2>/dev/null | head -5; then
    echo "Something is already on port ${PORT} (see above)."
  else
    echo "Port ${PORT} is free."
  fi
else
  echo "(lsof not available — skip)"
fi

echo
echo "5. .env (optional)"
if [ -f .env ]; then
  echo ".env exists ($(wc -l < .env) lines). If startup hangs, try: mv .env .env.bak"
  grep -E '^[A-Z]' .env 2>/dev/null | sed 's/=.*/=***/' || true
else
  echo "No .env — offline mode (fine)."
fi

echo
echo "6. Start test (5s, no --reload)"
python3 -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" &
PID=$!
sleep 2
if curl -sf "http://127.0.0.1:${PORT}/api/ping" >/dev/null; then
  echo "OK: http://127.0.0.1:${PORT}/api/ping"
  curl -sf "http://127.0.0.1:${PORT}/api/health" && echo
  curl -sf -o /dev/null -w "UI: HTTP %{http_code}\n" "http://127.0.0.1:${PORT}/"
else
  echo "FAIL: server did not respond. Check errors above."
fi
kill "$PID" 2>/dev/null || true
wait "$PID" 2>/dev/null || true

echo
echo "=== To run for real (keep terminal open) ==="
echo "  ./run.sh"
echo "Or:"
echo "  python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"
