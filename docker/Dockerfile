# syntax=docker/dockerfile:1
FROM python:3.12-slim

# comportement python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# paquets de base utiles (tini pour PID 1 propre)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl tini build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copier seulement requirements d'abord pour profiter du cache Docker
COPY requirements.txt /app/requirements.txt

# Installer deps (échouer si pip fail)
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copier tout le code (dev: on monte le volume, en prod on build l'image)
COPY . /app

RUN mkdir -p /app/logs /app/data \
    && chown -R 10001:10001 /app

RUN useradd -u 10001 -m appuser || true
USER appuser

ENV CONFIG_FILE=/app/configlocal.cfg

EXPOSE 8124

# Healthcheck basique (ajuste l'URL si ton app expose autre endpoint/port)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8124/ || exit 1



ENTRYPOINT ["/usr/bin/tini", "--"]
# Commande par défaut : lance le run.py (change si ton fichier s'appelle différemment)
CMD ["bash", "-lc", "flask db upgrade && python run.py"]