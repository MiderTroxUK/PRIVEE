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

Les règles de statut (DONE -> Ur_loc effectif 0.0, ABANDONED -> 1.0) sont
appliquées AVANT la propagation montante en déléguant à la source de vérité
unique :mod:`supplyscore.core.status_rules`.

Les arcs de secours (ArcKind.BACKUP) sont purement documentaires et INERTES
ici : le moteur ne parcourt que les voisins nominaux (comportement par défaut
de ``predecessors``/``successors`` du dépôt) et ``topological_order`` ignore
aussi les backup. Ils n'influencent donc ni Ud, ni Ur, ni ``simulate_shock``.

Toutes les valeurs propagées sont clipées dans [0, 1]. Ce module ne calcule
PAS l'adéquation (rôle de core/adequation) ; côté core, il n'importe que les
règles de statut unifiées (supplyscore.core.status_rules).
"""

from __future__ import annotations

import time

from supplyscore.core.status_rules import effective_ud_local, effective_ur_local
from supplyscore.domain.models import TaskStatus, UrgencyState
from supplyscore.graph.repository import GraphRepository


def _clip01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


class PropagationEngine:
    """Propage Ud (descendant) et Ur (montant) sur un GraphRepository."""

    def __init__(self, repo: GraphRepository) -> None:
        """Initialise le moteur sur le dépôt de graphe ``repo``."""
        self._repo = repo

    # --- Calculs purs (sans écriture) -------------------------------------

    def _compute_ud(self) -> dict[str, float]:
        """Ud propagé, calculé du rang 0 vers le rang N (ordre topo inverse)."""
        ud: dict[str, float] = {}
        for node_id in reversed(self._repo.topological_order()):
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de topological_order() du même dépôt
            ud_loc = effective_ud_local(node.status, node.urgency.ud_local)
            attenuation = 1.0
            for client in self._repo.successors(node_id):
                arc = self._repo.get_arc(node_id, client.id)
                assert arc is not None  # client est un successeur : l'arc existe
                attenuation *= 1.0 - arc.gamma * ud[client.id]
            ud[node_id] = _clip01(1.0 - (1.0 - ud_loc) * attenuation)
        return ud

    def _effective_ur_local(self, node_id: str, overrides: dict[str, float]) -> float:
        """Ur_local effectif d'un nœud : override what-if sinon règle de statut."""
        if node_id in overrides:
            return overrides[node_id]
        node = self._repo.get_node(node_id)
        assert node is not None  # id issu de topological_order() du même dépôt
        return effective_ur_local(node.status, node.urgency.ur_local)

    def _compute_ur(self, overrides: dict[str, float] | None = None) -> dict[str, float]:
        """Ur propagé, calculé du rang N vers le rang 0 (ordre topologique)."""
        overrides = overrides or {}
        ur: dict[str, float] = {}
        for node_id in self._repo.topological_order():
            ur_loc = self._effective_ur_local(node_id, overrides)
            attenuation = 1.0
            for supplier in self._repo.predecessors(node_id):
                arc = self._repo.get_arc(supplier.id, node_id)
                assert arc is not None  # supplier est un prédécesseur : l'arc existe
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
            assert node is not None  # id issu de _compute_ud() sur le même dépôt
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
            assert node is not None  # id issu de _compute_ur() sur le même dépôt
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

    def apply_status(self, node_id: str, status: TaskStatus) -> None:
        """Pose le statut sur le nœud SANS propager.

        La méthode persiste uniquement le nouveau statut ; appeler
        :meth:`propagate_all` (ou ``evaluate_all`` côté orchestrateur,
        unique point de propagation) ensuite pour recalculer Ud/Ur.

        Args:
            node_id: identifiant du nœud.
            status: nouveau statut à persister.

        Raises:
            KeyError: si ``node_id`` est inconnu du dépôt.
        """
        node = self._repo.get_node(node_id)
        if node is None:
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        node.status = status
        self._repo.update_node(node)
