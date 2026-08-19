"""Balayage de calibration : rejoue HELIOS sous plusieurs jeux de parametres.

La chaine « choc -> risque de jalon » comporte deux constantes sans valeur
derivable a priori (cf. ``supplyscore.domain.events``) :

- ``SUPPLYSCORE_LAMBDA_ARRET``     : part d'un arret qui s'inscrit au retard ;
- ``SUPPLYSCORE_RATTRAPAGE_HEBDO`` : part du retard rattrapee chaque semaine.

On les calibre en rejouant la campagne HELIOS — dont la verite terrain est
CONNUE et GELEE — puis en scorant les previsions produites. Le rejeu ne fait
AUCUN appel LLM : il repasse les reponses deja enregistrees du pilote a travers
le harnais, donc seul le MODELE change d'un point de grille a l'autre. Les
declarations humaines etant identiques partout, la comparaison est propre.

Deux objectifs, volontairement separes :

- **skill de Brier** moyen sur les horizons 1..4 — calibration ET
  discrimination sur les 90 a 112 points scorables ;
- **cout diagnostique** — l'erreur sur les six cas qui ont motive la
  correction (CompoDis livre a l'heure, NovaFab rate apres quatre semaines
  d'arret). Un modele peut gagner en moyenne tout en restant faux sur les deux
  cas qui comptent : on regarde les deux.

Usage : python balayage.py [dossier_sortie] [n_workers]
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REPO = Path(r"C:\PRIVEE\AZURE")
PY = REPO / ".venv" / "Scripts" / "python.exe"
OUTILS = REPO / "projects/simu_semiconducteurs/experiment/mesures_avant_reparation/outils"
REJEU = OUTILS / "replay_a.py"
AVANT = REPO / "projects/simu_semiconducteurs/experiment/mesures_avant_reparation/bras_a_rejeu"

sys.path.insert(0, str(REPO / "projects" / "simu_semiconducteurs" / "scenario"))
sys.path.insert(0, str(OUTILS))
from score_endogene import evenements_graves, jalons_rates  # noqa: E402
from score_predictions import auc, brier  # noqa: E402

HORIZONS = (1, 2, 3, 4)
TOUR_MAX = 18

#: Grille balayee : (lambda_arret, rattrapage_hebdo).
GRILLE: tuple[tuple[float, float], ...] = tuple(
    (lam, rat) for lam in (0.4, 0.7, 1.0) for rat in (0.0, 0.15, 0.35, 0.6)
)

#: Cas diagnostiques : (tour, noeud, le jalon a-t-il REELLEMENT ete rate ?).
#: CompoDis « Couverture composants S1 » (echeance T9) a ete LIVRE A L'HEURE —
#: toute probabilite elevee y est un faux positif, et c'est le cas ou le modele
#: annoncait 99,6 %. NovaFab « Allocation wafers HELIOS » (echeance T10) a ete
#: RATE (livre T11) apres quatre semaines d'arret — toute probabilite basse y
#: est un faux negatif, et c'est le cas ou le modele annoncait 0,0 %.
DIAGNOSTIQUES: tuple[tuple[int, str, bool], ...] = (
    (6, "compodis", False),
    (7, "compodis", False),
    (8, "compodis", False),
    (7, "novafab", True),
    (8, "novafab", True),
    (9, "novafab", True),
)


@dataclass
class Resultat:
    """Scores d'un point de grille."""

    lam: float
    rat: float
    skill: dict[int, float] = field(default_factory=dict)
    aire: dict[int, float] = field(default_factory=dict)
    diag: dict[tuple[int, str], float] = field(default_factory=dict)
    erreur: str = ""

    @property
    def skill_moyen(self) -> float:
        """Skill de Brier moyen sur les horizons scores."""
        return sum(self.skill.values()) / len(self.skill) if self.skill else float("-inf")

    @property
    def auc_moyen(self) -> float:
        """AUC moyenne sur les horizons scores."""
        return sum(self.aire.values()) / len(self.aire) if self.aire else float("nan")

    @property
    def cout_diagnostique(self) -> float:
        """Erreur absolue cumulee sur les six cas (0 = parfait, 6 = pire possible)."""
        total = 0.0
        for tour, node, rate in DIAGNOSTIQUES:
            proba = self.diag.get((tour, node))
            if proba is None:
                return float("inf")
            total += (1.0 - proba) if rate else proba
        return total


def _points(lignes: list[dict], h: int, dernier: int) -> tuple[np.ndarray, np.ndarray]:
    """(scores, verites) scorables a l'horizon h — cible endogene, censures exclus."""
    rates, graves = jalons_rates(dernier), evenements_graves()
    scores: list[float] = []
    verites: list[int] = []
    for ligne in lignes:
        tour, node = ligne["tour"], ligne["node_id"]
        proba = ligne.get(f"p_issue_h{h}")
        if proba is None:
            continue
        issue = any(tour < d <= tour + h for d in rates.get(node, set())) or any(
            tour < e <= tour + h for e in graves.get(node, set())
        )
        if not issue and tour + h > dernier:
            continue  # fenetre incomplete sans issue observee : point censure
        scores.append(float(proba))
        verites.append(1 if issue else 0)
    return np.asarray(scores), np.asarray(verites)


def scorer(chemin: Path, resultat: Resultat) -> Resultat:
    """Remplit ``resultat`` a partir d'un journal de previsions."""
    lignes = [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines() if x.strip()]
    dernier = max(ligne["tour"] for ligne in lignes)
    cibles = {(tour, node) for tour, node, _ in DIAGNOSTIQUES}
    for h in HORIZONS:
        scores, verites = _points(lignes, h, dernier)
        if scores.size == 0:
            continue
        resultat.skill[h] = brier(scores, verites)[1]
        aire = auc(scores, verites)
        if aire is not None:
            resultat.aire[h] = aire
    for ligne in lignes:
        cle = (ligne["tour"], ligne["node_id"])
        if cle in cibles:
            resultat.diag[cle] = float(ligne["p_jalon_rate"])
    return resultat


def rejouer(lam: float, rat: float, racine: Path) -> Resultat:
    """Rejoue la campagne sous (lam, rat) et score le journal produit."""
    res = Resultat(lam=lam, rat=rat)
    travail = racine / f"lam{lam:g}_rat{rat:g}"
    travail.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["SUPPLYSCORE_LAMBDA_ARRET"] = f"{lam:g}"
    env["SUPPLYSCORE_RATTRAPAGE_HEBDO"] = f"{rat:g}"
    proc = subprocess.run(
        [str(PY), str(REJEU), str(travail), str(TOUR_MAX)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    journal = travail / "out" / "predictions_log.jsonl"
    if proc.returncode != 0 or not journal.exists():
        res.erreur = (proc.stderr or proc.stdout or "sortie vide")[-400:]
        return res
    return scorer(journal, res)


def _ligne(etiquette: str, res: Resultat) -> str:
    corps = f"{res.skill_moyen:>+10.3f} {res.auc_moyen:>8.3f} {res.cout_diagnostique:>6.2f} |"
    detail = "".join(f"  {res.skill.get(h, float('nan')):>+8.3f}" for h in HORIZONS)
    return f"{etiquette:>11} | {corps}{detail}"


def main() -> None:
    """Lance le balayage, affiche le tableau et ecrit ``resultats.json``."""
    racine = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "balayage"
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    racine.mkdir(parents=True, exist_ok=True)

    reference = scorer(
        AVANT / "predictions_log.jsonl", Resultat(lam=float("nan"), rat=float("nan"))
    )
    print(f"grille de {len(GRILLE)} points, {workers} workers -> {racine}\n", flush=True)

    resultats: list[Resultat] = []
    with cf.ProcessPoolExecutor(max_workers=workers) as pool:
        futurs = [pool.submit(rejouer, lam, rat, racine) for lam, rat in GRILLE]
        for futur in cf.as_completed(futurs):
            res = futur.result()
            resultats.append(res)
            etat = "ECHEC" if res.erreur else f"skill={res.skill_moyen:+.3f}"
            print(f"  fait : lam={res.lam:g} rat={res.rat:g}  {etat}", flush=True)

    entete = f"{'point':>11} | {'skill moy':>10} {'AUC moy':>8} {'diag':>6} |"
    entete += "".join(f"  skill h{h}" for h in HORIZONS)
    print(f"\n{'=' * len(entete)}\n{entete}\n{'-' * len(entete)}")
    print(_ligne("AVANT", reference))
    print("-" * len(entete))

    valides = [r for r in resultats if not r.erreur]
    for res in sorted(valides, key=lambda r: -r.skill_moyen):
        print(_ligne(f"{res.lam:g}/{res.rat:g}", res))
    for res in (r for r in resultats if r.erreur):
        print(f"{res.lam:g}/{res.rat:g} | ECHEC : {res.erreur.splitlines()[-1][:60]}")

    if not valides:
        return
    print("\nLecture : skill > 0 = mieux que predire toujours le taux de base ;")
    print("          diag = erreur cumulee sur les 6 cas diagnostiques (0 parfait, 6 pire).")
    meilleur_skill = max(valides, key=lambda r: r.skill_moyen)
    meilleur_diag = min(valides, key=lambda r: r.cout_diagnostique)
    print(
        f"\nMeilleur skill      : lam={meilleur_skill.lam:g} rat={meilleur_skill.rat:g} "
        f"({meilleur_skill.skill_moyen:+.3f}, diag {meilleur_skill.cout_diagnostique:.2f})"
    )
    print(
        f"Meilleur diagnostic : lam={meilleur_diag.lam:g} rat={meilleur_diag.rat:g} "
        f"(diag {meilleur_diag.cout_diagnostique:.2f}, skill {meilleur_diag.skill_moyen:+.3f})"
    )
    (racine / "resultats.json").write_text(
        json.dumps(
            [
                {
                    "lambda_arret": r.lam,
                    "rattrapage_hebdo": r.rat,
                    "skill_moyen": r.skill_moyen,
                    "auc_moyen": r.auc_moyen,
                    "cout_diagnostique": r.cout_diagnostique,
                    "skill": {str(k): v for k, v in r.skill.items()},
                    "auc": {str(k): v for k, v in r.aire.items()},
                    "diagnostiques": {f"T{t}_{n}": p for (t, n), p in r.diag.items()},
                }
                for r in sorted(valides, key=lambda r: -r.skill_moyen)
            ],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nDetail : {racine / 'resultats.json'}")


if __name__ == "__main__":
    main()
