#!/usr/bin/env bash
# Phase 8: curl a full scheduling chat conversation (requires API + .env).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${PORT:-8010}"
BASE_URL="${BASE_URL:-http://127.0.0.1:$PORT}"

if ! curl -sf "$BASE_URL/health" >/dev/null 2>&1; then
  echo "Starting uvicorn on :$PORT..."
  (cd "$ROOT/backend" && PYTHONPATH=. python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT") &
  UV_PID=$!
  trap 'kill $UV_PID 2>/dev/null || true' EXIT
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    curl -sf "$BASE_URL/health" >/dev/null 2>&1 && break
    sleep 1
  done
fi

echo "== Create session =="
SESSION=$(curl -sf -X POST "$BASE_URL/chat/sessions" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Curl scheduling test"}')
SESSION_ID=$(echo "$SESSION" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "session_id=$SESSION_ID"

echo "== Stream message (scheduling) =="
OUT=$(mktemp)
curl -sf -N -X POST "$BASE_URL/chat/sessions/$SESSION_ID/messages" \
  -H 'Content-Type: application/json' \
  -d '{"content":"Schedule next week'\''s jobs for all pending work.","use_orchestrator_agent":false}' \
  | tee "$OUT"

RUN_ID=$(grep -E '^data:' "$OUT" | grep schedule_preview | tail -1 | python3 -c "
import sys, json
for line in sys.stdin:
    if line.startswith('data:'):
        d = json.loads(line[5:].strip())
        if d.get('schedule_run_id'):
            print(d['schedule_run_id'])
            break
" || true)

echo "== Messages in API =="
curl -sf "$BASE_URL/chat/sessions/$SESSION_ID/messages" | python3 -m json.tool | head -40

if [ -n "${RUN_ID:-}" ]; then
  echo "== Approve schedule $RUN_ID =="
  curl -sf -X POST "$BASE_URL/schedules/$RUN_ID/approve" | python3 -m json.tool
fi

echo "Done. Verify chat_messages in Supabase for session_id=$SESSION_ID"
