#!/bin/bash
# Kubernetes executes this file from ConfigMap data; Git must preserve LF endings.
set -euo pipefail

: "${KAFKA_BOOTSTRAP_SERVERS:?KAFKA_BOOTSTRAP_SERVERS is required}"
cat > /tmp/client.properties <<'PROPERTIES'
request.timeout.ms=10000
default.api.timeout.ms=30000
PROPERTIES
topics="$(/opt/kafka/bin/kafka-topics.sh --bootstrap-server "$KAFKA_BOOTSTRAP_SERVERS" --command-config /tmp/client.properties --list)"

while IFS= read -r topic; do
  grep -Fx -- "$topic" <<<"$topics" >/dev/null || { echo "Required Kafka topic is missing: $topic" >&2; exit 1; }
done <<'TOPICS'
notification_like_topic
notification_comment_topic
analytics_like_topic
analytics_like_topic.DLT
analytics_comment_topic
analytics_comment_topic.DLT
user_ban_topic
user_deactivation_topic
event_start_topic
analytics_user_view_profile_topic
analytics_user_view_profile_topic.DLT
publish_post_topic
public_post_view_topic
TOPICS

echo "Kafka preflight passed; required_topics=13"
