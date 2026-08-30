#!/bin/bash
PG_HOST=${POSTGRES_HOST:-postgres}
PG_PORT=${POSTGRES_PORT:-5432}
PG_USER=${POSTGRES_USER:-user}
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
PG_PASSWORD=$POSTGRES_PASSWORD
TARGET_DB=${POSTGRES_DB:-faang}

echo "Waiting for PostgreSQL at $PG_HOST:$PG_PORT to be ready..."

MAX_RETRIES=30
RETRIES=0

# Try connecting to the default 'postgres' database first to check connectivity
until PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d postgres -c '\q' 2>/dev/null; do
  if [ $RETRIES -eq $MAX_RETRIES ]; then
    echo "PostgreSQL failed to start within the allowed time"
    exit 1
  fi
  echo "PostgreSQL is not ready yet, waiting... (Attempt $((RETRIES+1))/$MAX_RETRIES)"
  sleep 2
  RETRIES=$((RETRIES+1))
done

echo "PostgreSQL is ready!"

# Create the target database if it doesn't exist
echo "Ensuring database '$TARGET_DB' exists..."
PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = '$TARGET_DB'" | grep -q 1 || \
PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d postgres -c "CREATE DATABASE $TARGET_DB;"

echo "Initializing database schemas in '$TARGET_DB' database..."

# Array of services that need schemas
SERVICES=(
  "payment_service"
  "project_service"
  "account_service"
  "user_service"
  "achievement_service"
  "analytics_service"
  "notification_service"
  "post_service"
  "url_shortener_service"
)

# Create schemas in the target database
for SERVICE in "${SERVICES[@]}"; do
  echo "Creating schema: $SERVICE"
  PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $TARGET_DB -c "CREATE SCHEMA IF NOT EXISTS $SERVICE;" 2>&1
  if [ $? -eq 0 ]; then
    echo "✓ Schema $SERVICE created successfully"
  else
    echo "✗ Failed to create schema $SERVICE"
  fi
done

echo ""
echo "Current schemas in $TARGET_DB database:"
PGPASSWORD=$PG_PASSWORD psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $TARGET_DB -c "\dn"

echo ""
echo "PostgreSQL initialization complete!"
