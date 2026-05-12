#!/bin/sh
set -eu

mkdir -p /app/data /app/uploads
python - <<'PY'
from app import init_db

init_db()
PY

if [ "$#" -eq 2 ] && [ "$1" = "uvicorn" ] && [ "$2" = "app:app" ]; then
  exec uvicorn app:app --host "${HERMES_WEB_HOST:-0.0.0.0}" --port "${HERMES_WEB_PORT:-8000}"
fi

exec "$@"
