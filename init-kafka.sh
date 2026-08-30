#!/bin/bash
# Default values if environment variables are not set
KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}

# Determine kafka-topics.sh location
if [ -x "/opt/kafka/bin/kafka-topics.sh" ]; then
  KAFKA_TOPICS_CMD="/opt/kafka/bin/kafka-topics.sh"
elif [ -x "/bin/kafka-topics.sh" ]; then
  KAFKA_TOPICS_CMD="/bin/kafka-topics.sh"
else
  # Fallback to finding it in PATH
  KAFKA_TOPICS_CMD="kafka-topics.sh"
fi

echo "Waiting for Kafka at $KAFKA_BOOTSTRAP_SERVERS to be ready..."

MAX_RETRIES=20
RETRIES=0

while ! $KAFKA_TOPICS_CMD --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS --list > /dev/null 2>&1; do
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
$KAFKA_TOPICS_CMD --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS --list | while read topic; do
  echo "- $topic"
done
echo ""

TOPIC_LIST=$($KAFKA_TOPICS_CMD --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS --list)

# Check and create each topic
for TOPIC_CONFIG in \
  "notification_like_topic:3:1" \
  "notification_comment_topic:2:1" \
  "analytics_like_topic:3:1" \
  "analytics_like_topic.DLT:3:1" \
  "analytics_comment_topic:1:1" \
  "analytics_comment_topic.DLT:1:1" \
  "user_ban_topic:1:1" \
  "user_deactivation_topic:1:1" \
  "userViewProfileTopic:3:1" \
  "event_start_topic:1:1" \
  "analytics_user_view_profile_topic:1:1" \
  "analytics_user_view_profile_topic.DLT:1:1" \
  "publish_post_topic:1:1"
do
  TOPIC=$(echo $TOPIC_CONFIG | cut -d: -f1)
  PARTITIONS=$(echo $TOPIC_CONFIG | cut -d: -f2)
  REPLICATION=$(echo $TOPIC_CONFIG | cut -d: -f3)

    if echo "$TOPIC_LIST" | grep -q "$TOPIC"; then
      echo "$TOPIC already exists"
    else
      $KAFKA_TOPICS_CMD --create --topic $TOPIC --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS --partitions $PARTITIONS --replication-factor $REPLICATION
      echo "$TOPIC created"
    fi
  done

echo "Topic creation completed."
