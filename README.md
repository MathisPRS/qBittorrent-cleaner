# Introduction
Ce projet a pour but de compenser un bug de qBittorrent.
Quand on télécharge un torrent avec Sonarr, le torrent reste en place et un hardlink est créé puis déplacé à l’endroit voulu pour laisser le fichier en seed. 
Mais si un upgrade automatique ou manuel remplace ce fichier, Sonarr supprime seulement le hardlink (et le remplace), pas le torrent. 
On se retrouve alors avec des dizaines de torrents dupliqués pour le même épisode ou la même série.

# Arborescance du Projet :

- adapters/ --> methode (API) concernant les services externe au projet (Gotify, qBittorrent, etc)
- api/ --> s'occupe des routes et redirige vers les controllers
- controllers/ --> normalise les données et redirige vers les Services et Repositories
- models/ --> Définis la structure de la base et des items 
- repositories/ --> passe les requetes a la Base
- services/ --> Regroupement de la logique metier


# Setup son projet

## Requirements

- docker installé

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

# Déploiment du projet : 

## Docker

Le docker s'occupe de creer un container à partir du Dockerfile. L'image va normalement installer python3 et les lib nécessaire au projet

Lancer la stack :
- Se mettre a la racine du projet puis effectuer les commandes suivantes
```
docker compose -f docker/docker-compose.yml up -d --build
```

TO DO :
- Fix Cross-seed delete
- Move movie queue in "Discipline"

- 
       
