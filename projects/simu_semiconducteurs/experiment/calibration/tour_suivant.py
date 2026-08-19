"""Attend les huit declarations d'un tour, le verifie, le clot et prepare le suivant.

Le coordinateur relance les agents ; ce script fait tout le reste sans qu'il ait
a intervenir entre chaque etape. Il n'ecrit RIEN dans les bacs a sable en dehors
de ce que fait deja ``campagne_bras_c.py verifier`` (le retour de l'outil sur
echec de coherence) : le protocole anti-contamination est preserve.

Sortie en erreur si le delai d'attente expire — mieux vaut un refus explicite
qu'un tour clos avec des declarations manquantes.

Usage : python tour_suivant.py <travail> <tour> [timeout_s]
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"C:\PRIVEE\AZURE")
PY = REPO / ".venv" / "Scripts" / "python.exe"
PILOTE = REPO / "projects/simu_semiconducteurs/experiment/calibration/campagne_bras_c.py"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NODES = [
    "orbitalys", "aviosys", "electis", "compodis",
    "transglobal", "novafab", "meridian", "silpure",
]

#: Intervalle de scrutation des bacs a sable (secondes).
_PAS = 5.0


def _a_repondu(sandbox: Path, tour: int) -> bool:
    """Le persona a-t-il ecrit une ligne pour ce tour ?"""
    chemin = sandbox / "results.jsonl"
    if not chemin.is_file():
        return False
    for brute in chemin.read_text(encoding="utf-8-sig").splitlines():
        brute = brute.strip().lstrip("\ufeff")
        if not brute:
            continue
        try:
            if json.loads(brute).get("tour") == tour:
                return True
        except json.JSONDecodeError:
            continue
    return False


def attendre(out: Path, tour: int, timeout_s: float) -> list[str]:
    """Attend les huit reponses ; renvoie la liste des manquants a l'expiration."""
    debut = time.monotonic()
    vus: set[str] = set()
    while time.monotonic() - debut < timeout_s:
        for node in NODES:
            if node not in vus and _a_repondu(out / f"sandbox_{node}", tour):
                vus.add(node)
                print(f"  [{len(vus)}/8] {node}", flush=True)
        if len(vus) == len(NODES):
            return []
        time.sleep(_PAS)
    return [n for n in NODES if n not in vus]


def piloter(travail: Path, commande: str, tour: int) -> int:
    """Lance une commande du pilote et relaie sa sortie."""
    proc = subprocess.run(
        [str(PY), str(PILOTE), commande, str(travail), str(tour)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    sortie = (proc.stdout or "").rstrip()
    if sortie:
        print(sortie)
    if proc.returncode != 0 and proc.stderr:
        print(proc.stderr[-800:])
    return proc.returncode


def main() -> None:
    """Attend, verifie, clot le tour et prepare le suivant."""
    travail = Path(sys.argv[1])
    tour = int(sys.argv[2])
    timeout_s = float(sys.argv[3]) if len(sys.argv) > 3 else 900.0

    print(f"--- attente des declarations du tour {tour} ---", flush=True)
    manquants = attendre(travail / "out", tour, timeout_s)
    if manquants:
        print(f"REFUS : delai expire, manquent {', '.join(manquants)}")
        sys.exit(1)

    print(f"\n--- verification de coherence, tour {tour} ---")
    if piloter(travail, "verifier", tour) != 0:
        sys.exit(1)

    print(f"\n--- cloture du tour {tour} ---")
    if piloter(travail, "cloturer", tour) != 0:
        print("REFUS : cloture impossible (voir ci-dessus).")
        sys.exit(1)

    print(f"\n--- preparation du tour {tour + 1} ---")
    if piloter(travail, "preparer", tour + 1) != 0:
        sys.exit(1)
    print(f"\nTOUR {tour + 1} PRET — relancer les agents.")


if __name__ == "__main__":
    main()
