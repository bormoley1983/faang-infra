#!/bin/sh
# Kubernetes executes this file from ConfigMap data; Git must preserve LF endings.
set -eu

: "${REDIS_HOST:?REDIS_HOST is required}"
: "${REDIS_PORT:?REDIS_PORT is required}"

set -- -h "$REDIS_HOST" -p "$REDIS_PORT" --connect-timeout 10 --no-auth-warning
if [ -n "${REDIS_PASSWORD:-}" ]; then
  set -- "$@" -a "$REDIS_PASSWORD"
fi
[ "$(redis-cli "$@" PING)" = "PONG" ] || { echo "Redis PING failed" >&2; exit 1; }
version="$(redis-cli "$@" INFO server | sed -n 's/^redis_version:\(.*\)\r$/\1/p')"
[ -n "$version" ] || { echo "Redis version could not be read" >&2; exit 1; }
echo "Redis preflight passed; version=$version"
