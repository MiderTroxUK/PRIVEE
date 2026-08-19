"""Injecte les résultats du pilote LLM (8 personas, 19 tours) dans une vraie
base de campagne HÉLIOS, via le même service que l'UI (orchestrator).

Rejoue exactement la séquence des scripts facilitateur (inject_tour puis
advance-only, tour par tour) mais remplace l'étape "8 évaluations AHP
synthétiques" (--dry-run-ahp) par les vraies réponses des 8 personas LLM
(analysis/llm_pilot_run/sandbox_<node>/results.jsonl).

Usage :
    python apply_llm_pilot.py --db-dir D
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

import _common
from _common import PROJECT_ID, scenario

PILOT_DIR = _common.PROJECT_DIR / "analysis" / "llm_pilot_run"
NODES = [spec["id"] for spec in scenario.NODES]


def _load_results(node_id: str) -> dict:
    path = PILOT_DIR / f"sandbox_{node_id}" / "results.jsonl"
    by_tour: dict = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        key = row["tour"]
        by_tour[key] = row
    return by_tour


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _common.require_db_dir(parser)
    args = parser.parse_args(argv)

    results = {node_id: _load_results(node_id) for node_id in NODES}
    py = sys.executable

    def run_script(name: str, *extra: str) -> None:
        cmd = [py, str(_common.PROJECT_DIR / "scripts" / name), "--db-dir", args.db_dir, *extra]
        print(f"$ {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

    if _common.load_state(args.db_dir) is None:
        run_script("setup_scenario.py")

    for tour in range(0, scenario.N_TOURS + 1):
        state = _common.load_state(args.db_dir)
        if state["last_tour"] >= tour:
            print(f"Tour {tour} déjà joué, on continue.")
            continue

        run_script("inject_tour.py", "--tour", str(tour))

        from supplyscore.core.ahp import bipolar_to_saaty, score_6_to_9
        from supplyscore.services.orchestrator import SupplyScoreService

        service = _common.open_service(args.db_dir)
        try:
            for node_id in NODES:
                row = results[node_id].get(tour)
                if row is None:
                    print(f"  [!] {node_id} : pas de réponse au tour {tour}, ignoré")
                    continue
                if row.get("cr_echec"):
                    print(f"  [cr_echec] {node_id} tour {tour} : report à l'identique")
                    continue
                v = row["bipolar"]
                comparisons = {
                    (0, 1): bipolar_to_saaty(v[0]),
                    (0, 2): bipolar_to_saaty(v[1]),
                    (0, 3): bipolar_to_saaty(v[2]),
                    (1, 2): bipolar_to_saaty(v[3]),
                    (1, 3): bipolar_to_saaty(v[4]),
                    (2, 3): bipolar_to_saaty(v[5]),
                }
                scores = [score_6_to_9(s) for s in row["scores_ui"]]
                assessment = SupplyScoreService.build_assessment(
                    node_id=node_id,
                    project_id=PROJECT_ID,
                    operator_id=_common.OPERATORS[node_id],
                    comparisons=comparisons,
                    criteria_scores=scores,
                    notes=row.get("note", ""),
                )
                service.submit_assessment(assessment)
                print(
                    f"  [ahp] {node_id} tour {tour} : "
                    f"Ud={assessment.ud:.3f} CR={assessment.consistency_ratio:.3f}"
                )
        finally:
            service.close()

        run_script("inject_tour.py", "--tour", str(tour), "--advance-only")

    print("\nCampagne pilote LLM injectée intégralement.")
    for node_id in NODES:
        debrief = results[node_id].get("debrief")
        if debrief:
            print(f"  [debrief] {node_id} : reconnu au tour {debrief.get('recognition_tour')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
