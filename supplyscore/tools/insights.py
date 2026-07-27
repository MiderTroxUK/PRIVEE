"""Insights décisionnels en ligne de commande — LE contrat de fin HÉLIOS v7.

Usage::

    python -m supplyscore.tools.insights --db-dir data_store --project <id> \
        [--model models/latest/artifact.json] [--json]

Tente une prévision complète via :class:`~supplyscore.services.prediction.\
PredictionService` (import PARESSEUX — le module U11 peut être absent de cet
environnement). Si le module est indisponible, si aucun artefact n'est
fourni/lisible, ou si la prévision échoue pour toute autre raison, l'outil
avertit clairement puis bascule en MODE DÉGRADÉ : des insights fondés
UNIQUEMENT sur la criticité systématique (:class:`~supplyscore.services.\
criticite.ServiceCriticite`) et les signaux H/F du dépôt sont produits sans
aucun artefact de modèle (jamais un P(≤4) fabriqué).

Code retour : 0 si des insights sont produits (même liste vide), 1 si le
projet est inconnu du registre (message français sur la sortie d'erreur).
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

#: Emplacement par défaut de l'artefact de modèle (contrat 5 figé, U10) — même
#: valeur que :mod:`supplyscore.tools.predict`.
_DEFAULT_MODEL = "models/latest/artifact.json"

#: Ordre d'affichage des sections groupées par sévérité.
_ORDRE_SEVERITE: tuple[str, ...] = ("alerte", "attention", "info")


def build_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments de l'outil d'insights.

    Returns:
        Le :class:`argparse.ArgumentParser` configuré (``--db-dir``,
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


# --- Points minimaux (mode dégradé, sans artefact) -----------------------------------------


@dataclasses.dataclass(frozen=True)
class _PointMinimal:
    """Point minimal reproduisant structurellement le contrat 6 (mode dégradé CLI).

    Tous les champs de prévision restent neutres/absents (aucun P(≤4) n'est
    fabriqué) ; seuls ``node_id``, ``node_name`` et ``impact_frac``
    (criticité, calculable sans aucun modèle) sont renseignés — cf.
    :class:`~supplyscore.services.insights.InsightService`, qui relit par
    ailleurs H/F et les arcs de secours EN DIRECT sur la façade.
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
    """Points minimaux (criticité + rien d'autre) pour le mode dégradé, sans artefact.

    Args:
        service: façade applicative (dépôt de graphe déjà chargé du registre).
        project_id: projet à analyser.

    Returns:
        Un :class:`_PointMinimal` par nœud ACTIF (onboarding terminé) du
        projet ; ``impact_frac`` est renseigné si la criticité est
        calculable (au moins un nœud actif), None sinon.
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
        pass  # aucun nœud actif : criticité indisponible, impact_frac restera absent

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
    """Points de prévision réels si possible, sinon points dégradés (jamais fatal).

    Tente ``PredictionService`` (import paresseux) UNIQUEMENT si l'artefact
    existe sur disque ; toute autre situation (module absent, artefact
    illisible, échec de prévision) bascule en mode dégradé avec un
    avertissement français explicite — jamais une exception propagée d'ici.

    Args:
        service: façade applicative (dépôt de graphe déjà chargé du registre).
        project_id: projet à analyser.
        model_path: chemin de l'artefact de modèle candidat.

    Returns:
        ``(points, avertissements)`` — les points (réels ou dégradés) et les
        avertissements français à afficher après le rendu.
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
    except Exception as exc:  # dégradation volontaire : jamais fatal pour cet outil
        return _points_degrades(service, project_id), [
            f"Prévision indisponible ({exc}). Mode dégradé : insights fondés sur la"
            " criticité et H/F uniquement, sans artefact."
        ]
    avertissements = [f"Prévision : {a}" for a in pred_service.avertissements]
    return points, avertissements


# --- Rendu humain ----------------------------------------------------------------------------


def _imprimer_insights(insights: list[Insight]) -> None:
    """Imprime les insights groupés par sévérité (alerte, attention, info).

    Args:
        insights: insights à afficher, déjà triés par :meth:`InsightService.insights`.
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


# --- Rendu JSON ------------------------------------------------------------------------------


def _insight_vers_json(insight: Insight) -> dict[str, Any]:
    """Convertit un :class:`Insight` en dictionnaire JSON-sérialisable.

    Args:
        insight: insight à convertir.

    Returns:
        Le dictionnaire prêt pour ``json.dumps``.
    """
    return dataclasses.asdict(insight)


# --- Point d'entrée ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée : produit les insights du projet et les affiche.

    Args:
        argv: arguments de la ligne de commande (``sys.argv[1:]`` si None).

    Returns:
        0 si des insights sont produits (même liste vide), 1 si le projet est
        inconnu du registre (message français sur la sortie d'erreur).
    """
    args = build_parser().parse_args(argv)
    service = SupplyScoreService(db_dir=args.db_dir)
    try:
        # Le dépôt de graphe en mémoire démarre vide : il faut le réhydrater
        # depuis le registre SQLite (même motif que tools/predict.py).
        service.load_graph_from_registry()

        # _construire_points ne lève JAMAIS (dégradation interne complète, cf. sa
        # docstring) : seule InsightService.insights peut échouer (projet inconnu).
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
