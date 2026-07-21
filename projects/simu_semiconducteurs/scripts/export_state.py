"""Snapshot d'état de campagne (U6) : scores, criticité, couverture, sauvegarde.

Usage :
    python export_state.py --db-dir D [--tour N]

Écrit ``analysis/snapshots/tour_NN.json`` (ou ``adhoc_<ts>.json`` sans --tour)
et une archive zip de la base après chaque tour (rétention gérée par le
service de sauvegarde natif de SupplyScore).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import _common
from _common import PROJECT_ID, SNAPSHOTS


def snapshot(db_dir: str, service, tour: int | None, out_dir: Path | None = None) -> dict:
    """Construit et écrit le snapshot du réseau à l'instant courant.

    Args:
        db_dir: dossier des bases SQLite de la campagne (pour la sauvegarde
            zip, cf. ``ServiceSauvegarde``).
        service: façade ``SupplyScoreService`` déjà ouverte sur ``db_dir``.
        tour: numéro de tour (nomme le fichier ``tour_NN.json``), ou None
            pour un instantané ad hoc (``adhoc_<horodatage>.json``).
        out_dir: dossier de dépôt de ``tour_NN.json`` ; ``SNAPSHOTS`` (dossier
            de campagne standard) par défaut. Redirigeable par le runner de
            campagne headless (``run_campaign.py``, U5) vers un dossier de run
            dédié, sans dupliquer la logique de snapshot.
    """
    from supplyscore.services.criticite import ServiceCriticite
    from supplyscore.services.weekly import CycleHebdomadaire

    dest = Path(out_dir) if out_dir is not None else SNAPSHOTS
    dest.mkdir(parents=True, exist_ok=True)

    nodes_out: dict[str, dict] = {}
    for node in service.repo.nodes_by_project(PROJECT_ID):
        u = node.urgency
        nodes_out[node.id] = {
            "name": node.name,
            "rank": node.rank,
            "status": str(node.status),
            "ud": u.ud,
            "ur": u.ur,
            "adequation": u.adequation,
            "false_urgency": u.false_urgency,
            "hidden_risk": u.hidden_risk,
            "ud_local": u.ud_local,
            "ur_local": u.ur_local,
        }

    try:
        criticite = [
            {
                "node_id": p.node_id,
                "rank": p.rank,
                "delta_ur_final": p.delta_ur_final,
                "delta_ur_max": p.delta_ur_max,
                "nb_impactes": p.nb_impactes,
            }
            for p in ServiceCriticite(service).indice_criticite(PROJECT_ID)
        ]
    except Exception as exc:  # noqa: BLE001 — snapshot best-effort, consigné
        criticite = [{"erreur": f"{type(exc).__name__}: {exc}"}]

    a_jour, total = CycleHebdomadaire(service).couverture(PROJECT_ID)

    data = {
        "tour": tour,
        "horodatage": time.time(),
        "couverture": {"a_jour": a_jour, "total_actifs": total},
        "nodes": nodes_out,
        "criticite": criticite,
    }
    name = f"tour_{tour:02d}.json" if tour is not None else f"adhoc_{int(time.time())}.json"
    path = dest / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [snapshot] {path}")

    # Sauvegarde zip de la base (service natif : integrity_check + backup API).
    try:
        from supplyscore.data.backup import ServiceSauvegarde

        archive = ServiceSauvegarde(db_dir).backup_all()
        print(f"  [backup] {archive}")
    except Exception as exc:  # noqa: BLE001 — la campagne continue, mais on le voit
        print(f"  [backup ÉCHEC] {type(exc).__name__}: {exc}")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _common.require_db_dir(parser)
    parser.add_argument("--tour", type=int, default=None, help="Numéro de tour (étiquette)")
    args = parser.parse_args(argv)

    service = _common.open_service(args.db_dir)
    try:
        data = snapshot(args.db_dir, service, args.tour)
        cov = data["couverture"]
        print(f"Couverture hebdo : {cov['a_jour']}/{cov['total_actifs']}")
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    sys.exit(main())
