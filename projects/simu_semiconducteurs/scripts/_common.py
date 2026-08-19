"""Utilitaires partages des scripts facilitateur (campagne HELIOS).

- amorcage des chemins (racine du depot + dossier scenario) ;
- ouverture du service SupplyScore sur la base de campagne ;
- etat de campagne (state.json dans le db-dir) : idempotence des injections.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent.parent.parent  # C:\PRIVEE\AZURE


def _dossier_projet() -> Path:
    """Dossier du projet a instrumenter, resolu depuis l'environnement.

    ``SUPPLYSCORE_PROJET_DIR`` designe le dossier d'un projet — celui qui
    contient ``scenario/scenario.py`` et ``data/prepared/``. Sans lui, le
    dossier du script fait foi, donc HELIOS : aucune commande existante ne
    change de comportement.

    POURQUOI : le harnais codait ce dossier en dur. Instrumenter une autre
    chaine imposait donc d'editer le code, ce qui rendait l'outil inutilisable
    par quiconque n'y travaille pas. Un chemin relatif est resolu depuis la
    racine du depot, pour que la variable reste lisible.

    Returns:
        Le dossier du projet.

    Raises:
        SystemExit: si le dossier designe n'existe pas ou ne porte pas de
            module ``scenario``, avec un message qui dit lequel des deux.
    """
    brut = os.environ.get("SUPPLYSCORE_PROJET_DIR")
    if not brut:
        return _HERE.parent
    dossier = Path(brut)
    if not dossier.is_absolute():
        dossier = REPO_ROOT / dossier
    if not dossier.is_dir():
        raise SystemExit(f"SUPPLYSCORE_PROJET_DIR : dossier introuvable — {dossier}")
    if not (dossier / "scenario" / "scenario.py").is_file():
        raise SystemExit(
            f"SUPPLYSCORE_PROJET_DIR : {dossier} ne contient pas scenario/scenario.py"
        )
    return dossier


PROJECT_DIR = _dossier_projet()
PREPARED = PROJECT_DIR / "data" / "prepared"
SNAPSHOTS = PROJECT_DIR / "analysis" / "snapshots"

for p in (str(REPO_ROOT), str(PROJECT_DIR / "scenario")):
    if p not in sys.path:
        sys.path.insert(0, p)

import scenario  # noqa: E402

#: Identifiant du projet, porte par le scenario lui-meme. Repli sur " helios "
#: pour les scenarios anterieurs a ce champ.
PROJECT_ID = getattr(scenario, "PROJECT_ID", "helios")
FACILITATOR = "facilitateur"

#: operator_id de chaque consultant (carte de role) : C1..C8.
OPERATORS: dict[str, str] = {n["id"]: n["consultant"] for n in scenario.NODES}


def open_service(db_dir: str):
    """Ouvre la facade SupplyScore sur ``db_dir`` (import differe, service pret)."""
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
    """Ajoute --db-dir OBLIGATOIRE (jamais de base par defaut : pas d'accident)."""
    parser.add_argument(
        "--db-dir",
        required=True,
        help="Dossier des bases SQLite de la campagne (hors dossier synchronisé cloud)",
    )
