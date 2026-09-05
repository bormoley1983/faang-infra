#!/bin/sh
set -eu

: "${S3_ENDPOINT:?S3_ENDPOINT is required}"
: "${S3_ACCESS_KEY:?S3_ACCESS_KEY is required}"
: "${S3_SECRET_KEY:?S3_SECRET_KEY is required}"
: "${S3_BUCKET_NAME:?S3_BUCKET_NAME is required}"
: "${S3_AVATAR_BUCKET_NAME:?S3_AVATAR_BUCKET_NAME is required}"

aws configure set aws_access_key_id "$S3_ACCESS_KEY"
aws configure set aws_secret_access_key "$S3_SECRET_KEY"
aws configure set region us-east-1

attempt=1
until aws --endpoint-url "$S3_ENDPOINT" s3api list-buckets >/dev/null 2>&1; do
  if [ "$attempt" -ge 60 ]; then
    echo "S3 endpoint did not become ready after 60 attempts" >&2
    exit 1
  fi
  echo "Waiting for S3 endpoint ($attempt/60)"
  attempt=$((attempt + 1))
  sleep 5
done

aws --endpoint-url "$S3_ENDPOINT" s3api head-bucket --bucket "$S3_BUCKET_NAME" 2>/dev/null || \
  aws --endpoint-url "$S3_ENDPOINT" s3 mb "s3://$S3_BUCKET_NAME"
aws --endpoint-url "$S3_ENDPOINT" s3api head-bucket --bucket "$S3_AVATAR_BUCKET_NAME" 2>/dev/null || \
  aws --endpoint-url "$S3_ENDPOINT" s3 mb "s3://$S3_AVATAR_BUCKET_NAME"

echo "S3 bootstrap contract v1 is satisfied"
