#!/bin/sh
# Kubernetes executes this file from ConfigMap data; Git must preserve LF endings.
set -eu

: "${REDIS_HOST:?REDIS_HOST is required}"
: "${REDIS_PORT:?REDIS_PORT is required}"

set -- -h "$REDIS_HOST" -p "$REDIS_PORT" -t 10
if [ -n "${REDIS_PASSWORD:-}" ]; then
  REDISCLI_AUTH="$REDIS_PASSWORD"
  export REDISCLI_AUTH
fi

report_ping_failure() {
  case "$1" in
    *NOAUTH*|*WRONGPASS*|*"AUTH failed"*) echo "Redis authentication failed or conflicts with the declared credential policy" >&2 ;;
    *NOPERM*) echo "Redis ACL denied the read-only PING command" >&2 ;;
    *"Could not connect"*|*"Connection refused"*|*"Connection timed out"*|*"Connection reset"*|*"Server closed"*) echo "Redis connection failed through the stable service" >&2 ;;
    *SSL*|*TLS*) echo "Redis TLS negotiation failed or conflicts with the declared TLS policy" >&2 ;;
    *) echo "Redis PING returned an unexpected response" >&2 ;;
  esac
}

if ! ping_output="$(redis-cli "$@" --raw PING 2>&1)"; then
  report_ping_failure "$ping_output"
  exit 1
fi
if [ "$ping_output" != "PONG" ]; then
  report_ping_failure "$ping_output"
  exit 1
fi
if ! info_output="$(redis-cli "$@" --raw INFO server 2>&1)"; then
  echo "Redis INFO failed after PING; verify the read-only ACL permits server metadata" >&2
  exit 1
fi
version="$(printf '%s\n' "$info_output" | sed -n 's/^redis_version:\(.*\)\r$/\1/p')"
[ -n "$version" ] || { echo "Redis version could not be read" >&2; exit 1; }
echo "Redis preflight passed; version=$version"
