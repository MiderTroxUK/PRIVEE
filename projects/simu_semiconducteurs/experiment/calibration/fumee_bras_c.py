"""Test de fumee du bras C : la boucle fermee tourne-t-elle de bout en bout ?

Joue quelques tours du sous-bras ``act`` avec des reponses SCRIPTEES (aucun
appel LLM) et verifie que la plomberie tient :

- les fiches portent bien la section predictive ET la section « leviers » ;
- une action valide est appliquee et journalisee comme intervention ;
- une action dont la precondition est fausse est REFUSEE, pas appliquee ;
- un ``action_id`` inconnu est rejete a la lecture des reponses.

A lancer AVANT toute campagne avec personas LLM : il coute zero token et
attrape les erreurs de cablage que la campagne payante attraperait trop tard.

Usage : python fumee_bras_c.py <dossier_de_travail> [tour_max]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# La console Windows est en cp1252 : la sortie du harnais (accents, et le
# caractere de remplacement U+FFFD introduit par errors="replace") ne s'y
# encode pas. On force utf-8 plutot que de faire tomber le test sur un print.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(r"C:\PRIVEE\AZURE")
PY = REPO / ".venv" / "Scripts" / "python.exe"
CLI = REPO / "projects" / "simu_semiconducteurs" / "experiment" / "run_experiment.py"

NODES = [
    "orbitalys", "aviosys", "electis", "compodis",
    "transglobal", "novafab", "meridian", "silpure",
]

#: Reponse neutre : AHP coherent (tout a egalite) et scores medians.
BIPOLAIRE_NEUTRE = [0, 0, 0, 0, 0, 0]
SCORES_NEUTRES = [3, 3, 3, 3]

#: Action jouee par noeud a partir du tour 4. On melange volontairement des
#: leviers dont la precondition peut etre fausse : le refus doit etre TRACE,
#: jamais applique en silence.
ACTIONS = {
    "orbitalys": "replanifier_jalon",
    "aviosys": "expedition_express",
    "electis": "boost_capacite",
    "compodis": "ne_rien_faire",
    "transglobal": "promouvoir_arc_secours",
    "novafab": "boost_capacite",
    "meridian": "revue_declaration",
    "silpure": "ne_rien_faire",
}


def run(travail: Path, *args: str) -> str:
    """Lance une sous-commande du harnais et renvoie sa sortie standard."""
    proc = subprocess.run(
        [str(PY), str(CLI), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        (travail / "erreur.txt").write_text(
            f"COMMANDE: {' '.join(args)}\n\n--- STDOUT ---\n{proc.stdout}\n"
            f"--- STDERR ---\n{proc.stderr}",
            encoding="utf-8",
        )
        print(f"ECHEC : {' '.join(args[:2])}\n{(proc.stderr or proc.stdout)[-1200:]}")
        sys.exit(1)
    return proc.stdout


def reponse(node_id: str, tour: int) -> dict:
    """Reponse scriptee d'un persona, au format attendu par ``collect-tour``."""
    ligne = {
        "node_id": node_id,
        "bipolar": BIPOLAIRE_NEUTRE,
        "scores_ui": SCORES_NEUTRES,
        "attempts": 1,
        "note": f"reponse scriptee de fumee, tour {tour}",
        "influence_prediction": "aucune",
        "action_id": ACTIONS[node_id] if tour >= 4 else "ne_rien_faire",
        "objectif_action": "test de fumee du cablage bras C",
    }
    return ligne


def verifier_refus_objectif_vide(travail: Path, db: Path, out: Path) -> None:
    """Un objectif d'action vide doit etre REFUSE en phase de validation.

    ``InterventionJournal.record`` leve un ValueError sur un objectif vide.
    Si ce controle n'arrive qu'au moment d'agir, il survient APRES que les
    premiers noeuds ont deja ete soumis en base : le tour reste a moitie
    declare, ce que l'atomicite en deux phases promet d'eviter.
    """
    answers = travail / "answers_invalide.jsonl"
    lignes = []
    for node in NODES:
        ligne = reponse(node, 4)
        if node == "silpure":  # dernier de la liste : le pire cas
            ligne["action_id"] = "expedition_express"
            ligne["objectif_action"] = "   "
        lignes.append(json.dumps(ligne, ensure_ascii=False))
    answers.write_text("\n".join(lignes), encoding="utf-8")
    proc = subprocess.run(
        [str(PY), str(CLI), "collect-tour", "--arm", "act", "--db-dir", str(db),
         "--tour", "4", "--answers", str(answers), "--out", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    sortie = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        print("ECHEC : un objectif_action vide a ete ACCEPTE")
        sys.exit(1)
    if "Traceback" in sortie:
        print(f"ECHEC : plantage brut au lieu d'un refus propre\n{sortie[-800:]}")
        sys.exit(1)
    if "objectif_action" not in sortie:
        print(f"ECHEC : refus sans message explicite\n{sortie[-400:]}")
        sys.exit(1)
    print("  refus propre d'un objectif_action vide : OK")


def main() -> None:
    """Joue la campagne de fumee et resume ce qui a ete applique."""
    travail = Path(sys.argv[1])
    tour_max = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    travail.mkdir(parents=True, exist_ok=True)
    db, out = travail / "db", travail / "out"

    run(travail, "init", "--arm", "act", "--db-dir", str(db))
    run(travail, "make-sandboxes", "--arm", "act", "--out", str(out))

    appliquees: list[str] = []
    refusees: list[str] = []
    for tour in range(tour_max + 1):
        run(travail, "prepare-tour", "--arm", "act", "--db-dir", str(db),
            "--out", str(out), "--tour", str(tour))
        answers = travail / f"answers_{tour:02d}.jsonl"
        answers.write_text(
            "\n".join(json.dumps(reponse(n, tour), ensure_ascii=False) for n in NODES),
            encoding="utf-8",
        )
        sortie = run(travail, "collect-tour", "--arm", "act", "--db-dir", str(db),
                     "--tour", str(tour), "--answers", str(answers), "--out", str(out))
        # Detection sur le marqueur ASCII « [action] » : les accents ne
        # survivent pas toujours au reencodage de la sortie sous-processus.
        for ligne in sortie.splitlines():
            if "[action]" not in ligne:
                continue
            (appliquees if "APPLIQU" in ligne.upper() else refusees).append(
                f"T{tour} {ligne.strip()}"
            )
        run(travail, "close-tour", "--arm", "act", "--db-dir", str(db),
            "--out", str(out), "--tour", str(tour))
        print(f"  tour {tour} joue", flush=True)

    verifier_refus_objectif_vide(travail, db, out)

    print(f"\nActions APPLIQUEES : {len(appliquees)}")
    for ligne in appliquees:
        print(f"  {ligne}")
    print(f"\nActions REFUSEES : {len(refusees)}")
    for ligne in refusees:
        print(f"  {ligne}")

    # La section « leviers » doit figurer dans les instructions du bac a sable.
    instructions = (out / "sandbox_novafab" / "INSTRUCTIONS.md")
    if instructions.is_file():
        texte = instructions.read_text(encoding="utf-8")
        print(f"\nsection leviers dans INSTRUCTIONS.md : {'Vos leviers' in texte}")
        print(f"section predictive dans INSTRUCTIONS.md : {'ANALYSE PRÉDICTIVE' in texte}")
        print(f"cle action_id documentee : {'action_id' in texte}")

    fiche = out / "sandbox_novafab" / "fiche_tour_06.md"
    if fiche.is_file():
        print(f"analyse predictive dans la fiche T6 : "
              f"{'ANALYSE PRÉDICTIVE' in fiche.read_text(encoding='utf-8')}")

    print(f"\nFUMEE OK -> {out}")


if __name__ == "__main__":
    main()
