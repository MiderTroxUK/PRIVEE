"""Predicteur TRIVIAL, pour savoir ce que la couche Monte-Carlo apporte.

## Pourquoi ce script existe

Sur AIRB, enrichir deux blocs d'urgence a fait bouger ``ur_local`` sur 174 des
285 couples (tour, noeud) SANS deplacer ``p_issue`` d'un millieme. La lecture du
coeur explique pourquoi. Dans la boucle de simulation de ``forecast.py`` :

    jalon_cum |= (deadlines <= t_k) & (completion > deadlines)
    issue      = jalon_cum | evenement_cum

``completion`` ne depend que du lead time tire et de la part restante du jalon.
L'AR(1) ajuste sur ``ur_local`` (``etat.x_ar``) n'alimente que ``x_evt``, donc
seulement ``p_impact_client`` — il n'entre JAMAIS dans ``issue``. Sur une chaine
sans evenement exogene, ``p_issue`` se reduit donc a un modele de lead time.

Ce script en tire la consequence TESTABLE : si c'est vrai, un predicteur d'une
ligne, fonde sur le seul rapport « temps qu'il reste / travail qu'il reste »,
doit egaler 500 trajectoires Monte-Carlo. S'il les egale, la couche n'apporte
rien SUR CETTE CIBLE ET CETTE CHAINE. Si elle le bat, elle apporte quelque
chose et il faut chercher ailleurs.

## Le predicteur

Pour un noeud dont le prochain jalon non acheve a l'echeance ``D`` (en tours) et
dont il reste la fraction ``r`` a produire, avec un lead time nominal ``L``
converti en tours :

    marge(k) = (D - (t + k)) / max(r * L, eps)
    p(k)     = clip(1 - marge, 0, 1)

Proche de 1 quand il reste moins de temps que de travail, proche de 0 quand la
marge est large. Aucun parametre ajuste, aucun tirage, aucune calibration.
C'est la borne basse honnete.

Sortie au format ``predictions_log.jsonl`` du harnais, scorable telle quelle par
``banc.py --pack`` contre la MEME verite.

## Deux variantes, pour lever une objection

``--mode sante`` (defaut) lit la part restante dans ``trajectoire``, la variable
d'etat dont la verite est elle-meme derivee. Elle ne regarde aucun tour futur,
mais elle lit la MEME grandeur que le label — un avantage d'information dont il
faut savoir s'il porte le resultat.

``--mode calendrier`` ne lit rien du tout : la part restante y vaut
``1 - (t - debut) / (echeance - debut)``, c'est-a-dire l'avancement qu'aurait un
jalon parfaitement sain. Aucun KPI, aucune trajectoire. Si cette variante-la
egale encore le Monte-Carlo, l'objection tombe.

Usage :
    python temoin_trivial.py <pack_dir> <journal_reference.jsonl> <sortie.jsonl>
                             [--mode sante|calendrier]

``journal_reference`` sert a ne predire QUE les couples (tour, noeud) que le
harnais a produits, ET a ne rien predire la ou le harnais lui-meme s'est tu
(``p_issue`` a ``null`` quand le noeud n'a plus de jalon en cours). Sans cet
alignement la comparaison porterait sur deux echantillons differents — 210
points contre 151 a une semaine — et ne voudrait rien dire.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(r"C:\PRIVEE\AZURE")
sys.path.insert(0, str(REPO / "projects" / "airb" / "scenario"))

import scenario  # noqa: E402

#: Horizons produits, alignes sur ceux du harnais.
HORIZONS = range(1, 9)

#: Heures par tour, pour convertir un lead time en tours.
HEURES_PAR_TOUR = 168.0

#: Garde-fou de division : un jalon sans travail restant n'est pas en risque.
_EPS = 1e-9


def couples_scorables(journal: Path) -> dict[tuple[int, str], set[int]]:
    """``{(tour, node_id): {horizons ou la reference a REELLEMENT prevu}}``.

    Un horizon absent de l'ensemble est un horizon ou le harnais a ecrit
    ``null``. Le temoin s'y tait aussi, faute de quoi il serait score sur des
    points que son concurrent ne voit pas.
    """
    par_couple: dict[tuple[int, str], set[int]] = {}
    for brute in journal.read_text(encoding="utf-8").splitlines():
        if not brute.strip():
            continue
        ligne = json.loads(brute)
        cle = (int(ligne["tour"]), ligne["node_id"])
        par_couple[cle] = {k for k in HORIZONS if ligne.get(f"p_issue_h{k}") is not None}
    return par_couple


def lead_times(pack: Path, tour: int) -> dict[str, float]:
    """Lead time en heures par noeud a ce tour, socle du scenario en repli."""
    valeurs = {n: float(k["time.lead_time_h"]) for n, k in scenario.BASELINE_KPIS.items()}
    chemin = pack / f"tour_{tour:02d}.csv"
    if chemin.is_file():
        with chemin.open(encoding="utf-8", newline="") as flux:
            for ligne in csv.DictReader(flux):
                if ligne["kpi_path"] == "time.lead_time_h":
                    valeurs[ligne["node_id"]] = float(ligne["valeur"])
    return valeurs


def jalon_actif(verite: dict, node_id: str, tour: int,
                mode: str = "sante") -> tuple[float, float] | None:
    """``(echeance_en_tours, reste)`` du prochain jalon non acheve du noeud.

    Les jalons non observables — echeance posterieure au dernier tour — sont
    INCLUS : le service les prevoit lui aussi, et les exclure ici retirait au
    temoin onze negatifs faciles que son concurrent gardait.

    Returns:
        None si le noeud n'a plus de jalon en cours a ce tour — le predicteur
        n'a alors rien a dire, exactement comme le harnais.
    """
    candidats = []
    for jalon in verite["jalons"].values():
        if jalon["node_id"] != node_id:
            continue
        avance = float(jalon["trajectoire"].get(str(tour), 0.0))
        if avance >= 1.0:
            continue
        if mode == "calendrier":
            duree = float(jalon["echeance_origine"] - jalon["debut"])
            ecoule = (tour - jalon["debut"]) / duree if duree > 0 else 1.0
            avance = min(max(ecoule, 0.0), 1.0)
        candidats.append((float(jalon["echeance_origine"]), 1.0 - avance))
    if not candidats:
        return None
    return min(candidats)  # le plus proche dans le temps


def main() -> None:
    """Ecrit le journal du predicteur trivial."""
    args = sys.argv[1:]
    mode = "sante"
    if "--mode" in args:
        i = args.index("--mode")
        mode = args[i + 1]
        del args[i:i + 2]
    if len(args) != 3 or mode not in ("sante", "calendrier"):
        raise SystemExit(__doc__)
    pack, reference, sortie = Path(args[0]), Path(args[1]), Path(args[2])
    verite = json.loads((pack / "VERITE.json").read_text(encoding="utf-8"))
    scorables = couples_scorables(reference)

    lignes: list[str] = []
    muets_reference = muets_temoin = accord = 0
    leads_par_tour = {t: lead_times(pack, t) for t in {c[0] for c in scorables}}
    for tour, node_id in sorted(scorables):
        horizons_vus = scorables[(tour, node_id)]
        entree: dict = {"arm": f"trivial_{mode}", "tour": tour, "node_id": node_id}
        actif = jalon_actif(verite, node_id, tour, mode)
        muets_reference += not horizons_vus
        muets_temoin += actif is None
        accord += (not horizons_vus) == (actif is None)
        for k in HORIZONS:
            if k not in horizons_vus or actif is None:
                entree[f"p_issue_h{k}"] = None
                continue
            echeance, reste = actif
            besoin = max(reste * leads_par_tour[tour].get(node_id, 0.0) / HEURES_PAR_TOUR, _EPS)
            marge = (echeance - (tour + k)) / besoin
            entree[f"p_issue_h{k}"] = max(0.0, min(1.0, 1.0 - marge))
        lignes.append(json.dumps(entree, ensure_ascii=False))

    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    print(f"{len(lignes)} previsions triviales -> {sortie}")
    print(f"  reference muette sur {muets_reference} couples, temoin sur {muets_temoin} ;"
          f" ils sont d'accord sur {accord}/{len(scorables)}")


if __name__ == "__main__":
    main()
