#!/bin/bash
echo "Waiting for Kafka to be ready..."

MAX_RETRIES=20
RETRIES=0

while ! /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list > /dev/null 2>&1; do
  if [ $RETRIES -eq $MAX_RETRIES ]; then
    echo "Kafka failed to start within the allowed time"
    exit 1
  fi
  echo "Kafka is not ready yet, waiting... (Attempt $((RETRIES+1))/$MAX_RETRIES)"
  sleep 5
  RETRIES=$((RETRIES+1))
done

echo "Kafka is ready!"
echo "Initializing Kafka topics..."

echo "Current topics in Kafka:"
/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list | while read topic; do
  echo "- $topic"
done
echo ""

TOPIC_LIST=$(/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list)

# Check and create each topic
for TOPIC_CONFIG in \
  "notification_like_topic:3:1" \
  "notification_comment_topic:2:1" \
  "analytics_like_topic:3:1" \
  "analytics_comment_topic:1:1" \
  "user_ban_topic:1:1" \
  "userViewProfileTopic:3:1" \
  "event_start_topic:3:1"
do
  TOPIC=$(echo $TOPIC_CONFIG | cut -d: -f1)
  PARTITIONS=$(echo $TOPIC_CONFIG | cut -d: -f2)
  REPLICATION=$(echo $TOPIC_CONFIG | cut -d: -f3)

    if echo "$TOPIC_LIST" | grep -q "$TOPIC"; then
      echo "$TOPIC already exists"
    else
      /opt/kafka/bin/kafka-topics.sh --create --topic $TOPIC --bootstrap-server kafka:9092 --partitions $PARTITIONS --replication-factor $REPLICATION
      echo "$TOPIC created"
    fi
  done

echo "Topic creation completed."