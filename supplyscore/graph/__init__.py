"""Moteur de graphe DAG multi-rangs et propagation des urgences.

API publique :
- GraphRepository        : interface abstraite du dépôt de graphe ;
- InMemoryGraphRepository : implémentation networkx (référence, tests) ;
- Neo4jGraphRepository   : implémentation persistante (driver neo4j optionnel,
                           importé paresseusement dans le constructeur) ;
- PropagationEngine      : propagation Ud descendante / Ur montante,
                           simulation de choc (ΔUr et Δl), application de statut ;
- ShockDetail            : résultat détaillé d'un choc what-if (ΔUr + Δl).
"""

from supplyscore.graph.memory_repo import InMemoryGraphRepository
from supplyscore.graph.neo4j_repo import Neo4jGraphRepository
from supplyscore.graph.propagation import PropagationEngine, ShockDetail
from supplyscore.graph.repository import GraphRepository

__all__ = [
    "GraphRepository",
    "InMemoryGraphRepository",
    "Neo4jGraphRepository",
    "PropagationEngine",
    "ShockDetail",
]
