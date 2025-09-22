# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Paquets de base (certifs TLS + curl pour le healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances Python
COPY requirements.txt .
RUN pip install -r requirements.txt
# (si ton requirements.txt est vide tu peux enlever les 2 lignes ci-dessus)
RUN pip install flask requests

# Code
COPY app.py ./app.py
COPY cleaner ./cleaner

# Crée les dossiers logs + data (cache) dans l'image
RUN mkdir -p /app/logs /app/data && chown -R 10001:10001 /app

# User non-root
RUN useradd -u 10001 -m appuser
USER appuser

# Paramètres runtime (overridables par compose)
ENV CONFIG_FILE=/app/configlocal.cfg
EXPOSE 8124

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8124/ || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "app.py"]
