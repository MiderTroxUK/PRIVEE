"""Construit un pack de donnees « HELIOS-E » : degradation ENDOGENE, zero choc.

La campagne HELIOS melange deux natures d'issue defavorable. Les jalons rates
sont ENDOGENES : ils se preparent, le lead time monte, l'avancement decroche,
et un modele peut en principe les voir venir. Les evenements graves sont
EXOGENES : scriptes, sans precurseur dans les KPI, ils sont imprevisibles PAR
CONSTRUCTION. Mesure a l'appui, le modele est anti-predictif sur la seconde
(AUC 0,17 a une semaine) et cette part tire la cible mixte vers le bas.

Ce pack isole la premiere. Il reprend le pack officiel a l'identique, puis :

  - VIDE tous les fichiers d'evenements : plus aucun choc exogene ;
  - fait DERIVER quatre fournisseurs a des dates et des vitesses differentes,
    un lead time qui monte regulierement et une volatilite de cout qui suit,
    ce qui est le comportement d'un fournisseur qui se degrade sans qu'il lui
    arrive un accident.

Tout le reste, reseau, jalons, socle de KPI, personas, est inchange : la
comparaison avec la campagne d'origine ne porte donc que sur la nature des
issues.

Usage :
    python pack_endogene.py <dossier_destination>
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(r"C:\PRIVEE\AZURE")
SOURCE = REPO / "projects" / "simu_semiconducteurs" / "data" / "prepared"

#: Profil de degradation par defaut : quels fournisseurs derivent, a partir de
#: quand, et a quelle vitesse. Chaque entree vaut
#: ``node_id : (lead_time initial en heures, hausse par tour, tour de depart)``.
#: C'est le profil « ce fournisseur prend de plus en plus de retard » et non
#: « il lui arrive quelque chose » : la montee est reguliere et sans a-coup.
#:
#: Des DEPARTS ECHELONNES sont voulus. Faire deriver tout le monde au meme tour
#: produit des issues toutes groupees, donc un echantillon ou le modele n'a
#: qu'une seule chose a apprendre ; des departs etales donnent des positifs
#: repartis dans le temps et sur les noeuds, ce qui est la condition pour que
#: le score veuille dire quelque chose.
DERIVE_LEAD_TIME: dict[str, tuple[float, float, int]] = {
    # node_id : (lead time initial en heures, hausse par tour, tour de depart)
    "compodis": (464.0, 30.0, 1),    # distributeur, derive tot et fort
    "electis": (309.0, 16.0, 3),     # EMS, derive moderee
    "silpure": (580.0, 34.0, 5),     # matiere premiere, derive tardive et forte
    "transglobal": (232.0, 11.0, 2),  # fret, derive lente et continue
}

#: Volatilite de cout induite, qui monte avec le retard : un fournisseur qui
#: derive fait monter ses prix spot. Bornee, sinon le bloc cout sature.
VOLATILITE_MAX: float = 0.45


def construire(destination: Path) -> None:
    """Copie le pack officiel puis y applique la derive endogene."""
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(SOURCE, destination)
    print(f"pack copie depuis {SOURCE}")

    vides = 0
    for chemin in sorted(destination.glob("events_*.json")):
        avant = json.loads(chemin.read_text(encoding="utf-8"))
        if avant:
            vides += 1
        chemin.write_text("[]\n", encoding="utf-8")
    print(f"evenements exogenes retires : {vides} tours en portaient")

    tours = sorted(destination.glob("tour_*.csv"))
    for chemin in tours:
        tour = int(chemin.stem.removeprefix("tour_"))
        lignes = list(csv.DictReader(chemin.read_text(encoding="utf-8").splitlines()))
        # retire les eventuelles valeurs existantes des chemins qu'on pilote
        pilotes = {"time.lead_time_h", "risk.cost_volatility"}
        lignes = [
            l for l in lignes
            if not (l["node_id"] in DERIVE_LEAD_TIME and l["kpi_path"] in pilotes)
        ]
        for node, (base, pente, depart) in DERIVE_LEAD_TIME.items():
            avance = max(tour - depart, 0)
            lead = base + pente * avance
            part = min(avance / 18.0, 1.0)
            lignes.append({"node_id": node, "kpi_path": "time.lead_time_h",
                           "valeur": f"{lead:.1f}"})
            lignes.append({"node_id": node, "kpi_path": "risk.cost_volatility",
                           "valeur": f"{VOLATILITE_MAX * part:.4f}"})
        with chemin.open("w", encoding="utf-8", newline="") as flux:
            plume = csv.DictWriter(flux, fieldnames=["node_id", "kpi_path", "valeur"])
            plume.writeheader()
            plume.writerows(lignes)
    print(f"derive appliquee sur {len(tours)} tours pour {sorted(DERIVE_LEAD_TIME)}")

    # Le manifeste d'empreintes du pack d'origine ne decrit plus ce pack.
    empreintes = destination / "HASHES.sha256"
    if empreintes.exists():
        empreintes.unlink()
    (destination / "PROVENANCE.md").write_text(
        "# Pack HELIOS-E — degradation endogene, zero choc exogene\n\n"
        f"Derive du pack officiel `{SOURCE}` par `pack_endogene.py`.\n\n"
        "- Tous les `events_NN.json` sont vides : aucun evenement moteur.\n"
        "- `time.lead_time_h` et `risk.cost_volatility` sont pilotes en rampe sur "
        f"{', '.join(sorted(DERIVE_LEAD_TIME))}.\n"
        "- Reseau, jalons, socle de KPI et personas : identiques a l'original.\n\n"
        "`HASHES.sha256` a ete retire : les empreintes du pack officiel ne "
        "decrivent plus ce contenu, et laisser un manifeste faux serait pire "
        "que ne pas en avoir.\n",
        encoding="utf-8",
    )
    print(f"-> {destination}")


def main() -> None:
    """Construit le pack a l'emplacement demande."""
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    construire(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
