#!/bin/sh
set -eu

: "${POSTGRES_HOST:?POSTGRES_HOST is required}"
: "${POSTGRES_PORT:?POSTGRES_PORT is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

export PGPASSWORD="$POSTGRES_PASSWORD"
psql_query() {
  psql -X -v ON_ERROR_STOP=1 -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"
}
capable="$(psql_query -Atqc "SELECT current_setting('server_version_num')::int >= 180000 AND to_regprocedure('uuidv7()') IS NOT NULL")"
[ "$capable" = "t" ] || { echo "PostgreSQL 18 with uuidv7() is required" >&2; exit 1; }

for schema in account_service achievement_service analytics_service post_service project_service url_shortener_service user_service; do
  present="$(psql_query -Atqc "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = '$schema')")"
  [ "$present" = "t" ] || { echo "Required PostgreSQL schema is missing: $schema" >&2; exit 1; }
done

version="$(psql_query -Atqc 'SHOW server_version')"
echo "PostgreSQL preflight passed; version=$version; uuidv7=true; schemas=7"
