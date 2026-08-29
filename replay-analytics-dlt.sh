#!/bin/bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <analytics-topic>" >&2
  exit 2
fi

TOPIC="$1"
BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}"

case "$TOPIC" in
  analytics_like_topic|analytics_comment_topic|analytics_user_view_profile_topic) ;;
  *) echo "Unsupported analytics topic: $TOPIC" >&2; exit 2 ;;
esac

kafka-console-consumer.sh \
  --bootstrap-server "$BOOTSTRAP_SERVERS" \
  --topic "$TOPIC.DLT" \
  --from-beginning \
  --group "analytics-dlt-replay-$TOPIC-$(date +%s)" \
  --timeout-ms 10000 |
kafka-console-producer.sh \
  --bootstrap-server "$BOOTSTRAP_SERVERS" \
  --topic "$TOPIC"
