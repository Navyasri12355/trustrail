#!/usr/bin/env bash
# Dump or restore the TrustRail database into backups/.
# Usage (from repo root):
#   bash scripts/backup_db.sh
#   bash scripts/backup_db.sh --restore backups/trustrail_YYYYMMDD_HHMMSS.sql

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p backups

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PGUSER="${POSTGRES_USER:-trustrail}"
PGDB="${POSTGRES_DB:-trustrail}"

docker_up() {
  docker compose ps --status running db >/dev/null 2>&1
}

if [ "${1:-}" = "--restore" ]; then
  FILE="${2:?Usage: backup_db.sh --restore <file>}"
  if docker_up; then
    echo "Restoring $FILE into Postgres (docker compose db)..."
    docker compose exec -T db psql -U "$PGUSER" -d "$PGDB" < "$FILE"
    echo "Restore complete."
    exit 0
  fi
  cp "$FILE" "$ROOT/trustrail.db"
  echo "Restored SQLite file to $ROOT/trustrail.db"
  exit 0
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
if docker_up; then
  OUT="backups/trustrail_${STAMP}.sql"
  echo "Dumping Postgres to $OUT ..."
  docker compose exec -T db pg_dump -U "$PGUSER" "$PGDB" > "$OUT"
  echo "Wrote $OUT"
  exit 0
fi

if [ -f trustrail.db ]; then
  OUT="backups/trustrail_${STAMP}.db"
  cp trustrail.db "$OUT"
  echo "Copied SQLite DB to $OUT"
  exit 0
fi

echo "No running Compose Postgres service and no trustrail.db found." >&2
exit 1
