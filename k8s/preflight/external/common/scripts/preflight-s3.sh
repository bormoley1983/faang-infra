#!/bin/sh
# Kubernetes executes this file from ConfigMap data; Git must preserve LF endings.
set -eu

: "${S3_ENDPOINT:?S3_ENDPOINT is required}"
: "${S3_ACCESS_KEY:?S3_ACCESS_KEY is required}"
: "${S3_SECRET_KEY:?S3_SECRET_KEY is required}"
: "${S3_BUCKET_NAME:?S3_BUCKET_NAME is required}"
: "${S3_AVATAR_BUCKET_NAME:?S3_AVATAR_BUCKET_NAME is required}"

aws configure set aws_access_key_id "$S3_ACCESS_KEY"
aws configure set aws_secret_access_key "$S3_SECRET_KEY"
aws configure set region us-east-1

aws --endpoint-url "$S3_ENDPOINT" s3api list-buckets >/dev/null 2>&1 || {
  echo "S3 endpoint is not reachable at $S3_ENDPOINT" >&2
  exit 1
}
aws --endpoint-url "$S3_ENDPOINT" s3api head-bucket --bucket "$S3_BUCKET_NAME" >/dev/null 2>&1 || {
  echo "Required bucket '$S3_BUCKET_NAME' is missing" >&2
  exit 1
}
aws --endpoint-url "$S3_ENDPOINT" s3api head-bucket --bucket "$S3_AVATAR_BUCKET_NAME" >/dev/null 2>&1 || {
  echo "Required avatar bucket '$S3_AVATAR_BUCKET_NAME' is missing" >&2
  exit 1
}
echo "S3 preflight passed; required_buckets=2"
