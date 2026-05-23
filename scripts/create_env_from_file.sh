#!/usr/bin/env bash
# Copy first 30 lines from a source .env into repo-root .env
# Usage: ./scripts/create_env_from_file.sh [source_path]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-$ROOT/.env}"
DEST="$ROOT/.env"

if [[ ! -f "$SRC" ]]; then
  echo "Error: source file not found: $SRC" >&2
  echo "Save your keys to that path first, or pass another path." >&2
  exit 1
fi

head -n 30 "$SRC" > "$DEST"
chmod 600 "$DEST"
echo "Wrote $(wc -l < "$DEST") lines to $DEST"
