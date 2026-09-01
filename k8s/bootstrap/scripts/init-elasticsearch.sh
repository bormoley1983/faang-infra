#!/bin/sh
set -eu

: "${ELASTICSEARCH_URL:?ELASTICSEARCH_URL is required}"
: "${ELASTICSEARCH_TLS_INSECURE:?ELASTICSEARCH_TLS_INSECURE is required}"
: "${ELASTICSEARCH_USERNAME:?ELASTICSEARCH_USERNAME is required}"
: "${ELASTICSEARCH_PASSWORD:?ELASTICSEARCH_PASSWORD is required}"
index_name=hashtags_index

set -- --fail --silent --show-error --user "$ELASTICSEARCH_USERNAME:$ELASTICSEARCH_PASSWORD"
case "$ELASTICSEARCH_TLS_INSECURE" in
  true) set -- "$@" --insecure ;;
  false) ;;
  *) echo "ELASTICSEARCH_TLS_INSECURE must be true or false" >&2; exit 2 ;;
esac

attempt=1
until curl "$@" "$ELASTICSEARCH_URL" >/dev/null; do
  if [ "$attempt" -ge 60 ]; then
    echo "Elasticsearch did not become ready after 60 attempts" >&2
    exit 1
  fi
  echo "Waiting for Elasticsearch ($attempt/60)"
  attempt=$((attempt + 1))
  sleep 5
done

if curl "$@" --head "$ELASTICSEARCH_URL/$index_name" >/dev/null; then
  echo "Elasticsearch index $index_name already exists"
else
  curl "$@" \
    --request PUT "$ELASTICSEARCH_URL/$index_name" \
    --header 'Content-Type: application/json' \
    --data '{
      "settings": {"number_of_shards": 5, "number_of_replicas": 1},
      "mappings": {"properties": {
        "post_id": {"type": "keyword"},
        "hashtags": {"type": "keyword"},
        "content": {"type": "text"},
        "created_at": {"type": "date"}
      }}
    }'
fi

echo "Elasticsearch bootstrap contract v1 is satisfied"
