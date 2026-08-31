#!/bin/sh
set -eu

: "${POSTGRES_HOST:?POSTGRES_HOST is required}"
: "${POSTGRES_PORT:?POSTGRES_PORT is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

case "$POSTGRES_DB" in
  ''|*[!A-Za-z0-9_]*) echo "POSTGRES_DB must be a simple SQL identifier" >&2; exit 2 ;;
esac

export PGPASSWORD="$POSTGRES_PASSWORD"
attempt=1
until psql -v ON_ERROR_STOP=1 -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -c '\q' >/dev/null 2>&1; do
  if [ "$attempt" -ge 60 ]; then
    echo "PostgreSQL did not become ready after 60 attempts" >&2
    exit 1
  fi
  echo "Waiting for PostgreSQL ($attempt/60)"
  attempt=$((attempt + 1))
  sleep 5
done

exists="$(psql -v ON_ERROR_STOP=1 -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -Atqc "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'")"
if [ "$exists" != "1" ]; then
  psql -v ON_ERROR_STOP=1 -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE \"$POSTGRES_DB\""
fi

for schema in account_service achievement_service analytics_service post_service project_service url_shortener_service user_service; do
  psql -v ON_ERROR_STOP=1 -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE SCHEMA IF NOT EXISTS \"$schema\""
done

echo "PostgreSQL bootstrap contract v1 is satisfied"
