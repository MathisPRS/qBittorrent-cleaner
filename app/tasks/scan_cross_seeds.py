# app/tasks/scan_cross_seeds.py
from typing import List, Dict, Optional, Tuple
import re

from app.logger import get_logger
from ..repositories.torrents_repo import TorrentsRepo
from ..adapters.qbittorrent_adapter import QbittorrentAdapter
from ..adapters.gotify_adapter import notify_gotify
from ..extensions import db
from ..models.torrents import Torrents
from ..config import QBIT_HOST, QBIT_USER, QBIT_PASS

# configuration / constantes
CROSS_KEYWORDS = ("cross", "cross-seed", "cross-seed-link", "crossseed", "cross_seed")
CATEGORY_SPLIT_RE = re.compile(r"^([^\.]+)")

# -------------------------
# Helpers / small utilities
# -------------------------
def _get_base_category(category: Optional[str]) -> Optional[str]:
    if not category:
        return None
    m = CATEGORY_SPLIT_RE.match(category)
    return (m.group(1).lower().strip()) if m else category.lower().strip()

def _category_contains_cross(category: Optional[str]) -> bool:
    if not category:
        return False
    lower = category.lower()
    return any(k in lower for k in CROSS_KEYWORDS)

def _normalize_hash(h: Optional[str]) -> Optional[str]:
    if not h:
        return None
    return h.strip().lower()

# -------------------------
# Core small functions
# -------------------------
def list_qb_torrents(logger) -> List[Dict]:
    """Récupère la liste brute des torrents depuis qBittorrent via l'adapter."""
    qb = QbittorrentAdapter(QBIT_HOST, QBIT_USER, QBIT_PASS, logger_obj=logger)
    return qb.list_torrents()

def filter_cross_candidates(qb_torrents: List[Dict]) -> List[Dict]:
    """Filtre les torrents qB pour ne garder que ceux dont la catégorie contient 'cross'."""
    candidates = []
    for t in qb_torrents:
        category = (t.get("category") or "").strip()
        name = (t.get("name") or t.get("label") or "").strip()
        if not name:
            continue
        if _category_contains_cross(category):
            candidates.append(t)
    return candidates

def build_qb_index_by_category_and_name(qb_torrents: List[Dict]) -> Dict[Tuple[str, str], List[Dict]]:
    """
    Construit un index (base_category, name) -> [torrent_dicts]
    Permet recherche rapide du parent par (base_category, name).
    """
    index = {}
    for t in qb_torrents:
        category = (t.get("category") or "").strip()
        name = (t.get("name") or t.get("label") or "").strip()
        if not name:
            continue
        base = _get_base_category(category) or ""
        key = (base, name)
        index.setdefault(key, []).append(t)
    return index

def diff_candidates_with_db(candidates: List[Dict], torrents_repo: TorrentsRepo) -> List[Dict]:
    """
    Ne retourne que les candidats 'à traiter':
     - ceux dont le hash n'existe pas en BDD
     - ou ceux qui existent mais n'ont pas de cross_seed_id (non-lies)
    Optimise en batchant la recherche DB par hash IN (...)
    """
    hashes = [_normalize_hash(c.get("hash")) for c in candidates if c.get("hash")]
    hashes = [h for h in hashes if h]
    if not hashes:
        return candidates  # pas de hash -> on traite pour notification manuelle plus tard

    # Récupérer en une seule query les rows existantes
    try:
        existing_rows = db.session.query(Torrents).filter(Torrents.hash.in_(hashes)).all()
        existing_map = { (r.hash or "").strip().lower(): r for r in existing_rows }
    except Exception:
        # si erreur DB, on renvoie tous pour traitement (défensif)
        return candidates

    to_process = []
    for cand in candidates:
        h = _normalize_hash(cand.get("hash"))
        row = existing_map.get(h)
        if row is None:
            to_process.append(cand)  # absent en BDD -> créer+link
        else:
            # present en BDD mais non lié au parent -> re-lier si possible
            if getattr(row, "cross_seed_id", None) in (None, 0):
                to_process.append(cand)
            # sinon déjà lié -> on skip
    return to_process

def find_parent_candidate_in_qb(qb_index: Dict[Tuple[str, str], List[Dict]], child_torrent: Dict) -> Optional[Dict]:
    """
    Recherche le parent en qB pour un child donné :
    parent must have same base_category and exact same name.
    Retourne la dict qB du parent si trouvée, sinon None.
    """
    category = (child_torrent.get("category") or "").strip()
    name = (child_torrent.get("name") or child_torrent.get("label") or "").strip()
    base = _get_base_category(category)
    if not base or not name:
        return None
    # ignore adult base categories
    if base == "adultes":
        return None
    key = (base, name)
    candidates = qb_index.get(key, [])
    return candidates[0] if candidates else None

def ensure_torrent_row_exists(torrents_repo: TorrentsRepo, hashval: str, name: Optional[str]) -> Torrents:
    """
    Retourne la row Torrents existante ou la crée (committed).
    Utilise le repo pour bénéficier des logs/gestion existants.
    """
    existing = torrents_repo.get_by_hash(hashval)
    if existing:
        return existing
    return torrents_repo.create(hashval=hashval, name=name)

def link_child_to_parent_db(child_row: Torrents, parent_row: Torrents, logger) -> bool:
    """
    Lie child_row.cross_seed_id -> parent_row.id si besoin, commit et retourne True si linkage effectué.
    """
    if getattr(child_row, "cross_seed_id", None) == parent_row.id:
        logger.debug("link_child_to_parent_db: already linked child_id=%s parent_id=%s", getattr(child_row, "id", None), parent_row.id)
        return False
    child_row.cross_seed_id = parent_row.id
    try:
        db.session.add(child_row)
        db.session.commit()
        logger.info("link_child_to_parent_db: linked child id=%s hash=%s -> parent id=%s", getattr(child_row, "id", None), child_row.hash, parent_row.id)
        return True
    except Exception:
        logger.exception("link_child_to_parent_db: commit failed linking child hash=%s -> parent id=%s", child_row.hash, parent_row.id)
        try:
            db.session.rollback()
        except Exception:
            logger.exception("link_child_to_parent_db: rollback failed after linking error")
        return False

def notify_parent_missing(child_name: str, child_category: str, logger) -> None:
    """Envoi Gotify si parent introuvable pour un cross."""
    title = "Cross parent not found"
    lines = [
        f"Torrent: {child_name}",
        f"Category: {child_category}",
        "Action: parent not found in qBittorrent — manual check required"
    ]
    logger.warning("notify_parent_missing: parent not found for %s (category=%s)", child_name, child_category)
    try:
        notify_gotify(title, lines)
    except Exception:
        logger.exception("notify_parent_missing: failed to send Gotify for %s", child_name)

# -------------------------
# Orchestrateur principal
# -------------------------
def scan_cross_seeds_once(app) -> Dict:
    """
    Orchestrateur principal — compose les petites fonctions ci-dessus.
    Retourne un résumé.
    """
    logger = get_logger(__name__, app=app)
    logger.info("scan_cross_seeds_once: start (optimized, function-split)")

    torrents_repo = TorrentsRepo()

    # 1) récupérer tous les torrents depuis qB (adapter)
    try:
        qb_torrents = list_qb_torrents(logger)
    except Exception:
        logger.exception("scan_cross_seeds_once: failed to list torrents from qB")
        return {"error": "qb_list_failed"}

    # 2) index pour recherches parents + liste candidates cross
    qb_index = build_qb_index_by_category_and_name(qb_torrents)
    cross_candidates = filter_cross_candidates(qb_torrents)

    logger.info("scan_cross_seeds_once: %d qb torrents, %d cross candidates", len(qb_torrents), len(cross_candidates))

    # 3) réduire à ceux qui manquent ou non-liés en BDD
    to_process = diff_candidates_with_db(cross_candidates, torrents_repo)
    logger.info("scan_cross_seeds_once: %d cross candidates to process (missing/unlinked)", len(to_process))

    # 4) pour chaque candidate -> find parent, create rows if needed, link child->parent
    processed = 0
    linked = 0
    created_rows = 0
    notifications = 0
    skipped_adult = 0

    for child in to_process:
        processed += 1
        child_name = (child.get("name") or child.get("label") or "").strip()
        child_cat = (child.get("category") or "").strip()
        child_hash = _normalize_hash(child.get("hash"))

        logger.info("scan_cross_seeds_once: processing child name=%s category=%s hash=%s", child_name, child_cat, child_hash)

        # skip if no hash or name
        if not child_hash or not child_name:
            logger.warning("scan_cross_seeds_once: skipping child with missing hash/name: %s", child)
            continue

        # find parent in qb
        parent_qb = find_parent_candidate_in_qb(qb_index, child)
        if parent_qb is None:
            # parent not found OR base category is adult
            base = _get_base_category(child_cat)
            if base == "adultes":
                skipped_adult += 1
                logger.info("scan_cross_seeds_once: skipping child %s because base category '%s' is adult", child_name, base)
            else:
                notifications += 1
                notify_parent_missing(child_name, child_cat, logger)
            continue

        parent_hash = _normalize_hash(parent_qb.get("hash"))
        if not parent_hash:
            logger.warning("scan_cross_seeds_once: found parent candidate but it has no hash for %s", child_name)
            continue

        # ensure parent row exists
        parent_row = torrents_repo.get_by_hash(parent_hash)
        if parent_row is None:
            parent_row = ensure_torrent_row_exists(torrents_repo, parent_hash, parent_qb.get("name"))
            created_rows += 1

        # ensure child row exists
        child_row = torrents_repo.get_by_hash(child_hash)
        if child_row is None:
            child_row = ensure_torrent_row_exists(torrents_repo, child_hash, child_name)
            created_rows += 1

        # link child -> parent in db
        linked_ok = link_child_to_parent_db(child_row, parent_row, logger)
        if linked_ok:
            linked += 1

    summary = {
        "qb_total": len(qb_torrents),
        "cross_candidates_total": len(cross_candidates),
        "to_process": len(to_process),
        "processed": processed,
        "linked": linked,
        "created_rows": created_rows,
        "notifications": notifications,
        "skipped_adult": skipped_adult,
    }

    logger.info("scan_cross_seeds_once: finished summary=%s", summary)
    return summary
