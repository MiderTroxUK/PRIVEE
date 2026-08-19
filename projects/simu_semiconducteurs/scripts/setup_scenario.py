"""Mise en place du scenario HELIOS (U6) : projet, noeuds, arcs, jalons, mode jeu.

Usage :
    python setup_scenario.py --db-dir D [--force]

Refuse de s'executer si la base contient deja une campagne (sauf --force, qui
exige une confirmation interactive). Apres setup, l'horloge du projet est en
mode " jeu " et la campagne attend ``inject_tour.py --tour 0``.
"""

from __future__ import annotations

import argparse
import sys
import time

import _common
from _common import FACILITATOR, PROJECT_ID, scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _common.require_db_dir(parser)
    parser.add_argument("--force", action="store_true", help="Écrase une campagne existante")
    args = parser.parse_args(argv)

    if _common.load_state(args.db_dir) is not None:
        if not args.force:
            print("REFUS : campaign_state.json existe déjà dans ce db-dir.")
            print("Relancer avec --force pour écraser (confirmation demandée).")
            return 2
        answer = input("Écraser la campagne existante ? Taper OUI : ")
        if answer.strip() != "OUI":
            print("Abandon.")
            return 2

    from supplyscore.domain.milestones import Milestone
    from supplyscore.domain.models import ArcKind, Project, SupplyArc, SupplyNode

    service = _common.open_service(args.db_dir)
    try:
        t0 = time.time()
        project = Project(
            id=PROJECT_ID,
            name=scenario.PROJECT_NAME,
            owner_node_id="orbitalys",
            description=scenario.PROJECT_DESCRIPTION,
            t0_ts=t0,
        )
        nodes = [
            SupplyNode(
                id=spec["id"],
                name=spec["name"],
                label=spec["label"],
                rank=spec["rank"],
                project_id=PROJECT_ID,
                location=spec["location"],
                onboarding_state="complete",
            )
            for spec in scenario.NODES
        ]
        arcs = [
            SupplyArc(
                source_id=a["source"],
                target_id=a["target"],
                gamma=a["gamma"],
                beta=a["beta"],
                kind_arc=ArcKind.BACKUP if a["kind"] == "backup" else ArcKind.NOMINAL,
            )
            for a in scenario.ARCS
        ]
        service.create_project(project, nodes, arcs)

        # KPIs initiaux (T0) - via MutationService : validation + audit.
        for node_id, kpis in scenario.BASELINE_KPIS.items():
            service.mutations.update_kpis(
                node_id, dict(kpis), source="setup", operator_id=FACILITATOR
            )

        # Jalons : offsets en semaines moteur depuis t0.
        week_s = 168 * 3600.0
        for i, (node_id, name, kind, start_wk, deadline_wk) in enumerate(scenario.MILESTONES):
            service.registry.save_milestone(
                Milestone(
                    id=f"m_{node_id}_{i}",
                    node_id=node_id,
                    name=name,
                    kind=kind,
                    start_ts=t0 + start_wk * week_s,
                    deadline_ts=t0 + deadline_wk * week_s,
                    position=i,
                )
            )

        service.set_clock_mode(PROJECT_ID, "game")
        service.evaluate_all(persist=True)

        _common.save_state(args.db_dir, {"project_id": PROJECT_ID, "last_tour": -1})

        print(f"Campagne initialisée dans {args.db_dir} (t0 = {t0:.0f}).")
        print(f"{'Nœud':<28} {'Rang':<5} {'Consultant (operator_id)'}")
        for spec in scenario.NODES:
            print(f"{spec['name']:<28} {spec['rank']:<5} {spec['consultant']}")
        print("\nProchaine étape : inject_tour.py --tour 0 (entraînement).")
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    sys.exit(main())
