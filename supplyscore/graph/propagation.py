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

Propagation INCRÉMENTALE (E14.4) : le moteur tient deux ensembles « sales »
(``_dirty_ud``, ``_dirty_ur``) alimentés par l'orchestrateur — questionnaire
soumis → ``mark_dirty_ud(i)``, ``ur_local`` recalculé différent →
``mark_dirty_ur(i)``, mutation de structure → ``invalidate()``.
:meth:`PropagationEngine.propagate_incremental` ne recalcule alors que les
nœuds affectés (cônes amont/aval des nœuds sales), les valeurs des nœuds non
affectés étant relues du cache (``node.urgency.ud`` / ``node.urgency.ur``).

Toutes les valeurs propagées sont clipées dans [0, 1]. Ce module ne calcule
PAS l'adéquation (rôle de core/adequation) ; côté core, il n'importe que les
règles de statut unifiées (supplyscore.core.status_rules).
"""

from __future__ import annotations

import time

from supplyscore.core.status_rules import effective_ud_local, effective_ur_local
from supplyscore.domain.models import TaskStatus, UrgencyState
from supplyscore.graph.memory_repo import InMemoryGraphRepository
from supplyscore.graph.repository import GraphRepository


def _clip01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


class PropagationEngine:
    """Propage Ud (descendant) et Ur (montant) sur un GraphRepository."""

    def __init__(self, repo: GraphRepository) -> None:
        """Initialise le moteur sur le dépôt de graphe ``repo``.

        Avant la première propagation, TOUT est réputé sale
        (``_all_dirty = True``) : le premier :meth:`propagate_incremental`
        délègue donc à :meth:`propagate_all`.
        """
        self._repo = repo
        #: Nœuds dont le Ur effectif a changé (ur_local recalculé, statut).
        self._dirty_ur: set[str] = set()
        #: Nœuds dont le ud_local a changé (questionnaire AHP soumis).
        self._dirty_ud: set[str] = set()
        #: Tout est sale (mutation de structure ou jamais propagé).
        self._all_dirty = True
        #: ``structure_version`` du dépôt mémoire vue à la dernière propagation
        #: complète — filet de sécurité : une mutation de structure qui n'est
        #: pas passée par l'orchestrateur (ex. ``MutationService._sync_repo_arc``
        #: qui remplace un arc pour changer son β) est ainsi détectée.
        self._seen_structure_version: int | None = None

    # --- Suivi incrémental (E14.4) -----------------------------------------

    def mark_dirty_ur(self, node_id: str) -> None:
        """Marque le nœud sale côté Ur : son ``ur_local`` effectif a changé."""
        self._dirty_ur.add(node_id)

    def mark_dirty_ud(self, node_id: str) -> None:
        """Marque le nœud sale côté Ud : son ``ud_local`` a changé."""
        self._dirty_ud.add(node_id)

    def invalidate(self) -> None:
        """Marque TOUT le graphe comme sale (mutation de structure).

        Appelée par l'orchestrateur sur toute mutation de structure
        (ajout/suppression de nœud ou d'arc, recalage des rangs) : le prochain
        :meth:`propagate_incremental` délègue à :meth:`propagate_all`.
        """
        self._all_dirty = True
        self._dirty_ur.clear()
        self._dirty_ud.clear()

    def _repo_structure_version(self) -> int | None:
        """Version de structure du dépôt, ou None s'il n'en expose pas.

        Seul :class:`InMemoryGraphRepository` expose ``structure_version`` ;
        pour un autre dépôt (Neo4j), le moteur s'en remet aux appels
        explicites à :meth:`invalidate` de l'orchestrateur.
        """
        if isinstance(self._repo, InMemoryGraphRepository):
            return self._repo.structure_version
        return None

    def _descendants(self, node_id: str) -> set[str]:
        """Cône aval de ``node_id`` (exclu) via les arcs nominaux.

        Chemin rapide ``InMemoryGraphRepository.descendants`` (networkx) ;
        repli générique en largeur via ``successors`` pour tout autre dépôt
        respectant le contrat :class:`GraphRepository`.
        """
        if isinstance(self._repo, InMemoryGraphRepository):
            return self._repo.descendants(node_id)
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            for succ in self._repo.successors(stack.pop()):
                if succ.id not in seen:
                    seen.add(succ.id)
                    stack.append(succ.id)
        return seen

    def _ancestors(self, node_id: str) -> set[str]:
        """Cône amont de ``node_id`` (exclu) via les arcs nominaux.

        Chemin rapide ``InMemoryGraphRepository.ancestors`` (networkx) ;
        repli générique en largeur via ``predecessors`` pour tout autre dépôt.
        """
        if isinstance(self._repo, InMemoryGraphRepository):
            return self._repo.ancestors(node_id)
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            for pred in self._repo.predecessors(stack.pop()):
                if pred.id not in seen:
                    seen.add(pred.id)
                    stack.append(pred.id)
        return seen

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

        Réinitialise aussi l'état incrémental : tout vient d'être recalculé,
        plus rien n'est sale et la version de structure du dépôt est resynchronisée.
        """
        self.propagate_descending()
        self.propagate_ascending()
        self._dirty_ud.clear()
        self._dirty_ur.clear()
        self._all_dirty = False
        self._seen_structure_version = self._repo_structure_version()
        return {node.id: node.urgency for node in self._repo.nodes()}

    def propagate_incremental(self) -> dict[str, UrgencyState]:
        """Propagation restreinte aux nœuds affectés par les ensembles sales.

        Affectés_Ur = union, sur s ∈ dirty_ur, de {s} et descendants(s) — Ur
        se propage en aval ; Affectés_Ud = union, sur s ∈ dirty_ud, de {s} et
        ancestors(s) — Ud se propage en amont. Le Ud est recalculé en ordre topologique INVERSE
        restreint aux Affectés_Ud (les Ud des successeurs non affectés sont
        relus du cache ``node.urgency.ud``), puis le Ur en ordre topologique
        restreint aux Affectés_Ur (Ur des prédécesseurs non affectés relus du
        cache). Les timestamps sont posés comme dans :meth:`propagate_all`
        (un ``time.time()`` par phase, sur les seuls nœuds recalculés). Les
        ensembles sales sont vidés en fin d'appel.

        Délègue à :meth:`propagate_all` quand TOUT est sale : après
        :meth:`invalidate`, avant la première propagation, ou si la version
        de structure du dépôt mémoire a changé depuis la dernière propagation
        complète (mutation de structure hors orchestrateur).

        CHOIX SIMPLE documenté : si un nœud HORS zone affectée n'a jamais été
        propagé (cache absent — ``urgency.ud`` ou ``urgency.ur`` None), on
        délègue au complet plutôt que d'élargir les ensembles affectés ; le
        cas ne survient qu'une fois (à la première propagation d'un graphe),
        l'élargissement ne ferait gagner aucune passe.

        Returns:
            ``{node_id: UrgencyState}`` de TOUS les nœuds (recalculés +
            cachés) — même contrat de retour que :meth:`propagate_all`.
        """
        if self._all_dirty or self._repo_structure_version() != self._seen_structure_version:
            return self.propagate_all()  # vide les ensembles sales et resynchronise

        affected_ud: set[str] = set()
        for node_id in self._dirty_ud:
            affected_ud.add(node_id)
            affected_ud |= self._ancestors(node_id)
        affected_ur: set[str] = set()
        for node_id in self._dirty_ur:
            affected_ur.add(node_id)
            affected_ur |= self._descendants(node_id)

        for node in self._repo.nodes():
            never_propagated = (node.urgency.ud is None and node.id not in affected_ud) or (
                node.urgency.ur is None and node.id not in affected_ur
            )
            if never_propagated:  # cache absent hors zone affectée → complet
                return self.propagate_all()

        order = self._repo.topological_order()
        if affected_ud:
            self._recompute_ud_restricted(order, affected_ud)
        if affected_ur:
            self._recompute_ur_restricted(order, affected_ur)
        self._dirty_ud.clear()
        self._dirty_ur.clear()
        return {node.id: node.urgency for node in self._repo.nodes()}

    def _recompute_ud_restricted(self, order: list[str], affected: set[str]) -> None:
        """Recalcule et persiste Ud sur les seuls nœuds ``affected``.

        Parcours en ordre topologique inverse (clients avant fournisseurs),
        restreint à ``affected``. Nœud « frontière » : un successeur hors
        zone affectée contribue par son Ud en CACHE (``urgency.ud``), garanti
        non-None par le balayage « cache absent » de l'appelant ; un
        successeur affecté contribue par sa valeur fraîche (déjà calculée,
        l'ordre inverse visitant les clients d'abord).
        """
        fresh: dict[str, float] = {}
        for node_id in reversed(order):
            if node_id not in affected:
                continue
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de topological_order() du même dépôt
            ud_loc = effective_ud_local(node.status, node.urgency.ud_local)
            attenuation = 1.0
            for client in self._repo.successors(node_id):
                if client.id in fresh:
                    ud_k = fresh[client.id]
                else:
                    cached = client.urgency.ud  # frontière : successeur non affecté
                    assert cached is not None  # garanti par le balayage « cache absent »
                    ud_k = cached
                arc = self._repo.get_arc(node_id, client.id)
                assert arc is not None  # client est un successeur : l'arc existe
                attenuation *= 1.0 - arc.gamma * ud_k
            fresh[node_id] = _clip01(1.0 - (1.0 - ud_loc) * attenuation)
        now = time.time()
        for node_id, value in fresh.items():
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de la boucle ci-dessus, même dépôt
            node.urgency.ud = value
            node.urgency.timestamp = now
            self._repo.update_node(node)

    def _recompute_ur_restricted(self, order: list[str], affected: set[str]) -> None:
        """Recalcule et persiste Ur sur les seuls nœuds ``affected``.

        Parcours en ordre topologique (fournisseurs avant clients), restreint
        à ``affected``. Nœud « frontière » : un prédécesseur hors zone
        affectée contribue par son Ur en CACHE (``urgency.ur``), garanti
        non-None par le balayage « cache absent » de l'appelant ; un
        prédécesseur affecté contribue par sa valeur fraîche.
        """
        fresh: dict[str, float] = {}
        for node_id in order:
            if node_id not in affected:
                continue
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de topological_order() du même dépôt
            ur_loc = effective_ur_local(node.status, node.urgency.ur_local)
            attenuation = 1.0
            for supplier in self._repo.predecessors(node_id):
                if supplier.id in fresh:
                    ur_j = fresh[supplier.id]
                else:
                    cached = supplier.urgency.ur  # frontière : prédécesseur non affecté
                    assert cached is not None  # garanti par le balayage « cache absent »
                    ur_j = cached
                arc = self._repo.get_arc(supplier.id, node_id)
                assert arc is not None  # supplier est un prédécesseur : l'arc existe
                attenuation *= 1.0 - arc.beta * ur_j
            fresh[node_id] = _clip01(1.0 - (1.0 - ur_loc) * attenuation)
        now = time.time()
        for node_id, value in fresh.items():
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de la boucle ci-dessus, même dépôt
            node.urgency.ur = value
            node.urgency.timestamp = now
            self._repo.update_node(node)

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
