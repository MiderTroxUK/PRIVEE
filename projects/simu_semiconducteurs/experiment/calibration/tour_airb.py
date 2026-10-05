"""Pilote un tour de campagne AIRB : prepare, puis collecte et clot.

Decoupe le tour en deux commandes pour laisser le coordinateur intercaler les
declarants entre les deux :

    python tour_airb.py preparer <travail> <tour>   -> fiches par noeud
    ... les personas ecrivent dans <travail>/reponses/<node>.jsonl ...
    python tour_airb.py cloturer <travail> <tour>   -> collecte + cloture

Le bras est choisi automatiquement : ``control`` tant que la prevision n'est pas
montree, ``predict`` ensuite. C'est le protocole, pas une commodite — le champ
``influence_prediction`` n'a de sens que si une prevision a ete affichee.

## Regle anti-contamination, enfreinte une fois dans cette campagne

Un persona ne recoit RIEN du coordinateur au-dela de sa carte de role. Tout
retour de l'outil — un controle de coherence echoue, par exemple — passe par un
fichier ecrit dans SON dossier, qu'il lit comme il lirait l'ecran de son
application. Le glisser dans le message de relance, comme cela a ete fait une
fois au tour 1 pour TransLog, revient a lui donner une information qu'aucun
operateur reel n'aurait recue de cette facon : la declaration cesse d'etre un
jugement autonome et le tour est contamine.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(r"C:\PRIVEE\AZURE")
PY = REPO / ".venv" / "Scripts" / "python.exe"
CLI = REPO / "projects" / "simu_semiconducteurs" / "experiment" / "run_experiment.py"
COLLECTE = REPO / "projects/simu_semiconducteurs/experiment/calibration/collecte_personas.py"

NODES = ("airb_fal", "aerostruct", "voilure", "sysintegra", "propulsia", "avionia",
         "atterral", "cabinova", "compolam", "usiforge", "harnetec", "hydralec",
         "titanor", "fibrelia", "translog")

#: Bras de la campagne, fixe pour toute sa duree : le harnais refuse de melanger
#: deux bras sur une meme base (« un db-dir par bras »), garde-fou correct qu'il
#: n'y a aucune raison de contourner. UN BRAS, UNE BASE, UN DOSSIER DE TRAVAIL.
#:
#: ``control``  la prevision est calculee et journalisee a chaque tour, jamais
#:              affichee. La declaration est donc independante de ce qu'on
#:              score.
#: ``predict``  la prevision est MONTREE au declarant des qu'elle existe (tour 4
#:              ici), et chaque declaration porte en plus ``influence_prediction``.
#:
#: Le second bras ne detruit pas la reference : sur AIRB le terrain KPI est pose
#: par le scenario et ne repond ni aux declarations ni aux actions, donc la
#: verite jalon derivee est LA MEME dans les deux bras. Ce qui change est la
#: declaration — et c'est precisement l'effet qu'on veut mesurer.
#:
#: Aux tours 0 a 3 aucune prevision n'existe encore. La fiche le dit au
#: declarant (« rien a en tirer ce tour-ci ») tout en lui demandant le champ :
#: « aucune » est alors la reponse juste, pas un pis-aller.
BRAS_CAMPAGNE = os.environ.get("SUPPLYSCORE_BRAS", "control")

#: Corps du retour de l'application quand la coherence echoue. Ecrit tel quel
#: dans le dossier du declarant : c'est l'outil qui parle, pas le coordinateur.
_RETOUR_COHERENCE = """# Retour de l'application — tour {tour}

Votre questionnaire n'a pas passe le controle de coherence : **CR = {cr:.3f}**
pour un seuil d'acceptation de 0,10.

Un CR au-dessus du seuil signifie que vos six jugements se contredisent entre
eux : pris deux a deux, ils decrivent des priorites qui ne peuvent pas
coexister. Ce n'est pas une erreur de fond, c'est une question d'echelle — vos
ecarts sont probablement plus tranches que ce que l'ensemble supporte.

Vous pouvez reduire l'amplitude de vos comparaisons, ou verifier la
transitivite : si A compte plus que B et B plus que C, alors A doit dominer C
d'autant plus, pas moins.
"""


def env() -> dict[str, str]:
    """Environnement du harnais : projet AIRB, horizon 8 semaines.

    ``SUPPLYSCORE_PACK_DIR`` est transmis tel quel s'il est pose : les deux bras
    d'une comparaison DOIVENT tourner sur le meme pack, faute de quoi l'ecart
    mesure melange l'effet du bras et celui du terrain.
    """
    variables = dict(os.environ)
    variables["SUPPLYSCORE_PROJET_DIR"] = "projects/airb"
    variables["SUPPLYSCORE_HORIZON_PREVISION"] = "8"
    return variables


def bras(tour: int) -> str:
    """Bras de la campagne — temoin du debut a la fin (cf. BRAS_CAMPAGNE)."""
    del tour  # le bras ne depend pas du tour : c'est le point
    return BRAS_CAMPAGNE


def run(travail: Path, *args: str) -> str:
    """Lance une sous-commande ; ecrit la trace et sort en erreur si elle echoue."""
    proc = subprocess.run([str(PY), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env(), cwd=REPO)
    if proc.returncode != 0:
        (travail / "erreur.txt").write_text(
            f"{' '.join(args)}\n\n{proc.stdout}\n{proc.stderr}", encoding="utf-8")
        print(f"ECHEC : {' '.join(args[1:3])}\n{(proc.stderr or proc.stdout)[-1200:]}")
        raise SystemExit(1)
    return proc.stdout


#: Ligne que le harnais imprime quand un questionnaire echoue au controle AHP :
#:   ``  [cr_echec] hydralec : tour 9 « control » report (CR = 0.116 >= 0.10) ...``
#: C'est la SEULE trace de l'echec — le harnais n'ecrit aucun fichier — donc le
#: canal de retour vers le declarant doit la lire ici, sans quoi il reste vide.
_CR_ECHEC = re.compile(r"\[cr_echec\]\s*(?P<node>[\w-]+)\s*:.*?CR\s*=\s*(?P<cr>[0-9.]+)")


def relever_echecs_coherence(sortie: str, travail: Path, tour: int) -> dict[str, dict]:
    """Extrait les echecs de coherence de la sortie du harnais et les journalise.

    Args:
        sortie: sortie de ``collect-tour``.
        travail: dossier de campagne.
        tour: tour collecte.

    Returns:
        ``{node: {"cr": float}}``, ecrit tel quel dans ``out/coherence_NN.json``
        pour que ``ecrire_retour_outil`` le retrouve au tour suivant.
    """
    echecs = {m.group("node"): {"cr": float(m.group("cr"))}
              for m in _CR_ECHEC.finditer(sortie)}
    if echecs:
        (travail / "out").mkdir(parents=True, exist_ok=True)
        (travail / "out" / f"coherence_{tour:02d}.json").write_text(
            json.dumps(echecs, ensure_ascii=False, indent=2), encoding="utf-8")
    return echecs


def ecrire_retour_outil(travail: Path, tour: int) -> list[str]:
    """Depose le retour de l'application dans le dossier des noeuds concernes.

    Args:
        travail: dossier de campagne.
        tour: tour a preparer ; le retour porte sur ``tour - 1``.

    Returns:
        Les noeuds pour lesquels un retour a ete ecrit.
    """
    if tour == 0:
        return []
    erreurs = travail / "out" / f"coherence_{tour - 1:02d}.json"
    if not erreurs.is_file():
        return []
    ecrits: list[str] = []
    for node, detail in json.loads(erreurs.read_text(encoding="utf-8")).items():
        dossier = travail / "retours" / node
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f"retour_tour_{tour - 1:02d}.md").write_text(
            _RETOUR_COHERENCE.format(tour=tour - 1, cr=float(detail.get("cr", float("nan")))),
            encoding="utf-8")
        ecrits.append(node)
    return ecrits


def preparer(travail: Path, tour: int) -> None:
    """Prepare le tour, depose les retours de l'outil, et resume."""
    arm = bras(tour)
    if tour == 0:
        run(travail, str(CLI), "init", "--arm", arm, "--db-dir", str(travail / "db"))
    sortie = run(travail, str(CLI), "prepare-tour", "--arm", arm,
                 "--db-dir", str(travail / "db"), "--tour", str(tour),
                 "--out", str(travail / "out"), "--n-draws", "500")
    print(sortie.rstrip()[-300:])
    print(f"\nTOUR {tour} PRET — bras « {arm} », {len(NODES)} fiches dans "
          f"{travail / 'out' / f'tour_{tour:02d}'}")
    retours = ecrire_retour_outil(travail, tour)
    if retours:
        print(f"Retour de l'application depose pour : {', '.join(retours)}")
        print("Ces noeuds lisent retours/<node>/retour_tour_NN.md EN PLUS de leur fiche.")


def cloturer(travail: Path, tour: int) -> None:
    """Assemble les declarations, collecte et clot le tour."""
    arm = bras(tour)
    answers = travail / f"answers_{tour:02d}.jsonl"
    exige = ["--exige", "influence_prediction"] if arm in ("predict", "act") else []
    print(run(travail, str(COLLECTE), str(travail / "reponses"), str(tour), str(answers),
              "--noeuds", ",".join(NODES), *exige).rstrip())
    collecte = run(travail, str(CLI), "collect-tour", "--arm", arm,
                   "--db-dir", str(travail / "db"), "--tour", str(tour),
                   "--answers", str(answers), "--out", str(travail / "out"))
    print(collecte.rstrip()[-400:])
    echecs = relever_echecs_coherence(collecte, travail, tour)
    if echecs:
        print(f"Coherence refusee pour : {', '.join(sorted(echecs))} — "
              f"retour depose a la preparation du tour {tour + 1}")
    print(run(travail, str(CLI), "close-tour", "--arm", arm,
              "--db-dir", str(travail / "db"), "--tour", str(tour),
              "--out", str(travail / "out")).rstrip()[-200:])
    journal = travail / "out" / "predictions_log.jsonl"
    n = len(journal.read_text(encoding="utf-8").splitlines()) if journal.is_file() else 0
    print(f"TOUR {tour} CLOS — {n} previsions journalisees au total")


def main() -> None:
    """Point d'entree : ``preparer`` ou ``cloturer``."""
    if len(sys.argv) != 4 or sys.argv[1] not in ("preparer", "cloturer"):
        raise SystemExit(__doc__)
    action, travail, tour = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
    travail.mkdir(parents=True, exist_ok=True)
    (preparer if action == "preparer" else cloturer)(travail, tour)


if __name__ == "__main__":
    main()
