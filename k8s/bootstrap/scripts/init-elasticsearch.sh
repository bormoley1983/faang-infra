#!/bin/sh
set -eu

: "${ELASTICSEARCH_URL:?ELASTICSEARCH_URL is required}"
index_name=hashtags_index

attempt=1
until curl --fail --silent --show-error "$ELASTICSEARCH_URL" >/dev/null; do
  if [ "$attempt" -ge 60 ]; then
    echo "Elasticsearch did not become ready after 60 attempts" >&2
    exit 1
  fi
  echo "Waiting for Elasticsearch ($attempt/60)"
  attempt=$((attempt + 1))
  sleep 5
done

if curl --fail --silent --head "$ELASTICSEARCH_URL/$index_name" >/dev/null; then
  echo "Elasticsearch index $index_name already exists"
else
  curl --fail --silent --show-error \
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
