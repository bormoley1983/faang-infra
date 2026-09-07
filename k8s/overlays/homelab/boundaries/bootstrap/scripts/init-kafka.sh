#!/bin/bash
set -euo pipefail

: "${KAFKA_BOOTSTRAP_SERVERS:?KAFKA_BOOTSTRAP_SERVERS is required}"
KAFKA_TOPICS_CMD=/opt/kafka/bin/kafka-topics.sh

attempt=1
until "$KAFKA_TOPICS_CMD" --bootstrap-server "$KAFKA_BOOTSTRAP_SERVERS" --list >/dev/null 2>&1; do
  if [ "$attempt" -ge 60 ]; then
    echo "Kafka did not become ready after 60 attempts" >&2
    exit 1
  fi
  echo "Waiting for Kafka ($attempt/60)"
  attempt=$((attempt + 1))
  sleep 5
done

while IFS=: read -r topic partitions replication; do
  "$KAFKA_TOPICS_CMD" \
    --bootstrap-server "$KAFKA_BOOTSTRAP_SERVERS" \
    --create \
    --if-not-exists \
    --topic "$topic" \
    --partitions "$partitions" \
    --replication-factor "$replication"
done <<'TOPICS'
notification_like_topic:3:1
notification_comment_topic:2:1
analytics_like_topic:3:1
analytics_like_topic.DLT:3:1
analytics_comment_topic:1:1
analytics_comment_topic.DLT:1:1
user_ban_topic:1:1
user_deactivation_topic:1:1
event_start_topic:1:1
analytics_user_view_profile_topic:1:1
analytics_user_view_profile_topic.DLT:1:1
publish_post_topic:1:1
public_post_view_topic:1:1
TOPICS

echo "Kafka bootstrap contract v1 is satisfied"
