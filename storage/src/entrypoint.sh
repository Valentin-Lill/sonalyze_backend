#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="/app/src"

RUN_MIGRATIONS_VALUE="${RUN_MIGRATIONS:-true}"

if [[ "$RUN_MIGRATIONS_VALUE" == "true" || "$RUN_MIGRATIONS_VALUE" == "1" ]]; then
  echo "[storage] running migrations..."
  alembic -c /app/src/alembic.ini upgrade head
fi

echo "[storage] starting api..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
