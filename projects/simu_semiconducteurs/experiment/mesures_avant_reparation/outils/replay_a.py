"""Rejeu du bras A (pilote LLM) dans le harnais, avec journalisation des previsions.

Aucun appel LLM : on rejoue les reponses DEJA enregistrees du pilote
(analysis/llm_pilot_run/sandbox_<node>/results.jsonl) a travers le harnais en
mode ``control`` — les previsions sont donc calculees et journalisees a chaque
tour, mais jamais montrees (ce qui est exactement la condition du bras A).

Usage : python replay_a.py <dossier_de_travail> [tour_max]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(r"C:\PRIVEE\AZURE")
PY = REPO / ".venv" / "Scripts" / "python.exe"
CLI = REPO / "projects" / "simu_semiconducteurs" / "experiment" / "run_experiment.py"
PILOTE = REPO / "projects" / "simu_semiconducteurs" / "analysis" / "llm_pilot_run"

NODES = ["orbitalys", "aviosys", "electis", "compodis", "transglobal",
         "novafab", "meridian", "silpure"]

WORK = Path(sys.argv[1])
TOUR_MAX = int(sys.argv[2]) if len(sys.argv) > 2 else 18
DB = WORK / "db"
OUT = WORK / "out"


def run(*args: str) -> None:
    res = subprocess.run(
        [str(PY), str(CLI), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if res.returncode != 0:
        (WORK / "erreur.txt").write_text(
            f"COMMANDE: {' '.join(args)}\n\n--- STDOUT ---\n{res.stdout}\n"
            f"--- STDERR ---\n{res.stderr}",
            encoding="utf-8",
        )
        sys.stdout.write(f"ECHEC: {' '.join(args[:3])} tour={args[args.index('--tour') + 1]}\n")
        sys.exit(1)


def charger_pilote() -> dict[str, dict[int, dict]]:
    """{node: {tour: ligne}} depuis les results.jsonl du pilote (lecture seule)."""
    data: dict[str, dict[int, dict]] = {}
    for node in NODES:
        path = PILOTE / f"sandbox_{node}" / "results.jsonl"
        par_tour: dict[int, dict] = {}
        for ligne in path.read_text(encoding="utf-8").splitlines():
            ligne = ligne.strip()
            if not ligne:
                continue
            row = json.loads(ligne)
            if isinstance(row.get("tour"), int):  # ignore la ligne "debrief"
                par_tour[row["tour"]] = row
        data[node] = par_tour
    return data


def main() -> None:
    pilote = charger_pilote()
    dispo = min(max(t.keys()) for t in pilote.values())
    tour_max = min(TOUR_MAX, dispo)
    print(f"pilote charge : tours 0..{dispo} pour {len(NODES)} noeuds ; rejeu jusqu'a {tour_max}")

    run("init", "--arm", "control", "--db-dir", str(DB))
    for tour in range(0, tour_max + 1):
        run("prepare-tour", "--arm", "control", "--db-dir", str(DB),
            "--tour", str(tour), "--out", str(OUT), "--n-draws", "500")

        rep = WORK / f"answers_{tour:02d}.jsonl"
        with rep.open("w", encoding="utf-8") as fh:
            for node in NODES:
                src = pilote[node][tour]
                fh.write(json.dumps({
                    "node_id": node,
                    "bipolar": src["bipolar"],
                    "scores_ui": src["scores_ui"],
                    "note": src.get("note", ""),
                }, ensure_ascii=False) + "\n")

        run("collect-tour", "--arm", "control", "--db-dir", str(DB),
            "--tour", str(tour), "--answers", str(rep), "--out", str(OUT))
        run("close-tour", "--arm", "control", "--db-dir", str(DB),
            "--tour", str(tour), "--out", str(OUT))
        print(f"  tour {tour} rejoue")

    log = OUT / "predictions_log.jsonl"
    n = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
    print(f"\nREJEU TERMINE — {n} previsions journalisees dans {log}")


if __name__ == "__main__":
    main()
