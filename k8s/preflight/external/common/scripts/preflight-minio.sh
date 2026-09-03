#!/bin/sh
set -eu

: "${MINIO_URL:?MINIO_URL is required}"
: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY is required}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY is required}"
: "${MINIO_BUCKET_NAME:?MINIO_BUCKET_NAME is required}"
: "${S3_AVATAR_BUCKET_NAME:?S3_AVATAR_BUCKET_NAME is required}"

export MC_CONFIG_DIR=/tmp/mc
mc alias set faang "$MINIO_URL" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
mc ready --quiet faang >/dev/null
mc stat "faang/$MINIO_BUCKET_NAME" >/dev/null
mc stat "faang/$S3_AVATAR_BUCKET_NAME" >/dev/null
echo "MinIO preflight passed; required_buckets=2"
