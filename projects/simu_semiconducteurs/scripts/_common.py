"""Utilitaires partagés des scripts facilitateur (campagne HÉLIOS).

- amorçage des chemins (racine du dépôt + dossier scenario) ;
- ouverture du service SupplyScore sur la base de campagne ;
- état de campagne (state.json dans le db-dir) : idempotence des injections.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent.parent.parent  # C:\PRIVEE\AZURE
PROJECT_DIR = _HERE.parent  # projects/simu_semiconducteurs
PREPARED = PROJECT_DIR / "data" / "prepared"
SNAPSHOTS = PROJECT_DIR / "analysis" / "snapshots"

for p in (str(REPO_ROOT), str(PROJECT_DIR / "scenario")):
    if p not in sys.path:
        sys.path.insert(0, p)

import scenario  # noqa: E402

PROJECT_ID = "helios"
FACILITATOR = "facilitateur"

#: operator_id de chaque consultant (carte de rôle) : C1..C8.
OPERATORS: dict[str, str] = {n["id"]: n["consultant"] for n in scenario.NODES}


def open_service(db_dir: str):
    """Ouvre la façade SupplyScore sur ``db_dir`` (import différé, service prêt)."""
    from supplyscore.services.orchestrator import SupplyScoreService

    service = SupplyScoreService(db_dir=db_dir)
    service.load_graph_from_registry()
    return service


def state_path(db_dir: str) -> Path:
    return Path(db_dir) / "campaign_state.json"


def load_state(db_dir: str) -> dict | None:
    path = state_path(db_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(db_dir: str, state: dict) -> None:
    state_path(db_dir).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def require_db_dir(parser) -> None:
    """Ajoute --db-dir OBLIGATOIRE (jamais de base par défaut : pas d'accident)."""
    parser.add_argument(
        "--db-dir",
        required=True,
        help="Dossier des bases SQLite de la campagne (hors dossier synchronisé cloud)",
    )
