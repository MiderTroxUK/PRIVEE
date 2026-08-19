"""Insights decisionnels en ligne de commande - LE contrat de fin HELIOS v7.

Usage::

    python -m supplyscore.tools.insights --db-dir data_store --project <id> \
        [--model models/latest/artifact.json] [--json]

Tente une prevision complete via :class:`~supplyscore.services.prediction.\
PredictionService` (import PARESSEUX - le module U11 peut etre absent de cet
environnement). Si le module est indisponible, si aucun artefact n'est
fourni/lisible, ou si la prevision echoue pour toute autre raison, l'outil
avertit clairement puis bascule en MODE DEGRADE : des insights fondes
UNIQUEMENT sur la criticite systematique (:class:`~supplyscore.services.\
criticite.ServiceCriticite`) et les signaux H/F du depot sont produits sans
aucun artefact de modele (jamais un P(<=4) fabrique).

Code retour : 0 si des insights sont produits (meme liste vide), 1 si le
projet est inconnu du registre (message francais sur la sortie d'erreur).
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from supplyscore.domain.models import TaskStatus
from supplyscore.services import SupplyScoreService
from supplyscore.services.criticite import ServiceCriticite
from supplyscore.services.insights import Insight, InsightService

#: Emplacement par defaut de l'artefact de modele (contrat 5 fige, U10) - meme valeur que :mod:`supplyscore.tools.predict`.
_DEFAULT_MODEL = "models/latest/artifact.json"

#: Ordre d'affichage des sections groupees par severite.
_ORDRE_SEVERITE: tuple[str, ...] = ("alerte", "attention", "info")


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments de l'outil d'insights.

    Returns:
        Le :class:`argparse.ArgumentParser` configure (``--db-dir``,
        ``--project``, ``--model``, ``--json``).
    """
    parser = argparse.ArgumentParser(
        prog="python -m supplyscore.tools.insights",
        description=(
            "Produit, pour chaque nœud actif d'un projet SupplyScore, des insights"
            " décisionnels en français audités (contrat de fin HÉLIOS v7). Bascule"
            " en mode dégradé (criticité + H/F, sans artefact) si la prévision est"
            " indisponible."
        ),
    )
    parser.add_argument(
        "--db-dir", default="data_store", help="répertoire des bases SQLite (défaut : data_store)"
    )
    parser.add_argument("--project", required=True, help="identifiant du projet à analyser")
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"chemin de l'artefact de modèle JSON (défaut : {_DEFAULT_MODEL})",
    )
    parser.add_argument("--json", action="store_true", help="sortie JSON (une ligne par appel)")
    return parser


# Points minimaux (mode degrade, sans artefact)


@dataclasses.dataclass(frozen=True)
class _PointMinimal:
    """Point minimal reproduisant structurellement le contrat 6 (mode degrade CLI).

    Tous les champs de prevision restent neutres/absents (aucun P(<=4) n'est
    fabrique) ; seuls ``node_id``, ``node_name`` et ``impact_frac``
    (criticite, calculable sans aucun modele) sont renseignes - cf.
    :class:`~supplyscore.services.insights.InsightService`, qui relit par
    ailleurs H/F et les arcs de secours EN DIRECT sur la facade.
    """

    node_id: str
    node_name: str
    proba_by_horizon: dict[int, float]
    ic80_by_horizon: dict[int, tuple[float, float] | None]
    incertitude_mc: dict[int, float] | None
    incertitude_param: dict[int, float] | None
    delta_vs_last_week: float | None
    p_jalon_rate: float | None
    p_impact_client: float | None
    drivers: list[tuple[str, float]]
    impact_frac: float | None
    delta_ell_final: float | None
    recommandation: object | None


def _points_degrades(service: SupplyScoreService, project_id: str) -> list[_PointMinimal]:
    """Points minimaux (criticite + rien d'autre) pour le mode degrade, sans artefact.

    Args:
        service: facade applicative (depot de graphe deja charge du registre).
        project_id: projet a analyser.

    Returns:
        Un :class:`_PointMinimal` par noeud ACTIF (onboarding termine) du
        projet ; ``impact_frac`` est renseigne si la criticite est
        calculable (au moins un noeud actif), None sinon.
    """
    noeuds = [
        n
        for n in service.repo.nodes_by_project(project_id)
        if n.status == TaskStatus.ACTIVE and n.onboarding_state != "draft"
    ]
    impact_par_noeud: dict[str, float] = {}
    try:
        points_crit = ServiceCriticite(service).indice_criticite(project_id)
        n_total = len(service.repo.nodes_by_project(project_id))
        if n_total:
            impact_par_noeud = {p.node_id: p.nb_impactes / n_total for p in points_crit}
    except ValueError:
        pass  # aucun noeud actif : criticite indisponible, impact_frac restera absent

    return [
        _PointMinimal(
            node_id=n.id,
            node_name=n.name,
            proba_by_horizon={},
            ic80_by_horizon={},
            incertitude_mc=None,
            incertitude_param=None,
            delta_vs_last_week=None,
            p_jalon_rate=None,
            p_impact_client=None,
            drivers=[],
            impact_frac=impact_par_noeud.get(n.id),
            delta_ell_final=None,
            recommandation=None,
        )
        for n in noeuds
    ]


def _construire_points(
    service: SupplyScoreService, project_id: str, model_path: Path
) -> tuple[Sequence[Any], list[str]]:
    """Points de prevision reels si possible, sinon points degrades (jamais fatal).

    Tente ``PredictionService`` (import paresseux) UNIQUEMENT si l'artefact
    existe sur disque ; toute autre situation (module absent, artefact
    illisible, echec de prevision) bascule en mode degrade avec un
    avertissement francais explicite - jamais une exception propagee d'ici.

    Args:
        service: facade applicative (depot de graphe deja charge du registre).
        project_id: projet a analyser.
        model_path: chemin de l'artefact de modele candidat.

    Returns:
        ``(points, avertissements)`` - les points (reels ou degrades) et les
        avertissements francais a afficher apres le rendu.
    """
    try:
        module = importlib.import_module("supplyscore.services.prediction")
    except ImportError:
        return _points_degrades(service, project_id), [
            "Module de prévision indisponible (supplyscore.services.prediction absent) —"
            " consulter l'unité U11. Mode dégradé : insights fondés sur la criticité et"
            " H/F uniquement, sans artefact."
        ]

    if not model_path.exists():
        return _points_degrades(service, project_id), [
            f"Artefact de modèle introuvable ({model_path}). Mode dégradé : insights fondés"
            " sur la criticité et H/F uniquement, sans artefact."
        ]

    try:
        pred_service = module.PredictionService(service, model_path)
        points = pred_service.predict(project_id)
    except Exception as exc:  # degradation volontaire : jamais fatal pour cet outil
        return _points_degrades(service, project_id), [
            f"Prévision indisponible ({exc}). Mode dégradé : insights fondés sur la"
            " criticité et H/F uniquement, sans artefact."
        ]
    avertissements = [f"Prévision : {a}" for a in pred_service.avertissements]
    return points, avertissements


# Rendu humain


def _imprimer_insights(insights: list[Insight]) -> None:
    """Imprime les insights groupes par severite (alerte, attention, info).

    Args:
        insights: insights a afficher, deja tries par :meth:`InsightService.insights`.
    """
    par_severite: dict[str, list[Insight]] = {severite: [] for severite in _ORDRE_SEVERITE}
    for insight in insights:
        par_severite.setdefault(insight.severite, []).append(insight)

    for severite in (*_ORDRE_SEVERITE, *(s for s in par_severite if s not in _ORDRE_SEVERITE)):
        groupe = par_severite.get(severite, [])
        if not groupe:
            continue
        print(f"\n=== {severite.upper()} ({len(groupe)}) ===")
        for insight in groupe:
            print(f"- {insight.message}")
            if insight.action:
                print(f"  Action suggérée : {insight.action}")


# Rendu JSON


def _insight_vers_json(insight: Insight) -> dict[str, Any]:
    """Convertit un :class:`Insight` en dictionnaire JSON-serialisable.

    Args:
        insight: insight a convertir.

    Returns:
        Le dictionnaire pret pour ``json.dumps``.
    """
    return dataclasses.asdict(insight)


# Point d'entree


def main(argv: list[str] | None = None) -> int:
    """Point d'entree : produit les insights du projet et les affiche.

    Args:
        argv: arguments de la ligne de commande (``sys.argv[1:]`` si None).

    Returns:
        0 si des insights sont produits (meme liste vide), 1 si le projet est
        inconnu du registre (message francais sur la sortie d'erreur).
    """
    args = build_parser().parse_args(argv)
    service = SupplyScoreService(db_dir=args.db_dir)
    try:
        # Le depot de graphe en memoire demarre vide : il faut le rehydrater depuis le registre SQLite (meme motif que tools/predict.py).
        service.load_graph_from_registry()

        # _construire_points ne leve JAMAIS (degradation interne complete, cf. sa docstring) : seule InsightService.insights peut echouer (projet inconnu).
        points, avertissements = _construire_points(service, args.project, Path(args.model))

        try:
            insights = InsightService(service).insights(args.project, points)
        except ValueError as exc:
            print(f"Erreur : {exc}", file=sys.stderr)
            return 1

        if args.json:
            brut = [_insight_vers_json(i) for i in insights]
            print(json.dumps(brut, ensure_ascii=False, indent=2))
        else:
            if insights:
                _imprimer_insights(insights)
            else:
                print("Aucun insight produit (aucun nœud éligible).")
            for avertissement in avertissements:
                print(f"\nAvertissement : {avertissement}")
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
