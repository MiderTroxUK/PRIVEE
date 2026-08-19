"""Rejeu d'un bras LLM dans le harnais, avec journalisation des previsions.

Generalise ``mesures_avant_reparation/outils/replay_a.py`` a n'importe quel jeu
de declarations deja enregistrees et a n'importe quel bras du harnais. Aucun
appel LLM : les reponses sont relues telles quelles, seul le MODELE change
d'une execution a l'autre. C'est ce qui rend deux rejeux comparables.

Usage :
    python rejeu_bras.py <dossier_travail> <source_declarations> <arm> [tour_max]

    <source_declarations> contient soit ``sandbox_<node>/results.jsonl``
    (format pilote), soit ``results_<node>.jsonl`` (format bras B).
    <arm> vaut ``control`` (prevision calculee, jamais montree) ou ``predict``
    (prevision montree au declarant).

Variables d'environnement honorees par le modele, utiles aux balayages :
``SUPPLYSCORE_SIGMA_AVANCEMENT``, ``SUPPLYSCORE_LAMBDA_ARRET``,
``SUPPLYSCORE_RATTRAPAGE_HEBDO``, ``SUPPLYSCORE_COUT_CHOC_SEMAINE``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(r"C:\PRIVEE\AZURE")
PY = REPO / ".venv" / "Scripts" / "python.exe"
CLI = REPO / "projects" / "simu_semiconducteurs" / "experiment" / "run_experiment.py"

NODES = ("orbitalys", "aviosys", "electis", "compodis",
         "transglobal", "novafab", "meridian", "silpure")


def charger(source: Path) -> dict[str, dict[int, dict]]:
    """``{node: {tour: declaration}}`` depuis l'un ou l'autre format de dossier."""
    data: dict[str, dict[int, dict]] = {}
    for node in NODES:
        candidats = [source / f"sandbox_{node}" / "results.jsonl",
                     source / f"results_{node}.jsonl"]
        chemin = next((c for c in candidats if c.is_file()), None)
        if chemin is None:
            raise SystemExit(f"declarations introuvables pour {node} sous {source}")
        par_tour: dict[int, dict] = {}
        for ligne in chemin.read_text(encoding="utf-8-sig").splitlines():
            ligne = ligne.strip()
            if not ligne:
                continue
            row = json.loads(ligne)
            if isinstance(row.get("tour"), int):  # ignore la ligne de debrief
                par_tour[row["tour"]] = row
        data[node] = par_tour
    return data


def main() -> None:
    """Rejoue le bras demande et rapporte le nombre de previsions journalisees."""
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    travail, source, arm = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    tour_max_voulu = int(sys.argv[4]) if len(sys.argv) > 4 else 18
    db, out = travail / "db", travail / "out"
    travail.mkdir(parents=True, exist_ok=True)

    def run(*args: str) -> None:
        proc = subprocess.run([str(PY), str(CLI), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            (travail / "erreur.txt").write_text(
                f"COMMANDE: {' '.join(args)}\n\n{proc.stdout}\n{proc.stderr}",
                encoding="utf-8")
            raise SystemExit(f"ECHEC {' '.join(args[:2])}\n{(proc.stderr or proc.stdout)[-1200:]}")

    declarations = charger(source)
    dispo = min(max(t) for t in declarations.values())
    tour_max = min(tour_max_voulu, dispo)
    print(f"{len(NODES)} noeuds, tours 0..{dispo} disponibles ; rejeu bras '{arm}' jusqu'a {tour_max}")

    run("init", "--arm", arm, "--db-dir", str(db))
    for tour in range(tour_max + 1):
        run("prepare-tour", "--arm", arm, "--db-dir", str(db),
            "--tour", str(tour), "--out", str(out), "--n-draws", "500")
        reponses = travail / f"answers_{tour:02d}.jsonl"
        with reponses.open("w", encoding="utf-8") as flux:
            for node in NODES:
                src = declarations[node][tour]
                ligne = {"node_id": node, "bipolar": src["bipolar"],
                         "scores_ui": src["scores_ui"], "note": src.get("note", "")}
                if arm == "predict" and "influence_prediction" in src:
                    ligne["influence_prediction"] = src["influence_prediction"]
                flux.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        run("collect-tour", "--arm", arm, "--db-dir", str(db),
            "--tour", str(tour), "--answers", str(reponses), "--out", str(out))
        run("close-tour", "--arm", arm, "--db-dir", str(db),
            "--tour", str(tour), "--out", str(out))
        print(f"  tour {tour} rejoue", flush=True)

    journal = out / "predictions_log.jsonl"
    n = len(journal.read_text(encoding="utf-8").splitlines()) if journal.exists() else 0
    print(f"\nTERMINE — {n} previsions dans {journal}")


if __name__ == "__main__":
    main()
