"""Couche donnees de supplyscore : persistance SQLite + generateur de donnees de test.

API publique :
- :class:`RegistryDatabase` - registre global (projets, noeuds, arcs partages).
- :class:`ClientDatabase`  - base par client (evaluations AHP, snapshots KPI, urgences).
- :class:`RandomSupplyChainGenerator` - donnees de TEST aleatoires (jamais en production).
- ``kpis_to_json`` / ``kpis_from_json`` - serialisation KPIBundle <-> JSON.
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
    "RandomSupplyChainGenerator",
    "RegistryDatabase",
    "kpis_from_json",
    "kpis_to_json",
]
