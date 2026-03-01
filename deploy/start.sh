#!/usr/bin/env bash
# deploy/start.sh
set -euo pipefail

APP_UID=153192260
APP_GID=153192260

# Ensure necessary directories exist (host bind mount may create them with wrong perms)
mkdir -p /app/data /app/logs /app/run /app/data/redis

# If directories are bind-mounted from host, chown them to target UID/GID (start.sh runs as root)
# This makes it painless: no manual chown on host required.
chown -R "${APP_UID}:${APP_GID}" /app/data /app/logs /app/run /app/data/redis || true
chmod -R 0755 /app /app/data /app/logs /app/run /app/data/redis || true

# Ensure celerybeat schedule file exists and has proper ownership/perm
touch /app/data/celerybeat-schedule || true
chown "${APP_UID}:${APP_GID}" /app/data/celerybeat-schedule || true
chmod 0644 /app/data/celerybeat-schedule || true

# If an argument/command is supplied (via CMD or docker-compose), execute it.
exec "$@"