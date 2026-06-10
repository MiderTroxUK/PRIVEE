"""Couche données de supplyscore : persistance SQLite + générateur de données de test.

API publique :
- :class:`RegistryDatabase` — registre global (projets, nœuds, arcs partagés).
- :class:`ClientDatabase`  — base par client (évaluations AHP, snapshots KPI, urgences).
- :class:`RandomSupplyChainGenerator` — données de TEST aléatoires (jamais en production).
- ``kpis_to_json`` / ``kpis_from_json`` — sérialisation KPIBundle <-> JSON.
"""

from supplyscore.data.db import (
    ClientDatabase,
    RegistryDatabase,
    kpis_from_json,
    kpis_to_json,
)
from supplyscore.data.generator import RandomSupplyChainGenerator

__all__ = [
    "ClientDatabase",
    "RegistryDatabase",
    "RandomSupplyChainGenerator",
    "kpis_from_json",
    "kpis_to_json",
]
