# deploy/Dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_WORKDIR=/app \
    APP_UID=${APP_UID} \
    APP_GID=${APP_GID}

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl tini build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR ${APP_WORKDIR}

# Python deps
COPY requirements.txt ${APP_WORKDIR}/requirements.txt
RUN pip install --no-cache-dir -r ${APP_WORKDIR}/requirements.txt

# App
COPY . ${APP_WORKDIR}

# Create directories that will be bind-mounted and ensure perms inside image.
# They will be adjusted at container runtime by start.sh for host bind mounts.
RUN mkdir -p /app/data /app/logs /app/run /app/data/redis \
 && chmod 0777 /app/data /app/logs /app/run /app/data/redis

# create a system group/user with configurable uid/gid (user will not be used directly for ENTRYPOINT)
RUN groupadd -g ${APP_GID} appgroup || true \
 && useradd -u ${APP_UID} -g ${APP_GID} -m -s /bin/bash appuser || true

# copy startup script
COPY deploy/start.sh /usr/local/bin/start.sh
RUN chmod +x /usr/local/bin/start.sh

ENV CONFIG_FILE=/app/configlocal.cfg

EXPOSE 8124

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start.sh"]
# default command (overridable in docker-compose for worker)
CMD ["bash", "-lc", "flask db upgrade && python run.py"]