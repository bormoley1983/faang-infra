#!/bin/bash
echo "Waiting for Elasticsearch..."
until $(curl --silent --output /dev/null http://elasticsearch:9200); do
  sleep 5
done

if [ "$WAIT_FOR_REDIS" = "true" ]; then
  echo "Waiting for Redis..."
  until $(redis-cli -h redis ping > /dev/null 2>&1); do
    sleep 2
  done
fi

echo "Creating Elasticsearch indexes..."
curl -X PUT "http://elasticsearch:9200/hashtags_index" -H 'Content-Type: application/json' -d '
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