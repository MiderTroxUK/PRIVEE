"""H3 re-mesure : le departage log-survie rend-il les tours satures informatifs ?

L'indice de criticite classe les noeuds par ``delta_ur_final``. En crise
generalisee tous les Ur saturent, tous les deltas se clipent a zero, et le
classement ne dit plus rien — precisement quand il compterait. Le code ajoute
donc une seconde cle en log-survie l(p) = -ln(1-p) sur un jumeau
epsilon-regularise : elle ordonne comme ``delta_ur_final`` hors saturation
(invariant teste dans ``tests/property/test_prop_delta_ell.py``) et reste
discriminante dedans.

Ce script mesure ce que cette cle recupere, tour par tour, en comparant le
leader des fournisseurs profonds sous l'ancien critere et sous le nouveau.

Usage :
    python h3_delta_ell.py <dossier_snapshots> [<dossier_snapshots> ...]

Les dossiers de snapshots sont produits par le rejeu gele :
    python ../mesures_avant_reparation/outils/replay_a.py <travail> 18
    -> <travail>/out/snapshots/

Le pilote d'origine (sans delta_ell) est a
``analysis/llm_pilot_run/snapshots`` : le script le detecte et n'affiche alors
que la colonne de l'ancien critere.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: Fournisseurs de rang >= 4, ceux dont H3 compare la criticite.
PROFONDS = frozenset({"novafab", "meridian", "silpure"})

#: En dessous de ce seuil, tous les delta_ur sont reputes nuls : reseau sature.
_EPS = 1e-9


def lire(dossier: Path) -> dict[int, list[dict]]:
    """``{tour: points de criticite}`` depuis les snapshots ``tour_NN.json``."""
    par_tour: dict[int, list[dict]] = {}
    for chemin in sorted(dossier.glob("tour_*.json")):
        snap = json.loads(chemin.read_text(encoding="utf-8"))
        points = [p for p in (snap.get("criticite") or []) if "erreur" not in p]
        if points:
            par_tour[snap["tour"]] = points
    return par_tour


def _cle_ancienne(point: dict) -> float:
    return point.get("delta_ur_final", 0.0)


def _cle_nouvelle(point: dict) -> tuple[float, float]:
    return (point.get("delta_ur_final", 0.0), point.get("delta_ell_final", 0.0))


def analyser(dossier: Path) -> None:
    """Affiche le leader par tour sous les deux criteres, et les deux parts."""
    par_tour = lire(dossier)
    if not par_tour:
        print(f"\n=== {dossier} : aucun snapshot exploitable ===")
        return
    a_ell = any("delta_ell_final" in p for pts in par_tour.values() for p in pts)

    print(f"\n=== {dossier}")
    print(f"    {len(par_tour)} tours, delta_ell {'present' if a_ell else 'ABSENT'} ===")

    inf_ancien = top_ancien = inf_nouveau = top_nouveau = 0
    for tour in sorted(par_tour):
        points = par_tour[tour]
        profonds = [p for p in points if p["node_id"] in PROFONDS]
        sature = max(_cle_ancienne(p) for p in points) < _EPS

        if sature:
            chef_ancien = "sature"
        else:
            inf_ancien += 1
            chef_ancien = max(profonds, key=_cle_ancienne)["node_id"]
            top_ancien += chef_ancien == "novafab"

        if not a_ell:
            chef_nouveau = "n/a"
        elif len({_cle_nouvelle(p) for p in profonds}) <= 1:
            chef_nouveau = "indiscernable"  # meme le departage ne separe rien
        else:
            inf_nouveau += 1
            chef_nouveau = max(profonds, key=_cle_nouvelle)["node_id"]
            top_nouveau += chef_nouveau == "novafab"

        print(f"  T{tour:<2}  dUr: {chef_ancien:<14}  dUr+dl: {chef_nouveau}")

    part = top_ancien / inf_ancien if inf_ancien else 0.0
    print(f"\n  ancien critere : novafab top-1 sur {top_ancien}/{inf_ancien} "
          f"tours informatifs = {part:.0%}")
    if a_ell:
        part_n = top_nouveau / inf_nouveau if inf_nouveau else 0.0
        print(f"  avec delta-l   : novafab top-1 sur {top_nouveau}/{inf_nouveau} "
              f"tours informatifs = {part_n:.0%}")


def main() -> None:
    """Analyse chaque dossier de snapshots passe en argument."""
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for argument in sys.argv[1:]:
        analyser(Path(argument))


if __name__ == "__main__":
    main()
