# qBittorrent Cleaner

Webhook receiver qui garantit l'absence de doublons de torrents sur un NAS géré par Sonarr / Radarr + qBittorrent.

## Contexte

Lorsque Sonarr ou Radarr upgrade un fichier média, il :
1. télécharge la nouvelle version → crée un hardlink dans `/media`
2. supprime l'ancien hardlink de `/media`

L'ancien torrent continue de seeder dans `/downloads` sans que qBittorrent ou les *arr le suppriment.
On se retrouve avec plusieurs torrents pour le même film ou le même épisode.

Ce service intercepte les webhooks `on_import` de Sonarr/Radarr, maintient en base le `latest_torrent` par film/épisode, et supprime automatiquement les anciens torrents — immédiatement ou après un délai de seeding configurable.

---

## Architecture

```
app/
├── adapters/       Clients HTTP vers les services externes (qBittorrent, Sonarr, Radarr, Gotify)
├── api/            Définition des routes Flask
├── controllers/    Normalisation des payloads entrants, délégation vers services/repositories
├── models/         Modèles SQLAlchemy (Torrents, Movies, Series, Episodes, DeferredDeletions)
├── repositories/   Accès base de données (requêtes SQLAlchemy)
├── services/       Logique métier
│   ├── arr_queue_service.py            Récupère les hashes gérés par les queues Radarr/Sonarr
│   ├── commun_services.py              Suppression qBittorrent + BDD, notifications Gotify
│   ├── deferred_deletions_services.py  Gestion des suppressions différées (delta seeding)
│   ├── hardlink_audit_service.py       Détecte les torrents orphelins (st_nlink == 1)
│   ├── radarr_services.py              Import de films
│   ├── scheduler_services.py           Planification Celery
│   ├── sonarr_services.py              Import d'épisodes
│   └── torrents_resolver_services.py   Résolution torrent → Sonarr/Radarr via guessit
└── tasks/
    └── detect_unpublish_torrents.py    Audit quotidien (2 phases, voir ci-dessous)
```

---

## Fonctionnement

### Webhooks (temps réel)

| Endpoint            | Source          | Déclencheur       |
|---------------------|-----------------|-------------------|
| `POST /api/radarr`  | Radarr          | `on_import`       |
| `POST /api/sonarr`  | Sonarr          | `on_import`       |
| `POST /api/torrent` | cross-seed tool | import cross-seed |

À chaque import, le service :
1. Crée ou met à jour l'entrée `Movie` / `Episode` en BDD avec le nouveau hash
2. Collecte l'ancien hash (+ ses cross-seeds éventuels)
3. Supprime l'ancien torrent immédiatement si le delta de seeding est atteint, sinon planifie la suppression via Celery

### Audit quotidien — 2 phases

Lancé automatiquement via Celery Beat (20h00 UTC) **uniquement si `AUDIT_ENABLED = True`** dans `configlocal.cfg`.

**Phase 1 — Synchronisation BDD**
Compare chaque torrent de qBittorrent avec la BDD locale.
Les torrents absents de la BDD (webhook raté) sont résolus via Sonarr/Radarr et ingérés.
> Guard : les torrents présents dans la queue Radarr/Sonarr (ex. en attente d'un import manuel) sont exclus même s'ils ne sont pas en BDD.

**Phase 2 — Détection des orphelins (hardlinks)**
Pour chaque torrent en seeding, vérifie le `st_nlink` de ses fichiers.
Un fichier avec `st_nlink == 1` n'est plus hardlinké vers `/media` : Radarr/Sonarr l'a déjà remplacé.
Les torrents entièrement orphelins sont routés vers le pipeline de suppression différée standard.
> Guard : même exclusion que Phase 1 — les torrents en queue arr sont ignorés.

---

## Configuration

Créer un fichier `configlocal.cfg` à la racine du projet :

```ini
[general]
LOG_LEVEL = INFO               # DEBUG | INFO | WARNING | ERROR

[server]
HOST = 0.0.0.0
PORT = 8124

[logging]
LOG_FILE = /app/logs/webhook-cleaner.log
MAX_MB   = 20
BACKUPS  = 7
WERKZEUG_LEVEL = WARNING

[qbittorrent]
HOST                    = http://qbittorrent:8080
USER                    = admin
PASS                    = password
DEFFERED_DELETION_DELTA = 24   # heures de seeding minimum avant suppression différée

[sonarr]
URL     = http://sonarr:8989
API_KEY = <votre_clé>

[radarr]
URL     = http://radarr:7878
API_KEY = <votre_clé>

[redis]
URL                   = redis://redis:6379/0
CELERY_BROKER_URL     = redis://redis:6379/0
CELERY_RESULT_BACKEND = redis://redis:6379/1

[celery]
# Active le cron quotidien d'audit (Phase 1 + Phase 2 hardlinks)
# False = le cron ne se déclenche jamais automatiquement
# Les appels manuels CLI fonctionnent toujours quelle que soit cette valeur
AUDIT_ENABLED = False

[gotify]
ENABLED    = true
URL        = http://gotify:80
TOKEN      = <votre_token>
PRIORITY   = 5
TITLE      = Cleaner qBittorrent
VERIFY_SSL = true

[database]
URL  = sqlite:///data/app.db   # ou postgresql://user:pass@host/db
ECHO = false
```

---

## Déploiement

### Prérequis

- Docker + Docker Compose
- Réseau Docker `media_net` existant (partagé avec Sonarr, Radarr, qBittorrent)
- Le container doit avoir accès en lecture au volume `/downloads` pour l'audit hardlink (Phase 2)

### Lancer la stack

```bash
# depuis la racine du projet
docker compose -f deploy/docker-compose.yml up -d --build
```

La stack démarre 4 containers :

| Container                | Rôle                                           |
|--------------------------|------------------------------------------------|
| `webhook-cleaner`        | API Flask — reçoit les webhooks                |
| `webhook-cleaner-worker` | Celery worker — exécute les tâches asynchrones |
| `webhook-cleaner-beat`   | Celery beat — planifie l'audit quotidien        |
| `webhook-cleaner-redis`  | Broker Redis                                   |

### Variables d'environnement (optionnelles)

```bash
APP_UID=1000   # UID du processus dans le container (défaut : 1000)
APP_GID=1000   # GID du processus dans le container (défaut : 1000)
```

Créer un `.env` à la racine si nécessaire :

```env
APP_UID=1000
APP_GID=1000
```

---

## Configuration des webhooks

### Radarr

`Settings → Connect → + Webhook`

| Champ    | Valeur                                    |
|----------|-------------------------------------------|
| URL      | `http://webhook-cleaner:8124/api/radarr`  |
| Triggers | **On Import** uniquement                  |

### Sonarr

`Settings → Connect → + Webhook`

| Champ    | Valeur                                    |
|----------|-------------------------------------------|
| URL      | `http://webhook-cleaner:8124/api/sonarr`  |
| Triggers | **On Import** uniquement                  |

---

## Audit manuel (CLI)

Toutes les commandes ci-dessous fonctionnent **indépendamment de `AUDIT_ENABLED`** dans la config.

### Audit complet (Phase 1 + Phase 2)

```bash
# Simulation : résout et logge sans rien écrire ni supprimer
docker exec webhook-cleaner python -m app.tasks.detect_unpublish_torrents --dry-run

# Exécution réelle
docker exec webhook-cleaner python -m app.tasks.detect_unpublish_torrents
```

### Audit hardlinks uniquement (Phase 2 seule)

Affiche la liste des torrents dont les fichiers ont `st_nlink == 1` (plus de hardlink vers `/media`) **sans rien supprimer ni modifier la BDD**. Utile pour vérifier ce que le cron aurait nettoyé.

```bash
docker exec webhook-cleaner python -m app.tasks.detect_unpublish_torrents --hardlink-only
```

Exemple de sortie :

```
[Phase2] ===== ORPHANED TORRENTS (no hardlink to /media) =====
[Phase2]  [1/3] hash=abc123...  name=The.Movie.2024.2160p...  category=films  state=seeding  size=52.10 GB  path=/downloads/films/...
[Phase2]  [2/3] hash=def456...  name=Serie.S02E05.1080p...    category=series state=seeding  size=3.20 GB   path=/downloads/series/...
[Phase2]  [3/3] ...
[Phase2] ===== END OF ORPHANED TORRENTS LIST =====
```

### Récapitulatif des options CLI

| Commande                          | Phase 1 (DB sync) | Phase 2 (hardlinks) | Suppression |
|-----------------------------------|:-----------------:|:-------------------:|:-----------:|
| *(aucune option)*                 | oui               | oui                 | oui         |
| `--dry-run`                       | oui (simulation)  | oui (simulation)    | non         |
| `--hardlink-only`                 | non               | oui (simulation)    | non         |

### Activation du cron automatique

Par défaut `AUDIT_ENABLED = False` — le cron ne tourne jamais.
Pour l'activer, éditer `configlocal.cfg` :

```ini
[celery]
AUDIT_ENABLED = True
```

Puis redémarrer le container Celery Beat :

```bash
docker compose -f deploy/docker-compose.yml restart webhook-cleaner-beat
```
