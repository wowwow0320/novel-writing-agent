#!/bin/sh
set -e

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"

echo "Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT}..."
i=0
while [ "$i" -lt 60 ]; do
  if python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('${DB_HOST}', ${DB_PORT})); s.close()" 2>/dev/null; then
    echo "PostgreSQL is up."
    break
  fi
  i=$((i + 1))
  sleep 1
done

if [ "$i" -eq 60 ]; then
  echo "Timeout waiting for PostgreSQL."
  exit 1
fi

export ALEMBIC_SYNC_URL="${ALEMBIC_SYNC_URL:-postgresql+psycopg://novel:novel@${DB_HOST}:${DB_PORT}/novel_agent}"

cd /app
alembic upgrade head

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
