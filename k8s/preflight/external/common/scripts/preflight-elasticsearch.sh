#!/bin/sh
set -eu

: "${ELASTICSEARCH_URL:?ELASTICSEARCH_URL is required}"
: "${ELASTICSEARCH_TLS_INSECURE:?ELASTICSEARCH_TLS_INSECURE is required}"
: "${ELASTICSEARCH_USERNAME:?ELASTICSEARCH_USERNAME is required}"
: "${ELASTICSEARCH_PASSWORD:?ELASTICSEARCH_PASSWORD is required}"

set -- --fail --silent --show-error --connect-timeout 10 --max-time 30 --user "$ELASTICSEARCH_USERNAME:$ELASTICSEARCH_PASSWORD"
case "$ELASTICSEARCH_TLS_INSECURE" in
  true) set -- "$@" --insecure ;;
  false) ;;
  *) echo "ELASTICSEARCH_TLS_INSECURE must be true or false" >&2; exit 2 ;;
esac

curl "$@" "$ELASTICSEARCH_URL" --output /tmp/elasticsearch-root.json
version="$(sed -n 's/.*"number"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /tmp/elasticsearch-root.json | head -n 1)"
[ -n "$version" ] || { echo "Elasticsearch version could not be read" >&2; exit 1; }
curl "$@" --head "$ELASTICSEARCH_URL/hashtags_index" >/dev/null
echo "Elasticsearch preflight passed; version=$version; index=hashtags_index"
