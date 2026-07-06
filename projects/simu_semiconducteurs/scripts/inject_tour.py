"""Injection du tour N (U6) : KPIs, jalons, événements, puis avance d'une semaine.

Usage :
    python inject_tour.py --tour N --db-dir D [--dry-run-ahp]

Garde-fou d'idempotence : le tour N n'est accepté que si le dernier tour joué
est N-1 (campaign_state.json). Pas de rejeu silencieux.

Séquence d'un tour :
    1. KPIs depuis ``data/prepared/tour_NN.csv`` (source="weekly") ;
    2. progrès/statuts des jalons depuis ``milestones_NN.json`` ;
    3. événements calibrés depuis ``events_NN.json`` (EventEngine.apply, qui
       journalise, mute les KPIs et réévalue) ;
    4. si ``--dry-run-ahp`` : 8 évaluations AHP synthétiques (profils
       paniqueur / sous-déclarant / neutre — dry run et baseline U10) ;
    5. ``advance_week(n=1)`` — le réseau passe à la semaine suivante ;
    6. snapshot automatique (export_state).

En campagne réelle, l'étape 4 est remplacée par la fenêtre de réponse humaine :
lancer SANS ``--dry-run-ahp``, attendre la couverture 8/8, puis relancer avec
``--advance-only`` pour clore le tour.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys

import _common
from _common import FACILITATOR, PREPARED, PROJECT_ID, scenario


def _load_tour_files(tour: int) -> tuple[list[dict], list[dict], list[dict]]:
    kpi_rows: list[dict] = []
    with (PREPARED / f"tour_{tour:02d}.csv").open(encoding="utf-8") as f:
        kpi_rows = list(csv.DictReader(f))
    events = json.loads((PREPARED / f"events_{tour:02d}.json").read_text(encoding="utf-8"))
    milestones = json.loads(
        (PREPARED / f"milestones_{tour:02d}.json").read_text(encoding="utf-8")
    )
    return kpi_rows, events, milestones


def _inject_kpis(service, kpi_rows: list[dict]) -> int:
    by_node: dict[str, dict[str, float]] = {}
    for row in kpi_rows:
        by_node.setdefault(row["node_id"], {})[row["kpi_path"]] = float(row["valeur"])
    changed = 0
    for node_id, changes in by_node.items():
        entries = service.mutations.update_kpis(
            node_id, changes, source="weekly", operator_id=FACILITATOR
        )
        changed += len(entries)
    return changed


def _inject_milestones(service, milestones: list[dict]) -> int:
    project = next(p for p in service.registry.list_projects() if p.id == PROJECT_ID)
    week_s = 168 * 3600.0
    changed = 0
    for m in milestones:
        found = [
            ms for ms in service.registry.list_milestones(m["node"]) if ms.name == m["name"]
        ]
        if not found:
            print(f"  [!] jalon introuvable : {m['node']} / {m['name']}")
            continue
        changes: dict = {"progress": float(m["progress"])}
        if m.get("status") == "done":
            changes["status"] = "done"
        if "deadline_wk" in m:  # re-planification officielle (revue de programme)
            changes["deadline_ts"] = project.origin_ts + m["deadline_wk"] * week_s
            print(f"  [replan] {m['node']} / {m['name']} -> semaine {m['deadline_wk']}")
        entries = service.mutations.update_milestone(
            found[0].id, changes, source="weekly", operator_id=FACILITATOR
        )
        changed += len(entries)
    return changed


def _inject_events(service, events: list[dict]) -> int:
    from supplyscore.services.events import EventEngine

    engine = EventEngine(service)
    for ev in events:
        applied = engine.apply(
            ev["node"], ev["type"], ev["params"], operator_id=FACILITATOR,
            notes=ev.get("note", ""),
        )
        print(f"  [event] {ev['node']}: {ev['type']} -> {len(applied.impacts)} impact(s)")
    return len(events)


def _submit_synthetic_ahp(service, tour: int) -> None:
    """Soumet 8 évaluations synthétiques (profils biaisés, cohérence garantie).

    Les comparaisons sont neutres (matrice unitaire, CR = 0) ; le biais du
    profil passe par les scores locaux des 4 critères, ancrés sur l'urgence
    réelle LOCALE du nœud (score nominal = 1 + 8·Ur_local — pas l'urgence
    propagée, qui rendrait le Ud synthétique circulairement saturé),
    déterministe par (nœud, tour) pour la reproductibilité.
    """
    from supplyscore.services.orchestrator import SupplyScoreService

    profile_by_node: dict[str, float] = {}
    for profile in scenario.SYNTHETIC_PROFILES.values():
        for node_id in profile["nodes"]:
            profile_by_node[node_id] = profile["bias"]

    states = service.evaluate_all(persist=False)
    comparisons = {(i, j): 1.0 for i in range(4) for j in range(i + 1, 4)}
    for spec in scenario.NODES:
        node_id = spec["id"]
        rng = random.Random(f"{node_id}-{tour}")
        state = states.get(node_id)
        ur = (state.ur_local if state is not None and state.ur_local is not None
              else 0.0)
        nominal = 1.0 + 8.0 * min(max(ur, 0.0), 1.0)
        bias = profile_by_node.get(node_id, 0.0)
        scores = [
            min(max(nominal + bias + rng.uniform(-0.5, 0.5), 1.0), 9.0) for _ in range(4)
        ]
        assessment = SupplyScoreService.build_assessment(
            node_id=node_id,
            project_id=PROJECT_ID,
            operator_id=f"synth_{_common.OPERATORS[node_id]}",
            comparisons=comparisons,
            criteria_scores=scores,
            notes=f"dry-run tour {tour}",
        )
        service.submit_assessment(assessment)
    print("  [ahp] 8 évaluations synthétiques soumises")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _common.require_db_dir(parser)
    parser.add_argument("--tour", type=int, required=True, help="Numéro de tour (0..18)")
    parser.add_argument(
        "--dry-run-ahp", action="store_true",
        help="Soumet des AHP synthétiques (dry run) au lieu d'attendre les humains",
    )
    parser.add_argument(
        "--advance-only", action="store_true",
        help="Clôture seulement : advance_week après la fenêtre de réponse humaine",
    )
    args = parser.parse_args(argv)

    state = _common.load_state(args.db_dir)
    if state is None:
        print("REFUS : pas de campagne dans ce db-dir (lancer setup_scenario.py).")
        return 2

    service = _common.open_service(args.db_dir)
    try:
        if args.advance_only:
            if state.get("pending_tour") != args.tour:
                print(f"REFUS : aucun tour {args.tour} en attente de clôture.")
                return 2
            service.advance_week(PROJECT_ID, n=1)
            state["last_tour"] = args.tour
            state.pop("pending_tour", None)
            _common.save_state(args.db_dir, state)
            print(f"Tour {args.tour} clos (advance_week).")
            _export(args.db_dir, service, args.tour)
            return 0

        expected = state["last_tour"] + 1
        if args.tour != expected:
            print(f"REFUS : tour attendu = {expected}, demandé = {args.tour}.")
            return 2
        if args.tour > scenario.N_TOURS:
            print(f"REFUS : la campagne s'arrête au tour {scenario.N_TOURS}.")
            return 2

        kpi_rows, events, milestones = _load_tour_files(args.tour)
        print(f"Tour {args.tour} — injection :")
        # Érosion hebdomadaire d'abord (« semaine écoulée sans nouvel incident ») :
        # les effets des événements PASSÉS refluent avant d'injecter ceux du tour.
        if args.tour > 0:
            from supplyscore.services.events import EventEngine

            engine = EventEngine(service)
            n_decay = sum(
                len(engine.apply_weekly_decay(spec["id"], operator_id=FACILITATOR))
                for spec in scenario.NODES
            )
            print(f"  [décroissance] {n_decay} KPI(s) érodé(s)")
        n_kpi = _inject_kpis(service, kpi_rows)
        print(f"  [kpi] {n_kpi} champ(s) modifié(s)")
        n_ms = _inject_milestones(service, milestones)
        print(f"  [jalons] {n_ms} champ(s) modifié(s)")
        _inject_events(service, events)

        if args.dry_run_ahp:
            _submit_synthetic_ahp(service, args.tour)
            service.advance_week(PROJECT_ID, n=1)
            state["last_tour"] = args.tour
            _common.save_state(args.db_dir, state)
            print(f"Tour {args.tour} joué et clos (dry run).")
            _export(args.db_dir, service, args.tour)
        else:
            state["pending_tour"] = args.tour
            _common.save_state(args.db_dir, state)
            print(
                f"Tour {args.tour} injecté. Fenêtre de réponse humaine ouverte — "
                f"clore avec : inject_tour.py --tour {args.tour} --advance-only "
                f"--db-dir {args.db_dir}"
            )
        return 0
    finally:
        service.close()


def _export(db_dir: str, service, tour: int) -> None:
    import export_state

    export_state.snapshot(db_dir, service, tour)


if __name__ == "__main__":
    sys.exit(main())
