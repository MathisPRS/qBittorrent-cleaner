Creer un configlocal.cfg

```
[general]
DRY_RUN =
PORT =
LOG_LEVEL =
ONLY_UPGRADES =

[server]
HOST =
PORT =

[logging]
LOG_FILE =
MAX_MB = 
BACKUPS =
WERKZEUG_LEVEL = 

[sonarr]
URL =
API_KEY =

[radarr]
URL =
API_KEY =

[qbittorrent]
HOST =
USER = 
PASS =

[gotify]
ENABLED = 
URL = 
TOKEN = 
PRIORITY = 
TITLE = 
```

Déploiment du projet : 

gdocker compose up -d --build