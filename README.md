Ce projet a pour but de compenser un bug de qBittorrent.
Quand on télécharge un torrent avec Sonarr, le torrent reste en place et un hardlink est créé puis déplacé à l’endroit voulu pour laisser le fichier en seed. 
Mais si un upgrade automatique ou manuel remplace ce fichier, Sonarr supprime seulement le hardlink (et le remplace), pas le torrent. 
On se retrouve alors avec des dizaines de torrents dupliqués pour le même épisode ou la même série.

Ce repo stocke tout au format JSON : à chaque ajout ou mise à jour de fichier, les informations sont écrites dans un JSON.
Pour utiliser le repos il faut :

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