"""Prevision produit en ligne de commande - l'export du contrat de fin HELIOS v7.

Usage::

    python -m supplyscore.tools.predict --db-dir data_store --project <id> \
        [--model models/latest/artifact.json] [--json] [--horizon 4] \
        [--draws 2000] [--seed 0]

Code retour : 0 si la prevision aboutit (meme vide), 1 sinon (message
d'erreur en francais sur la sortie d'erreur). Les avertissements non
bloquants (noeuds exclus, mode features-only, imputations) sont affiches
apres le tableau humain, jamais en JSON strict (``--json`` ne dump que les
points, pour rester consommable par un pipeline).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

from supplyscore.services import SupplyScoreService
from supplyscore.services.prediction import PredictionPoint, PredictionService

#: Emplacement par defaut de l'artefact de modele (contrat 5 fige, U10).
_DEFAULT_MODEL = "models/latest/artifact.json"


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments de l'outil de prevision.

    Returns:
        Le :class:`argparse.ArgumentParser` configure (``--db-dir``,
        ``--project``, ``--model``, ``--json``, ``--horizon``, ``--draws``,
        ``--seed``).
    """
    parser = argparse.ArgumentParser(
        prog="python -m supplyscore.tools.predict",
        description=(
            "Prévoit, pour chaque nœud actif d'un projet SupplyScore, la probabilité"
            " calibrée d'issue défavorable sur 1..N semaines à partir d'un artefact de"
            " modèle figé (contrat 5)."
        ),
    )
    parser.add_argument(
        "--db-dir", default="data_store", help="répertoire des bases SQLite (défaut : data_store)"
    )
    parser.add_argument("--project", required=True, help="identifiant du projet à prévoir")
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"chemin de l'artefact de modèle JSON (défaut : {_DEFAULT_MODEL})",
    )
    parser.add_argument("--json", action="store_true", help="sortie JSON (une ligne par appel)")
    parser.add_argument(
        "--horizon",
        type=int,
        default=4,
        help="horizon maximal en semaines : prévoit 1..N (défaut 4)",
    )
    parser.add_argument(
        "--draws", type=int, default=2000, help="budget de trajectoires du rollout U9 (défaut 2000)"
    )
    parser.add_argument("--seed", type=int, default=0, help="graine du rollout U9 (défaut 0)")
    return parser


# Rendu humain


def _formater_probabilite(p: float, ic80: tuple[float, float] | None) -> str:
    """Formate une probabilite et son IC80 optionnel pour le tableau humain.

    Args:
        p: probabilite calibree dans [0, 1].
        ic80: intervalle de confiance a 80 %, ou None.

    Returns:
        ``"29%"`` ou ``"29% [21-38]"`` si un IC80 est fourni.
    """
    base = f"{p * 100:.0f}%"
    if ic80 is None:
        return base
    lo, hi = ic80
    return f"{base} [{lo * 100:.0f}-{hi * 100:.0f}]"


def _formater_drivers(drivers: list[tuple[str, float]]) -> str:
    """Formate les features dominantes pour le tableau humain.

    Args:
        drivers: ``[(nom, contribution_signee), ...]``.

    Returns:
        ``"ur_local(+1.00), hidden_risk(+1.00), rang(+1.00)"`` (chaine vide
        si aucun driver).
    """
    return ", ".join(f"{nom}({valeur:+.2f})" for nom, valeur in drivers)


def _formater_tableau(entetes: list[str], lignes: list[list[str]]) -> str:
    """Aligne un tableau texte en colonnes de largeur homogene.

    Args:
        entetes: libelles de colonnes.
        lignes: valeurs, une liste de cellules (chaines) par ligne.

    Returns:
        Le tableau rendu, en-tete et lignes separes par des retours a la ligne.
    """
    largeurs = [len(entete) for entete in entetes]
    for ligne in lignes:
        for i, cellule in enumerate(ligne):
            largeurs[i] = max(largeurs[i], len(cellule))
    rendu = ["  ".join(entete.ljust(largeurs[i]) for i, entete in enumerate(entetes))]
    for ligne in lignes:
        rendu.append("  ".join(cellule.ljust(largeurs[i]) for i, cellule in enumerate(ligne)))
    return "\n".join(rendu)


def _imprimer_tableau(points: list[PredictionPoint], horizons: tuple[int, ...]) -> None:
    """Imprime le tableau francais aligne des previsions.

    Args:
        points: previsions a afficher, dans l'ordre deja trie par le service.
        horizons: horizons demandes, dans l'ordre d'affichage des colonnes.
    """
    entetes = ["Nœud", *[f"P<={h}sem" for h in horizons], "Δ semaine", "Drivers"]
    lignes = []
    for point in points:
        delta = "n/d" if point.delta_vs_last_week is None else f"{point.delta_vs_last_week:+.2f}"
        lignes.append(
            [
                point.node_name,
                *[
                    _formater_probabilite(point.proba_by_horizon[h], point.ic80_by_horizon[h])
                    for h in horizons
                ],
                delta,
                _formater_drivers(point.drivers),
            ]
        )
    print(_formater_tableau(entetes, lignes))


# Rendu JSON


def _point_vers_json(point: PredictionPoint) -> dict[str, Any]:
    """Convertit une :class:`PredictionPoint` en dictionnaire JSON-serialisable.

    Args:
        point: prevision d'un noeud.

    Returns:
        Le dictionnaire pret pour ``json.dumps`` (la recommandation, si
        presente, est convertie via ``dataclasses.asdict`` quand c'est une
        sequence de dataclasses U18, sinon laissee telle quelle).
    """
    brut = dataclasses.asdict(point)
    if isinstance(point.recommandation, list):
        try:
            brut["recommandation"] = [dataclasses.asdict(reco) for reco in point.recommandation]
        except TypeError:
            brut["recommandation"] = point.recommandation
    return brut


# Point d'entree


def main(argv: list[str] | None = None) -> int:
    """Point d'entree : prevoit le projet et affiche le tableau francais ou du JSON.

    Args:
        argv: arguments de la ligne de commande (``sys.argv[1:]`` si None).

    Returns:
        0 si la prevision aboutit (meme liste vide), 1 en cas d'erreur
        (message francais sur la sortie d'erreur).
    """
    args = build_parser().parse_args(argv)
    model_path = Path(args.model)
    if not model_path.exists():
        print(f"Erreur : artefact de modèle introuvable : {model_path}", file=sys.stderr)
        return 1

    service = SupplyScoreService(db_dir=args.db_dir)
    try:
        # Le depot de graphe en memoire demarre vide : il faut le rehydrater depuis le registre SQLite (meme motif que web_ui/app.py) avant de pouvoir resoudre les noeuds du projet.
        service.load_graph_from_registry()
        try:
            pred_service = PredictionService(service, model_path)
        except ValueError as exc:
            print(f"Erreur : {exc}", file=sys.stderr)
            return 1

        horizons = tuple(range(1, args.horizon + 1))
        try:
            points = pred_service.predict(
                args.project, horizons=horizons, n_draws=args.draws, seed=args.seed
            )
        except ValueError as exc:
            print(f"Erreur : {exc}", file=sys.stderr)
            return 1

        if args.json:
            print(json.dumps([_point_vers_json(p) for p in points], ensure_ascii=False, indent=2))
        else:
            if points:
                _imprimer_tableau(points, horizons)
            else:
                print("Aucune prévision produite (aucun nœud éligible).")
            for avertissement in pred_service.avertissements:
                print(f"Avertissement : {avertissement}")
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
