# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Paquets de base
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances Python
COPY requirements.txt .
RUN pip install -r requirements.txt || true
# fallback si requirements.txt est vide
RUN pip install flask requests

# Code source
COPY app.py ./app.py
COPY cleaner ./cleaner
COPY tools ./tools

# Préparer répertoires persistants
RUN mkdir -p /app/logs /app/data && \
    chown -R 10001:10001 /app

# Utilisateur non-root
RUN useradd -u 10001 -m appuser
USER appuser

# Config & volumes
ENV CONFIG_FILE=/app/configlocal.cfg
VOLUME ["/app/logs", "/app/data"]

EXPOSE 8124

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8124/ || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py"]
