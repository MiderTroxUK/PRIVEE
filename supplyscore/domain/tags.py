"""Tags et taxonomie par projet - tri, filtres et coloration du graphe.

Deux niveaux : des categories controlees par projet (`TagCategory`, avec
couleur pour le DAG) et des tags libres (`Tag`) rattachables ou non a une
categorie. Les noeuds portent des listes d'ids de tags (`SupplyNode.tags`).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TagCategory:
    """Categorie de tags controlee par projet (ex : " Procede ", " Region ")."""

    id: str
    project_id: str
    name: str
    color: str | None = None  # couleur hex pour la coloration du DAG


@dataclass
class Tag:
    """Tag libre (auto-complete), eventuellement rattache a une categorie."""

    id: str
    project_id: str
    name: str
    category_id: str | None = None
