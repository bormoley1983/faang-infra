#!/bin/bash
# Default values if environment variables are not set
ELASTICSEARCH_URL=${ELASTICSEARCH_URL:-http://elasticsearch:9200}

echo "Waiting for Elasticsearch at $ELASTICSEARCH_URL..."
until $(curl --silent --output /dev/null $ELASTICSEARCH_URL); do
  sleep 5
done

if [ "$WAIT_FOR_REDIS" = "true" ]; then
  REDIS_HOST=${REDIS_HOST:-redis}
  echo "Waiting for Redis at $REDIS_HOST..."
  until $(redis-cli -h $REDIS_HOST ping > /dev/null 2>&1); do
    sleep 2
  done
fi

echo "Creating Elasticsearch indexes..."
curl -X PUT "$ELASTICSEARCH_URL/hashtags_index" -H 'Content-Type: application/json' -d '
{
  "settings": {
    "number_of_shards": 5,
    "number_of_replicas": 1
  },
  "mappings": {
    "properties": {
      "post_id": {"type": "keyword"},
      "hashtags": {"type": "keyword"},
      "content": {"type": "text"},
      "created_at": {"type": "date"}
    }
  }
}'