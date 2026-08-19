"""Fait DECOULER la verite jalon de la trajectoire des KPI du pack.

## Le probleme

Dans le pack officiel, l'avancement des jalons et le tour ou ils passent
« termine » sont ECRITS a la main (``MILESTONE_DRIFT``, ``MILESTONE_DONE`` dans
``scenario.py``). La verite terrain ne DECOULE donc pas de l'etat de la chaine :
on peut degrader le lead time d'un fournisseur autant qu'on veut, ses jalons
tombent quand meme aux dates prevues. Mesure a l'appui — un pack ou deux
fournisseurs derivent sans que la verite en tienne compte score PLUS MAL,
parce qu'on a fabrique des faux positifs et que le scoreur les compte.

Consequence : impossible de tester « un fournisseur prend du retard, que se
passe-t-il ? » sur ce pack. C'est ce que ce module repare.

## La regle

Pour un jalon partant au tour ``s`` avec echeance d'origine ``d``, le rythme
NOMINAL vaut ``r0 = 1 / (d - s)`` par tour : un noeud en bonne sante atteint
exactement 1,0 au tour ``d``, ni avant ni apres. La sante du tour module ce
rythme :

    progres_t = min(progres_{t-1} + r0 x sante_t, 1)

    sante_t = clip( (L0 / Lt) x (OEE_t / OEE_0) x (1 - perte_t), 0, PLAFOND )

ou ``Lt`` est le lead time courant du noeud, ``OEE`` le produit disponibilite x
performance x qualite, et ``perte_t`` la part de la semaine perdue en arrets.
Chaque facteur vaut 1 au nominal, donc ``sante = 1`` reproduit exactement le
comportement nominal : la regle est calibree par construction, sans constante
ajustee.

Un fournisseur dont le lead time double avance deux fois moins vite et rate son
echeance. C'est la physique qu'on voulait, et elle est desormais LA verite.

## Ce que le module ecrit

- ``milestones_NN.json`` recalcules dans le pack ;
- ``VERITE.json`` : par jalon, l'echeance d'origine et le tour d'achevement
  reel (ou ``null``), plus la trajectoire d'avancement. C'est le fichier que
  ``banc.py --verite`` lit pour scorer, au lieu de ``scenario.py``.

Aucune replanification n'est emise : replanifier est une DECISION, pas une
physique. Echeance contractuelle et echeance courante coincident donc dans un
pack derive, ce qui supprime au passage l'ambiguite de cible.

Usage :
    python verite_derivee.py <dossier_pack> [--tours 18] [--plafond 1.0]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

REPO = Path(r"C:\PRIVEE\AZURE")


def _dossier_scenario() -> Path:
    """Dossier ``scenario/`` du projet a traiter.

    ``SUPPLYSCORE_PROJET_DIR`` designe le projet ; sans lui, HELIOS. Sans cette
    resolution, l'outil chargeait toujours le scenario d'HELIOS et derivait donc
    la verite d'un projet a partir des jalons d'un autre — silencieusement.
    """
    brut = os.environ.get("SUPPLYSCORE_PROJET_DIR")
    if not brut:
        return REPO / "projects" / "simu_semiconducteurs" / "scenario"
    dossier = Path(brut)
    if not dossier.is_absolute():
        dossier = REPO / dossier
    return dossier / "scenario"


sys.path.insert(0, str(_dossier_scenario()))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import scenario  # noqa: E402

#: Heures moteur d'une semaine de jeu.
WEEK_HOURS: float = 168.0

#: Facteurs entrant dans la sante, et leur sens de lecture.
OEE_CHAMPS = ("oee.availability", "oee.performance", "oee.quality")


def etat_kpi(pack: Path, tours: int) -> dict[int, dict[str, dict[str, float]]]:
    """Etat KPI COURANT de chaque noeud a chaque tour.

    Les ``tour_NN.csv`` ne portent que les valeurs qui CHANGENT ; l'etat courant
    est donc le socle du scenario, ecrase au fil des tours par ce qui a ete
    ecrit. Reproduire cette accumulation ici est ce qui permet de lire le lead
    time reellement en vigueur au tour t.

    Args:
        pack: dossier du pack de donnees.
        tours: dernier tour inclus.

    Returns:
        ``{tour: {node_id: {kpi_path: valeur}}}``.
    """
    courant = {n: dict(kpis) for n, kpis in scenario.BASELINE_KPIS.items()}
    par_tour: dict[int, dict[str, dict[str, float]]] = {}
    for tour in range(tours + 1):
        chemin = pack / f"tour_{tour:02d}.csv"
        if chemin.is_file():
            for ligne in csv.DictReader(chemin.read_text(encoding="utf-8").splitlines()):
                node, cle, valeur = ligne["node_id"], ligne["kpi_path"], ligne["valeur"]
                if valeur not in ("", None):
                    courant.setdefault(node, {})[cle] = float(valeur)
        par_tour[tour] = {n: dict(k) for n, k in courant.items()}
    return par_tour


def perte_semaine(pack: Path, tour: int) -> dict[str, float]:
    """Part de la semaine perdue par noeud, depuis les evenements d'arret.

    Seuls les evenements portant une ``duree_arret_h`` retirent des heures de
    production. Un pack sans evenement rend un dictionnaire vide, donc aucune
    perte, ce qui est exactement la definition d'une degradation endogene.
    """
    chemin = pack / f"events_{tour:02d}.json"
    if not chemin.is_file():
        return {}
    pertes: dict[str, float] = {}
    for ev in json.loads(chemin.read_text(encoding="utf-8")):
        duree = ev.get("params", {}).get("duree_arret_h")
        if duree:
            pertes[ev["node"]] = pertes.get(ev["node"], 0.0) + float(duree)
    return {n: min(h / WEEK_HOURS, 1.0) for n, h in pertes.items()}


def sante(kpis: dict[str, float], socle: dict[str, float], perte: float,
          plafond: float) -> float:
    """Facteur multiplicatif du rythme nominal, 1,0 au nominal.

    Args:
        kpis: etat KPI courant du noeud.
        socle: etat KPI de reference du meme noeud.
        perte: part de la semaine perdue en arrets, dans [0, 1].
        plafond: borne haute (un noeud ne rattrape pas indefiniment).

    Returns:
        La sante du tour, dans ``[0, plafond]``.
    """
    lead_0, lead_t = socle.get("time.lead_time_h"), kpis.get("time.lead_time_h")
    f_lead = 1.0
    if lead_0 and lead_t and lead_t > 0:
        f_lead = lead_0 / lead_t

    oee_0 = oee_t = 1.0
    for champ in OEE_CHAMPS:
        if socle.get(champ) is not None and kpis.get(champ) is not None:
            oee_0 *= float(socle[champ])
            oee_t *= float(kpis[champ])
    f_oee = (oee_t / oee_0) if oee_0 > 0 else 1.0

    return max(0.0, min(f_lead * f_oee * (1.0 - perte), plafond))


def deriver(pack: Path, tours: int, plafond: float) -> dict:
    """Recalcule l'avancement de chaque jalon et ecrit la verite du pack."""
    etats = etat_kpi(pack, tours)
    pertes = {t: perte_semaine(pack, t) for t in range(tours + 1)}
    socle = scenario.BASELINE_KPIS

    verite: dict[str, dict] = {}
    par_tour: dict[int, list[dict]] = {t: [] for t in range(tours + 1)}

    for node, nom, _kind, debut, echeance in scenario.MILESTONES:
        duree = max(echeance - debut, 1)
        rythme = 1.0 / duree
        progres = 0.0
        acheve: int | None = None
        trajectoire: dict[int, float] = {}
        for tour in range(tours + 1):
            if tour < debut:
                trajectoire[tour] = 0.0
                par_tour[tour].append({"node": node, "name": nom, "progress": 0.0})
                continue
            s = sante(etats[tour].get(node, {}), socle.get(node, {}),
                      pertes[tour].get(node, 0.0), plafond)
            if tour > debut:  # le tour de depart ne fait pas avancer
                progres = min(progres + rythme * s, 1.0)
            trajectoire[tour] = progres
            entree = {"node": node, "name": nom, "progress": round(progres, 4)}
            if progres >= 1.0 - 1e-9:
                entree["status"] = "done"
                if acheve is None:
                    acheve = tour
            par_tour[tour].append(entree)
        verite[f"{node}|{nom}"] = {
            "node_id": node, "name": nom, "debut": debut,
            "echeance_origine": echeance, "acheve_au_tour": acheve,
            "rate": acheve is None or acheve > echeance,
            "observable": echeance <= tours,
            "trajectoire": {str(t): round(v, 4) for t, v in trajectoire.items()},
        }

    for tour, entrees in par_tour.items():
        (pack / f"milestones_{tour:02d}.json").write_text(
            json.dumps(entrees, ensure_ascii=False, indent=2), encoding="utf-8")

    manifeste = {
        "source": "verite_derivee.py",
        "regle": "progres_t = min(progres_{t-1} + sante_t / (echeance - debut), 1)",
        "plafond_sante": plafond,
        "tours": tours,
        "jalons": verite,
    }
    (pack / "VERITE.json").write_text(json.dumps(manifeste, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    return manifeste


def main() -> None:
    """Derive la verite du pack demande et resume ce qui rate."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pack", type=Path)
    ap.add_argument("--tours", type=int, default=18)
    ap.add_argument("--plafond", type=float, default=1.0,
                    help="borne haute de la sante (1.0 = pas de rattrapage)")
    args = ap.parse_args()

    manifeste = deriver(args.pack, args.tours, args.plafond)
    observables = [j for j in manifeste["jalons"].values() if j["observable"]]
    rates = [j for j in observables if j["rate"]]
    print(f"\nverite derivee : {len(manifeste['jalons'])} jalons, "
          f"{len(observables)} observables dans la campagne")
    print(f"{'noeud':<12} {'jalon':<34} {'ech.':>5} {'acheve':>7}  verdict")
    for j in observables:
        acheve = "jamais" if j["acheve_au_tour"] is None else f"T{j['acheve_au_tour']}"
        print(f"  {j['node_id']:<12} {j['name'][:33]:<34} {j['echeance_origine']:>5} "
              f"{acheve:>7}  {'RATE' if j['rate'] else 'tenu'}")
    print(f"\n{len(rates)} rates sur {len(observables)} observables")
    print(f"-> {args.pack / 'VERITE.json'}")


if __name__ == "__main__":
    main()
