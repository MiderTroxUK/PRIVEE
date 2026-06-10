"""Tags et taxonomie par projet — tri, filtres et coloration du graphe.

Deux niveaux : des catégories contrôlées par projet (`TagCategory`, avec
couleur pour le DAG) et des tags libres (`Tag`) rattachables ou non à une
catégorie. Les nœuds portent des listes d'ids de tags (`SupplyNode.tags`).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TagCategory:
    """Catégorie de tags contrôlée par projet (ex : « Procédé », « Région »)."""

    id: str
    project_id: str
    name: str
    color: str | None = None  # couleur hex pour la coloration du DAG


@dataclass
class Tag:
    """Tag libre (auto-complété), éventuellement rattaché à une catégorie."""

    id: str
    project_id: str
    name: str
    category_id: str | None = None
