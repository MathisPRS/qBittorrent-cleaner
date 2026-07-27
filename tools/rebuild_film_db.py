#!/usr/bin/env python3
"""
rebuild_film_db.py — reconstruit la partie FILMS de la BDD webhook-cleaner depuis
la vérité terrain (qBittorrent + inodes /media + Radarr). Séries/animes intacts.

Vérité :
  - torrents films = catégories qBit {films, films.cross}
  - association film = inode du fichier torrent == inode d'un movieFile Radarr
  - groupe cross-seed = torrents partageant le MÊME inode (hardlink)
  - parent = le torrent catégorie 'films' du groupe (sinon le 1er) ; enfants = 'films.cross'

Reconstruit, dans le périmètre FILMS uniquement :
  - torrents (insert des hashes films vivants manquants ; noms/indexer conservés/complétés)
  - cross_seed_id (parent=NULL, enfants→parent.id)
  - movies.latest_torrent_id → torrent parent (upsert par radarr_id)
  - purge des lignes FILMS fantômes (référencées par un movie mais absentes de qBit)

--dry-run (défaut) : n'écrit rien, imprime le plan.  --apply : exécute en transaction.
Backup manuel de data/app.db recommandé avant --apply.
"""
import os, sys, json, sqlite3, argparse
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "app.db")
NAS_CONT, NAS_HOST = "/nas-omv", os.getenv("NAS_HOST", "/mnt/nas/Media")
# fichiers d'entrée (JSON qBit + Radarr) passés en args pour tourner hors conteneur
def host(p): return p.replace(NAS_CONT, NAS_HOST, 1)


def build_truth(qb, movies):
    radarr_ino = {}
    for m in movies:
        if not m.get("hasFile"): continue
        p = host((m.get("movieFile") or {}).get("path", ""))
        try: radarr_ino[os.stat(p).st_ino] = m
        except OSError: pass
    film_torr = [t for t in qb if (t.get("category") or "") in ("films", "films.cross")]
    groups = defaultdict(list)
    for t in film_torr:
        p = host(t.get("content_path", ""))
        try:
            if os.path.isfile(p): groups[os.stat(p).st_ino].append(t)
        except OSError: pass
    # groupes mappés à un film Radarr → structure {radarr_id: {movie, parent, children[]}}
    plan = {}
    for ino, ts in groups.items():
        m = radarr_ino.get(ino)
        if not m: continue
        parents = [t for t in ts if t.get("category") == "films"]
        parent = parents[0] if parents else ts[0]
        children = [t for t in ts if t["hash"].lower() != parent["hash"].lower()]
        plan[str(m["id"])] = {"title": m.get("title"), "parent": parent, "children": children}
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qb", required=True); ap.add_argument("--movies", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    qb = json.load(open(a.qb)); movies = json.load(open(a.movies))
    qb_hashes = {t["hash"].lower() for t in qb}
    plan = build_truth(qb, movies)

    con = sqlite3.connect(DB); con.execute("PRAGMA foreign_keys=ON"); c = con.cursor()
    db_torr = {r[0].lower(): {"id": r[1], "name": r[2], "csid": r[3]}
               for r in c.execute("SELECT hash,id,name,cross_seed_id FROM torrents")}
    db_movies = {r[0]: {"id": r[1], "lt": r[2]} for r in c.execute("SELECT radarr_id,id,latest_torrent_id FROM movies")}

    # torrents films vivants à garantir présents
    needed = set()
    for rid, g in plan.items():
        for t in [g["parent"], *g["children"]]:
            needed.add(t["hash"].lower())
    to_insert = [h for h in needed if h not in db_torr]
    # lignes FILMS fantômes = torrents référencés par un movie mais absents de qBit
    stale_ids = set()
    for rid, m in db_movies.items():
        lt = m["lt"]
        if lt is None: continue
        # hash de ce torrent
        h = next((hh for hh, v in db_torr.items() if v["id"] == lt), None)
        if h is not None and h not in qb_hashes:
            stale_ids.add(lt)

    links = sum(len(g["children"]) for g in plan.values())
    print("=== PLAN REBUILD FILMS (dry-run=%s) ===" % (not a.apply))
    print("  films mappés (groupes)         : %d" % len(plan))
    print("  torrents films à INSÉRER (manquants en BDD) : %d" % len(to_insert))
    print("  liens cross_seed à (re)poser   : %d" % links)
    print("  movies à (re)pointer sur parent : %d" % len(plan))
    print("  torrents FILMS fantômes à PURGER (movie→torrent mort) : %d" % len(stale_ids))
    if not a.apply:
        print("\n(dry-run — aucune écriture. Relance avec --apply.)")
        return

    ins_name = {t["hash"].lower(): t for rid, g in plan.items() for t in [g["parent"], *g["children"]]}
    try:
        for h in to_insert:
            t = ins_name[h]
            c.execute("INSERT INTO torrents (hash,name,indexer) VALUES (?,?,?)",
                      (h, t.get("name"), (t.get("category") or "")))
        # refresh id map
        idmap = {r[0].lower(): r[1] for r in c.execute("SELECT hash,id FROM torrents")}
        for rid, g in plan.items():
            pid = idmap[g["parent"]["hash"].lower()]
            c.execute("UPDATE torrents SET cross_seed_id=NULL WHERE id=?", (pid,))
            for ch in g["children"]:
                c.execute("UPDATE torrents SET cross_seed_id=? WHERE id=?", (pid, idmap[ch["hash"].lower()]))
            if rid in db_movies:
                c.execute("UPDATE movies SET latest_torrent_id=? WHERE radarr_id=?", (pid, rid))
            else:
                c.execute("INSERT INTO movies (radarr_id,title,latest_torrent_id) VALUES (?,?,?)",
                          (rid, g["title"], pid))
        for tid in stale_ids:
            c.execute("DELETE FROM torrents WHERE id=?", (tid,))
        con.commit()
        print("✅ rebuild appliqué.")
    except Exception as e:
        con.rollback(); print("❌ rollback:", e); raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
