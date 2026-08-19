"""Assemble les reponses des personas en un fichier que le harnais collecte.

Chaque persona ecrit sa declaration dans SON fichier, seul endroit ou il a le
droit d'ecrire (protocole anti-fuite). Le harnais, lui, attend un JSONL unique.
Ce script fait le pont, et rien d'autre : il ne juge pas, ne corrige pas les
valeurs, ne remplace pas une reponse manquante par une valeur plausible.

Deux robustesses, apprises a la campagne HELIOS :

- **encodage** : une reponse ecrite en cp1252 par un outil Windows produit du
  mojibake une fois relue en UTF-8. Le script le detecte et le repare, en le
  DISANT — reparer en silence reviendrait a masquer un defaut de chaine.
- **anomalies nommees** : un noeud sans reponse, ou avec une reponse illisible,
  est signale par son nom. Le harnais reconduira la declaration precedente, ce
  qui est son protocole, mais l'operateur doit savoir pour qui.

Usage :
    python collecte_personas.py <dossier_reponses> <tour> <sortie.jsonl> [--noeuds a,b,c]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: Champs sans lesquels une declaration n'est pas exploitable.
REQUIS = ("node_id", "bipolar", "scores_ui")


def _reparer_mojibake(texte: str) -> tuple[str, bool]:
    """Repare un texte UTF-8 relu comme du cp1252, s'il l'a ete.

    Args:
        texte: chaine potentiellement abimee.

    Returns:
        ``(texte, repare)``. La reparation n'est retenue que si elle fait
        DISPARAITRE les sequences caracteristiques, jamais au jugement.
    """
    if "Ã" not in texte and "â€" not in texte:
        return texte, False
    try:
        candidat = texte.encode("cp1252", errors="strict").decode("utf-8", errors="strict")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texte, False
    if "Ã" in candidat or "â€" in candidat:
        return texte, False
    return candidat, True


def lire(dossier: Path, node: str, tour: int) -> tuple[dict | None, str | None]:
    """Derniere declaration du noeud pour ce tour, et l'anomalie s'il y en a une."""
    chemin = dossier / f"{node}.jsonl"
    if not chemin.is_file():
        return None, "aucune reponse deposee"
    trouvee: dict | None = None
    for brute in chemin.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        brute = brute.strip().lstrip("﻿")
        if not brute:
            continue
        try:
            ligne = json.loads(brute)
        except json.JSONDecodeError as err:
            return None, f"JSON illisible ({err.msg})"
        if ligne.get("tour") == tour:
            trouvee = ligne  # la derniere gagne : le persona a pu se corriger
    if trouvee is None:
        return None, f"aucune ligne au tour {tour}"
    manquants = [c for c in REQUIS if c not in trouvee]
    if manquants:
        return None, f"champs manquants : {', '.join(manquants)}"
    if len(trouvee["bipolar"]) != 6:
        return None, f"bipolar de longueur {len(trouvee['bipolar'])}, 6 attendus"
    if len(trouvee["scores_ui"]) != 4:
        return None, f"scores_ui de longueur {len(trouvee['scores_ui'])}, 4 attendus"
    return trouvee, None


def main() -> None:
    """Assemble, signale les anomalies, ecrit le JSONL du harnais."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reponses", type=Path)
    ap.add_argument("tour", type=int)
    ap.add_argument("sortie", type=Path)
    ap.add_argument("--noeuds", default=None,
                    help="Liste attendue, separee par des virgules. Sans elle, "
                         "tous les fichiers presents sont pris.")
    args = ap.parse_args()

    if args.noeuds:
        attendus = [n.strip() for n in args.noeuds.split(",") if n.strip()]
    else:
        attendus = sorted(p.stem for p in args.reponses.glob("*.jsonl"))

    lignes: list[str] = []
    anomalies: list[str] = []
    repares: list[str] = []
    for node in attendus:
        declaration, anomalie = lire(args.reponses, node, args.tour)
        if declaration is None:
            anomalies.append(f"{node} : {anomalie}")
            continue
        note, repare = _reparer_mojibake(str(declaration.get("note", "")))
        if repare:
            declaration["note"] = note
            repares.append(node)
        lignes.append(json.dumps(
            {"node_id": declaration["node_id"], "bipolar": declaration["bipolar"],
             "scores_ui": declaration["scores_ui"], "note": declaration.get("note", "")},
            ensure_ascii=False))

    args.sortie.parent.mkdir(parents=True, exist_ok=True)
    args.sortie.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    print(f"tour {args.tour} : {len(lignes)}/{len(attendus)} declarations -> {args.sortie}")
    if repares:
        print(f"  encodage repare (cp1252 -> utf-8) : {', '.join(repares)}")
    for a in anomalies:
        print(f"  ANOMALIE  {a}")
    if anomalies:
        print("  Le harnais reconduira la declaration precedente de ces noeuds.")


if __name__ == "__main__":
    main()
