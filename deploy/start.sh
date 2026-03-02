#!/usr/bin/env bash
set -euo pipefail

# If APP_UID/APP_GID are set (via env / docker-compose .env), keep them.
# Otherwise fallback to the container's current user ids.
: "${APP_UID:=$(id -u)}"
: "${APP_GID:=$(id -g)}"

export APP_UID APP_GID

mkdir -p /app/data /app/logs /app/run /app/data/redis

chown -R "${APP_UID}:${APP_GID}" /app/data /app/logs /app/run /app/data/redis || true
chmod -R 0755 /app /app/data /app/logs /app/run /app/data/redis || true

touch /app/data/celerybeat-schedule || true
chown "${APP_UID}:${APP_GID}" /app/data/celerybeat-schedule || true
chmod 0644 /app/data/celerybeat-schedule || true

exec "$@"