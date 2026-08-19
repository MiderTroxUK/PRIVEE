"""Injection du tour N (U6) : KPIs, jalons, evenements, puis avance d'une semaine.

Usage :
    python inject_tour.py --tour N --db-dir D [--dry-run-ahp]

Garde-fou d'idempotence : le tour N n'est accepte que si le dernier tour joue
est N-1 (campaign_state.json). Pas de rejeu silencieux.

Sequence d'un tour :
    1. KPIs depuis ``data/prepared/tour_NN.csv`` (source="weekly") ;
    2. progres/statuts des jalons depuis ``milestones_NN.json`` ;
    3. evenements calibres depuis ``events_NN.json`` (EventEngine.apply, qui
       journalise, mute les KPIs et reevalue) ;
    4. si ``--dry-run-ahp`` : 8 evaluations AHP synthetiques (profils
       paniqueur / sous-declarant / neutre - dry run et baseline U10) ;
    5. ``advance_week(n=1)`` - le reseau passe a la semaine suivante ;
    6. snapshot automatique (export_state).

En campagne reelle, l'etape 4 est remplacee par la fenetre de reponse humaine :
lancer SANS ``--dry-run-ahp``, attendre la couverture 8/8, puis relancer avec
``--advance-only`` pour clore le tour.

``_load_tour_files`` et ``_submit_synthetic_ahp`` sont reutilisees telles
quelles par le runner headless (``run_campaign.py``, U5) : la seconde y gagne
un callback ``respond`` optionnel (contrat 2 du plan v7) qui remplace les
profils synthetiques par une declaration pilotee noeud par noeud, sans changer
le comportement CLI par defaut de ce script.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path

import _common
from _common import FACILITATOR, PREPARED, PROJECT_ID, scenario

from supplyscore.core.ahp import bipolar_to_saaty, run_ahp, score_6_to_9

#: Paires de criteres comparees par le questionnaire AHP (ordre fixe UI) - contrat 2 du plan v7 : ``bipolar[k]`` juge la paire ``_AHP_PAIRS[k]``.
_AHP_PAIRS: list[tuple[int, int]] = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]


def _load_tour_files(
    tour: int, prepared_dir: Path = PREPARED
) -> tuple[list[dict], list[dict], list[dict]]:
    prepared_dir = Path(prepared_dir)
    kpi_rows: list[dict] = []
    with (prepared_dir / f"tour_{tour:02d}.csv").open(encoding="utf-8") as f:
        kpi_rows = list(csv.DictReader(f))
    events = json.loads((prepared_dir / f"events_{tour:02d}.json").read_text(encoding="utf-8"))
    milestones = json.loads(
        (prepared_dir / f"milestones_{tour:02d}.json").read_text(encoding="utf-8")
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
        found = [ms for ms in service.registry.list_milestones(m["node"]) if ms.name == m["name"]]
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
            ev["node"],
            ev["type"],
            ev["params"],
            operator_id=FACILITATOR,
            notes=ev.get("note", ""),
        )
        print(f"  [event] {ev['node']}: {ev['type']} -> {len(applied.impacts)} impact(s)")
    return len(events)


def _kpi_series(prepared_dir: Path, node_id: str, upto_tour: int) -> dict[str, dict[int, float]]:
    """Serie ``{kpi_path: {tour: valeur}}`` du noeud, tours 0..upto_tour, reportee en avant.

    Combine la baseline T0 (``scenario.BASELINE_KPIS``) et les deltas
    injectes (``tour_NN.csv``) : un chemin non modifie a un tour garde sa
    derniere valeur connue - un KPI ne revient jamais a zero entre deux
    tours faute de changement explicite (comportement reel du modele).
    """
    prepared_dir = Path(prepared_dir)
    current: dict[str, float] = dict(scenario.BASELINE_KPIS.get(node_id, {}))
    series: dict[str, dict[int, float]] = {}
    for path, val in current.items():
        series.setdefault(path, {})[0] = val
    for t in range(0, upto_tour + 1):
        csv_path = prepared_dir / f"tour_{t:02d}.csv"
        if csv_path.exists():
            with csv_path.open(encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row["node_id"] == node_id:
                        current[row["kpi_path"]] = float(row["valeur"])
        for path, val in current.items():
            series.setdefault(path, {})[t] = val
    return series


def _node_features(
    prepared_dir: Path, node_id: str, tour: int, events: list[dict], press_flag: bool
) -> dict:
    """Construit ``features`` pour le rappel ``respond`` (contrat 2, plan v7).

    9 chemins KPI de ``make_briefings.FIELD_LABELS`` -> ``{val, d1, d2}`` :
    ``val`` vaut 0.0 si le noeud n'a jamais eu ce KPI (absence de signal, pas
    une vraie mesure) ; ``d1``/``d2`` restent None tant que l'historique est
    insuffisant (moins de 2, resp. 3, points). ``event_flag`` : un evenement
    touche CE noeud ce tour. ``press_flag`` : la revue de presse du tour n'est
    pas vide.
    """
    import make_briefings

    series = _kpi_series(prepared_dir, node_id, tour)
    features: dict = {}
    for path in make_briefings.FIELD_LABELS:
        by_tour = series.get(path, {})
        val = by_tour.get(tour)
        prev1 = by_tour.get(tour - 1) if tour >= 1 else None
        prev2 = by_tour.get(tour - 2) if tour >= 2 else None
        d1 = (val - prev1) if (val is not None and prev1 is not None) else None
        d1_prev = (prev1 - prev2) if (prev1 is not None and prev2 is not None) else None
        d2 = (d1 - d1_prev) if (d1 is not None and d1_prev is not None) else None
        features[path] = {"val": val if val is not None else 0.0, "d1": d1, "d2": d2}
    features["event_flag"] = any(ev.get("node") == node_id for ev in events)
    features["press_flag"] = press_flag
    return features


def _most_inconsistent_pair(comparisons: dict[tuple[int, int], float], weights) -> tuple[int, int]:
    """Paire ``(i, j)`` dont le jugement de Saaty s'ecarte le plus de wi/wj.

    Diagnostic AHP standard : ``|log(A[i,j]) - log(wi/wj)|`` maximal.
    """
    return max(
        _AHP_PAIRS,
        key=lambda p: abs(math.log(comparisons[p]) - math.log(weights[p[0]] / weights[p[1]])),
    )


def _nudge_bipolar(v: int, target_saaty: float) -> int:
    """Decale ``v`` d'un cran (+/-1, borne a [-8, 8]) vers le jugement Saaty cible."""
    candidates = [c for c in (v - 1, v + 1) if -8 <= c <= 8]
    if not candidates:
        return v
    return min(
        candidates,
        key=lambda c: abs(math.log(bipolar_to_saaty(c)) - math.log(target_saaty)),
    )


def _resolve_consistency(
    bipolar: list[int], scores_ui: list[int]
) -> tuple[dict[tuple[int, int], float], list[float], bool]:
    """Convertit une reponse brute (bipolaire + notes UI) en jugements Saaty.

    Regle CR (contrat 2, plan v7) : si l'AHP est incoherent (CR >= seuil de
    Saaty), une correction est tentee UNE fois - la paire la plus divergente
    est identifiee puis sa valeur bipolaire rapprochee d'un cran de la
    coherence. Retourne ``(comparisons, criteria_scores, is_consistent)`` ;
    ``is_consistent`` a False signale a l'appelant de retomber sur la
    declaration du tour precedent (regle de repli).
    """
    criteria_scores = [score_6_to_9(float(s)) for s in scores_ui]
    comparisons = {pair: bipolar_to_saaty(v) for pair, v in zip(_AHP_PAIRS, bipolar, strict=True)}
    res = run_ahp(comparisons, n=4)
    if res.is_consistent:
        return comparisons, criteria_scores, True

    i, j = _most_inconsistent_pair(comparisons, res.weights)
    idx = _AHP_PAIRS.index((i, j))
    target = float(res.weights[i] / res.weights[j])
    nudged = list(bipolar)
    nudged[idx] = _nudge_bipolar(bipolar[idx], target)
    comparisons = {pair: bipolar_to_saaty(v) for pair, v in zip(_AHP_PAIRS, nudged, strict=True)}
    res = run_ahp(comparisons, n=4)
    return comparisons, criteria_scores, res.is_consistent


def _submit_synthetic_ahp(
    service,
    tour: int,
    respond=None,
    prepared_dir: Path = PREPARED,
    seed: int | None = None,
) -> None:
    """Soumet une evaluation AHP par noeud (8 au total).

    Sans ``respond`` (defaut, comportement CLI inchange) : profils
    synthetiques biaises, coherence garantie par construction (matrice
    unitaire, CR = 0) ; le biais du profil passe par les scores locaux des 4
    criteres, ancres sur l'urgence reelle LOCALE du noeud (score nominal =
    1 + 8-Ur_local - pas l'urgence propagee, qui rendrait le Ud synthetique
    circulairement sature), deterministe par (noeud, tour) pour la
    reproductibilite.

    Avec ``respond`` (contrat 2, plan v7 - utilise par ``run_campaign.py``,
    U5) : pour chaque noeud, ``respond(node_id, tour, features, rng)`` fournit
    ``{"bipolar": [6 valeurs -8..8], "scores_ui": [4 valeurs 1..6]}`` ; en cas
    d'incoherence persistante apres la correction d'un cran
    (:func:`_resolve_consistency`), la declaration du tour precedent du noeud
    est reconduite (``latest_assessment``), ou une declaration neutre si
    aucun historique n'existe (T0).
    """
    from supplyscore.services.orchestrator import SupplyScoreService

    if respond is None:
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
            ur = state.ur_local if state is not None and state.ur_local is not None else 0.0
            nominal = 1.0 + 8.0 * min(max(ur, 0.0), 1.0)
            bias = profile_by_node.get(node_id, 0.0)
            scores = [min(max(nominal + bias + rng.uniform(-0.5, 0.5), 1.0), 9.0) for _ in range(4)]
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
        return

    prepared_dir = Path(prepared_dir)
    events = json.loads((prepared_dir / f"events_{tour:02d}.json").read_text(encoding="utf-8"))
    press_flag = bool(scenario.NARRATIVE.get(tour, {}).get("presse", ""))
    for spec in scenario.NODES:
        node_id = spec["id"]
        rng = (
            random.Random((seed, node_id, tour))
            if seed is not None
            else random.Random(f"{node_id}-{tour}")
        )
        features = _node_features(prepared_dir, node_id, tour, events, press_flag)
        raw = respond(node_id, tour, features, rng)
        bipolar = list(raw["bipolar"])
        scores_ui = list(raw["scores_ui"])
        if len(bipolar) != 6 or len(scores_ui) != 4:
            raise ValueError(
                f"Réponse du déclarant invalide pour {node_id!r} (tour {tour}) : "
                f"attendu 6 valeurs bipolaires + 4 notes UI, reçu "
                f"{len(bipolar)} + {len(scores_ui)}."
            )
        comparisons, criteria_scores, ok = _resolve_consistency(bipolar, scores_ui)
        notes = f"tour {tour} — déclarant"
        if not ok:
            prev = service.client_db(node_id).latest_assessment(node_id)
            if prev is not None:
                comparisons = prev.comparisons
                criteria_scores = prev.criteria_scores
                notes = (
                    f"tour {tour} — repli (CR incohérent après correction) : "
                    "déclaration du tour précédent reconduite"
                )
            else:
                comparisons = {pair: 1.0 for pair in _AHP_PAIRS}
                criteria_scores = [score_6_to_9(3.0)] * 4
                notes = f"tour {tour} — repli neutre (CR incohérent, pas d'historique T0)"
        assessment = SupplyScoreService.build_assessment(
            node_id=node_id,
            project_id=PROJECT_ID,
            operator_id=_common.OPERATORS[node_id],
            comparisons=comparisons,
            criteria_scores=criteria_scores,
            notes=notes,
        )
        service.submit_assessment(assessment)
    print("  [ahp] 8 évaluations soumises (déclarant)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _common.require_db_dir(parser)
    parser.add_argument("--tour", type=int, required=True, help="Numéro de tour (0..18)")
    parser.add_argument(
        "--dry-run-ahp",
        action="store_true",
        help="Soumet des AHP synthétiques (dry run) au lieu d'attendre les humains",
    )
    parser.add_argument(
        "--advance-only",
        action="store_true",
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
        # Erosion hebdomadaire d'abord (" semaine ecoulee sans nouvel incident ") : les effets des evenements PASSES refluent avant d'injecter ceux du tour.
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
