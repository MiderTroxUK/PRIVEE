"""Moteur de graphe DAG multi-rangs et propagation des urgences.

API publique :
- GraphRepository        : interface abstraite du depot de graphe ;
- InMemoryGraphRepository : implementation networkx (reference, tests) ;
- Neo4jGraphRepository   : implementation persistante (driver neo4j optionnel,
                           importe paresseusement dans le constructeur) ;
- PropagationEngine      : propagation Ud descendante / Ur montante,
                           simulation de choc (DeltaUr et Deltal), application de statut ;
- ShockDetail            : resultat detaille d'un choc what-if (DeltaUr + Deltal).
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
