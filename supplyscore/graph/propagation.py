"""Moteur de propagation des urgences sur le DAG supply chain.

Le moteur lit les urgences LOCALES (ud_local, ur_local) déjà posées sur les
nœuds par le core (hors périmètre de ce module) et calcule les urgences
PROPAGÉES (ud, ur) :

- Ud (besoin déclaré) se propage en DESCENDANT, du client final (rang 0)
  vers les fournisseurs profonds (rang N) :
      Ud_i = 1 - (1 - Ud_loc_i) * Π_{k ∈ Succ(i)} (1 - γ_ik · Ud_k)

- Ur (risque réel) se propage en MONTANT, des fournisseurs profonds (rang N)
  vers le client final (rang 0) :
      Ur_i = 1 - (1 - Ur_loc_i) * Π_{j ∈ Pred(i)} (1 - β_ji · Ur_j)

Règles de statut appliquées AVANT la propagation montante :
- TaskStatus.DONE      -> Ur_loc effectif forcé à 0.0 (contribution nulle) ;
- TaskStatus.ABANDONED -> Ur_loc effectif forcé à 1.0.

Toutes les valeurs propagées sont clipées dans [0, 1]. Ce module ne calcule
PAS l'adéquation (rôle de core/adequation) et n'importe rien de supplyscore.core.
"""

from __future__ import annotations

import time

from supplyscore.domain.models import TaskStatus, UrgencyState
from supplyscore.graph.repository import GraphRepository


def _clip01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


class PropagationEngine:
    """Propage Ud (descendant) et Ur (montant) sur un GraphRepository."""

    def __init__(self, repo: GraphRepository) -> None:
        self._repo = repo

    # --- Calculs purs (sans écriture) -------------------------------------

    def _compute_ud(self) -> dict[str, float]:
        """Ud propagé, calculé du rang 0 vers le rang N (ordre topo inverse)."""
        ud: dict[str, float] = {}
        for node_id in reversed(self._repo.topological_order()):
            node = self._repo.get_node(node_id)
            ud_loc = node.urgency.ud_local if node.urgency.ud_local is not None else 0.0
            attenuation = 1.0
            for client in self._repo.successors(node_id):
                arc = self._repo.get_arc(node_id, client.id)
                attenuation *= 1.0 - arc.gamma * ud[client.id]
            ud[node_id] = _clip01(1.0 - (1.0 - ud_loc) * attenuation)
        return ud

    def _effective_ur_local(self, node_id: str, overrides: dict[str, float]) -> float:
        if node_id in overrides:
            return overrides[node_id]
        node = self._repo.get_node(node_id)
        if node.status is TaskStatus.DONE:
            return 0.0
        if node.status is TaskStatus.ABANDONED:
            return 1.0
        return node.urgency.ur_local if node.urgency.ur_local is not None else 0.0

    def _compute_ur(self, overrides: dict[str, float] | None = None) -> dict[str, float]:
        """Ur propagé, calculé du rang N vers le rang 0 (ordre topologique)."""
        overrides = overrides or {}
        ur: dict[str, float] = {}
        for node_id in self._repo.topological_order():
            ur_loc = self._effective_ur_local(node_id, overrides)
            attenuation = 1.0
            for supplier in self._repo.predecessors(node_id):
                arc = self._repo.get_arc(supplier.id, node_id)
                attenuation *= 1.0 - arc.beta * ur[supplier.id]
            ur[node_id] = _clip01(1.0 - (1.0 - ur_loc) * attenuation)
        return ur

    # --- Propagations persistantes -----------------------------------------

    def propagate_descending(self) -> dict[str, float]:
        """Calcule et persiste Ud sur chaque nœud. Retourne {id: ud}."""
        ud = self._compute_ud()
        now = time.time()
        for node_id, value in ud.items():
            node = self._repo.get_node(node_id)
            node.urgency.ud = value
            node.urgency.timestamp = now
            self._repo.update_node(node)
        return ud

    def propagate_ascending(self) -> dict[str, float]:
        """Calcule et persiste Ur sur chaque nœud. Retourne {id: ur}."""
        ur = self._compute_ur()
        now = time.time()
        for node_id, value in ur.items():
            node = self._repo.get_node(node_id)
            node.urgency.ur = value
            node.urgency.timestamp = now
            self._repo.update_node(node)
        return ur

    def propagate_all(self) -> dict[str, UrgencyState]:
        """Propagation descendante (Ud) puis montante (Ur).

        Persiste les valeurs et retourne {node_id: UrgencyState}.
        """
        self.propagate_descending()
        self.propagate_ascending()
        return {node.id: node.urgency for node in self._repo.nodes()}

    # --- What-if / statuts -------------------------------------------------

    def simulate_shock(self, node_id: str, new_ur_local: float) -> dict[str, float]:
        """Choc what-if : ΔUr par nœud si node_id passait à new_ur_local.

        Ne persiste RIEN : ni le ur_local simulé, ni les Ur recalculés.
        Retourne {node_id: delta_ur} (Ur choqué - Ur de référence).
        """
        if self._repo.get_node(node_id) is None:
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        baseline = self._compute_ur()
        shocked = self._compute_ur(overrides={node_id: _clip01(new_ur_local)})
        return {nid: shocked[nid] - baseline[nid] for nid in baseline}

    def apply_status(self, node_id: str, status: TaskStatus) -> dict[str, UrgencyState]:
        """Persiste le nouveau statut du nœud puis recalcule toute la propagation."""
        node = self._repo.get_node(node_id)
        if node is None:
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        node.status = status
        self._repo.update_node(node)
        return self.propagate_all()
