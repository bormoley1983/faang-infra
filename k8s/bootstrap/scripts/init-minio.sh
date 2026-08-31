#!/bin/sh
set -eu

: "${MINIO_URL:?MINIO_URL is required}"
: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY is required}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY is required}"
: "${MINIO_BUCKET_NAME:?MINIO_BUCKET_NAME is required}"
: "${S3_AVATAR_BUCKET_NAME:?S3_AVATAR_BUCKET_NAME is required}"

attempt=1
until mc alias set faang "$MINIO_URL" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null 2>&1 \
  && mc ready --quiet faang >/dev/null 2>&1; do
  if [ "$attempt" -ge 60 ]; then
    echo "MinIO did not become ready after 60 attempts" >&2
    exit 1
  fi
  echo "Waiting for MinIO ($attempt/60)"
  attempt=$((attempt + 1))
  sleep 5
done

mc mb --ignore-existing "faang/$MINIO_BUCKET_NAME"
mc mb --ignore-existing "faang/$S3_AVATAR_BUCKET_NAME"

echo "MinIO bootstrap contract v1 is satisfied"
