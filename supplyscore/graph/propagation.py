"""Moteur de propagation des urgences sur le DAG supply chain.

Le moteur lit les urgences LOCALES (ud_local, ur_local) deja posees sur les
noeuds par le core (hors perimetre de ce module) et calcule les urgences
PROPAGEES (ud, ur) :

- Ud (besoin declare) se propage en DESCENDANT, du client final (rang 0)
  vers les fournisseurs profonds (rang N) :
      Ud_i = 1 - (1 - Ud_loc_i) * Pi_{k  dans  Succ(i)} (1 - gamma_ik - Ud_k)

- Ur (risque reel) se propage en MONTANT, des fournisseurs profonds (rang N)
  vers le client final (rang 0) :
      Ur_i = 1 - (1 - Ur_loc_i) * Pi_{j  dans  Pred(i)} (1 - beta_ji - Ur_j)

Les regles de statut (DONE -> Ur_loc effectif 0.0, ABANDONED -> 1.0) sont
appliquees AVANT la propagation montante en deleguant a la source de verite
unique :mod:`supplyscore.core.status_rules`.

Les arcs de secours (ArcKind.BACKUP) sont purement documentaires et INERTES
ici : le moteur ne parcourt que les voisins nominaux (comportement par defaut
de ``predecessors``/``successors`` du depot) et ``topological_order`` ignore
aussi les backup. Ils n'influencent donc ni Ud, ni Ur, ni ``simulate_shock``.

Propagation INCREMENTALE (E14.4) : le moteur tient deux ensembles " sales "
(``_dirty_ud``, ``_dirty_ur``) alimentes par l'orchestrateur - questionnaire
soumis -> ``mark_dirty_ud(i)``, ``ur_local`` recalcule different ->
``mark_dirty_ur(i)``, mutation de structure -> ``invalidate()``.
:meth:`PropagationEngine.propagate_incremental` ne recalcule alors que les
noeuds affectes (cones amont/aval des noeuds sales), les valeurs des noeuds non
affectes etant relues du cache (``node.urgency.ud`` / ``node.urgency.ur``).

Toutes les valeurs propagees sont clipees dans [0, 1]. Ce module ne calcule
PAS l'adequation (role de core/adequation) ; cote core, il n'importe que les
regles de statut unifiees (supplyscore.core.status_rules).

De-saturation Deltal (HELIOS v7, U3) : sur un reseau sature (Ur = 1.0 partout en
aval), le clip [0, 1] ecrase tous les DeltaUr de :meth:`PropagationEngine.simulate_shock`
a 0. :meth:`PropagationEngine.simulate_shock_detailed` fournit en plus Deltal, un
ecart de log-survie l(p) = -ln(1-p) calcule sur un jumeau epsilon-regularise : meme
recurrence montante ecrite en espace survie, valeurs locales effectives
clipees dans [0, 1-epsilon] (epsilon = 1e-9) pour qu'aucun produit de survie ne s'annule,
l accumule en espace log - strictement discriminant meme en pleine
saturation. :meth:`PropagationEngine.compute_ur_batch` et
:meth:`PropagationEngine.compute_ell_batch` vectorisent les memes passes
topologiques sur S tirages simultanes (criticite probabiliste, lecture seule).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from supplyscore.core.status_rules import effective_ud_local, effective_ur_local
from supplyscore.domain.models import TaskStatus, UrgencyState
from supplyscore.graph.memory_repo import InMemoryGraphRepository
from supplyscore.graph.repository import GraphRepository

#: Seuil de saturation epsilon du jumeau regularise de :meth:`simulate_shock_detailed` : chaque valeur LOCALE effective y est clipee dans [0, 1-epsilon], si bien qu'aucun produit de survie ne s'annule et que l(p) = -ln(1-p) reste fini partout. Meme valeur que ``supplyscore.core.explain._EPS_SAT`` (coherence E8).
_EPS_SAT: float = 1e-9

#: Plancher des facteurs de survie du jumeau log-survie - garde purement numerique (beta = 1 avec survie amont sous le plus petit flottant normal), jamais atteinte sur des graphes realistes : garantit l fini dans tous les cas.
_SURVIVAL_FLOOR: float = 2.2250738585072014e-308


def _clip01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


@dataclass(frozen=True)
class ShockDetail:
    """Choc what-if detaille : DeltaUr standard ET Deltal en log-survie regularisee.

    Attributes:
        delta_ur: ``{node_id: DeltaUr}`` - identique a
            :meth:`PropagationEngine.simulate_shock` (Ur choque - Ur de
            reference, pipeline standard clipe dans [0, 1]).
        delta_ell: ``{node_id: Deltal}`` - ecart de log-survie l(p) = -ln(1-p)
            entre l'etat choque et la reference, calcules tous deux sur le
            jumeau epsilon-regularise (recurrence en espace survie, valeurs
            locales clipees dans [0, 1-epsilon], l accumule en log) : reste
            strictement informatif la ou le clip [0, 1] ecrase DeltaUr a 0
            (reseau sature).
    """

    delta_ur: dict[str, float]
    delta_ell: dict[str, float]


class PropagationEngine:
    """Propage Ud (descendant) et Ur (montant) sur un GraphRepository."""

    def __init__(self, repo: GraphRepository) -> None:
        """Initialise le moteur sur le depot de graphe ``repo``.

        Avant la premiere propagation, TOUT est repute sale
        (``_all_dirty = True``) : le premier :meth:`propagate_incremental`
        delegue donc a :meth:`propagate_all`.
        """
        self._repo = repo
        #: Noeuds dont le Ur effectif a change (ur_local recalcule, statut).
        self._dirty_ur: set[str] = set()
        #: Noeuds dont le ud_local a change (questionnaire AHP soumis).
        self._dirty_ud: set[str] = set()
        #: Tout est sale (mutation de structure ou jamais propage).
        self._all_dirty = True
        #: ``structure_version`` du depot memoire vue a la derniere propagation complete - filet de securite : une mutation de structure qui n'est pas passee par l'orchestrateur (ex. ``MutationService._sync_repo_arc`` qui remplace un arc pour changer son beta) est ainsi detectee.
        self._seen_structure_version: int | None = None

    # Suivi incremental (E14.4)

    def mark_dirty_ur(self, node_id: str) -> None:
        """Marque le noeud sale cote Ur : son ``ur_local`` effectif a change."""
        self._dirty_ur.add(node_id)

    def mark_dirty_ud(self, node_id: str) -> None:
        """Marque le noeud sale cote Ud : son ``ud_local`` a change."""
        self._dirty_ud.add(node_id)

    def invalidate(self) -> None:
        """Marque TOUT le graphe comme sale (mutation de structure).

        Appelee par l'orchestrateur sur toute mutation de structure
        (ajout/suppression de noeud ou d'arc, recalage des rangs) : le prochain
        :meth:`propagate_incremental` delegue a :meth:`propagate_all`.
        """
        self._all_dirty = True
        self._dirty_ur.clear()
        self._dirty_ud.clear()

    def _repo_structure_version(self) -> int | None:
        """Version de structure du depot, ou None s'il n'en expose pas.

        Seul :class:`InMemoryGraphRepository` expose ``structure_version`` ;
        pour un autre depot (Neo4j), le moteur s'en remet aux appels
        explicites a :meth:`invalidate` de l'orchestrateur.
        """
        if isinstance(self._repo, InMemoryGraphRepository):
            return self._repo.structure_version
        return None

    def _descendants(self, node_id: str) -> set[str]:
        """Cone aval de ``node_id`` (exclu) via les arcs nominaux.

        Chemin rapide ``InMemoryGraphRepository.descendants`` (networkx) ;
        repli generique en largeur via ``successors`` pour tout autre depot
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
        """Cone amont de ``node_id`` (exclu) via les arcs nominaux.

        Chemin rapide ``InMemoryGraphRepository.ancestors`` (networkx) ;
        repli generique en largeur via ``predecessors`` pour tout autre depot.
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

    # Calculs purs (sans ecriture)

    def _compute_ud(self) -> dict[str, float]:
        """Ud propage, calcule du rang 0 vers le rang N (ordre topo inverse)."""
        ud: dict[str, float] = {}
        for node_id in reversed(self._repo.topological_order()):
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de topological_order() du meme depot
            ud_loc = effective_ud_local(node.status, node.urgency.ud_local)
            attenuation = 1.0
            for client in self._repo.successors(node_id):
                arc = self._repo.get_arc(node_id, client.id)
                assert arc is not None  # client est un successeur : l'arc existe
                attenuation *= 1.0 - arc.gamma * ud[client.id]
            ud[node_id] = _clip01(1.0 - (1.0 - ud_loc) * attenuation)
        return ud

    def _effective_ur_local(self, node_id: str, overrides: dict[str, float]) -> float:
        """Ur_local effectif d'un noeud : override what-if sinon regle de statut."""
        if node_id in overrides:
            return overrides[node_id]
        node = self._repo.get_node(node_id)
        assert node is not None  # id issu de topological_order() du meme depot
        return effective_ur_local(node.status, node.urgency.ur_local)

    def _compute_ur(
        self,
        overrides: dict[str, float] | None = None,
        clip: tuple[float, float] = (0.0, 1.0),
    ) -> dict[str, float]:
        """Ur propage, calcule du rang N vers le rang 0 (ordre topologique).

        Args:
            overrides: ``{node_id: ur_local}`` what-if substitues aux valeurs
                effectives (cf. :meth:`simulate_shock`).
            clip: bornes ``(lo, hi)`` des valeurs propagees. Le defaut
                ``(0.0, 1.0)`` reproduit le pipeline standard a l'identique
                (bit a bit). Un ``hi < 1.0`` active le jumeau epsilon-regularise :
                la valeur LOCALE effective est alors clipee elle aussi dans
                ``[lo, hi]``, si bien qu'aucun facteur de survie ne s'annule.
        """
        overrides = overrides or {}
        lo, hi = clip
        regularized = hi < 1.0
        ur: dict[str, float] = {}
        for node_id in self._repo.topological_order():
            ur_loc = self._effective_ur_local(node_id, overrides)
            if regularized:
                ur_loc = min(max(ur_loc, lo), hi)
            attenuation = 1.0
            for supplier in self._repo.predecessors(node_id):
                arc = self._repo.get_arc(supplier.id, node_id)
                assert arc is not None  # supplier est un predecesseur : l'arc existe
                attenuation *= 1.0 - arc.beta * ur[supplier.id]
            ur[node_id] = min(max(1.0 - (1.0 - ur_loc) * attenuation, lo), hi)
        return ur

    def _compute_ell(self, overrides: dict[str, float] | None = None) -> dict[str, float]:
        """Log-survie l propagee du jumeau epsilon-regularise (rang N vers rang 0).

        Meme recurrence montante que :meth:`_compute_ur`, ecrite en espace
        survie : s_i = (1 - Ur_loc_i)-Pi_j ((1 - beta_ji) + beta_ji-s_j) - identite
        algebrique de 1 - beta-Ur_j avec Ur_j = 1 - s_j - la valeur locale
        effective etant clipee dans [0, 1-epsilon] (epsilon = 1e-9). Aucun facteur ne
        s'annule donc, et l_i = -ln(s_i) est accumule en espace log : exact
        en profondeur, jamais ecrase par le clip [0, 1] du pipeline standard
        ni par un plafond a 1-epsilon sur les valeurs propagees.

        Args:
            overrides: ``{node_id: ur_local}`` what-if substitues aux valeurs
                effectives (memes regles que :meth:`_compute_ur`).

        Returns:
            ``{node_id: l_i}`` avec l_i >= 0 fini ; hors saturation,
            l_i = -ln(1 - Ur_i) du pipeline standard a l'arrondi pres.
        """
        overrides = overrides or {}
        ell: dict[str, float] = {}
        for node_id in self._repo.topological_order():
            ur_loc = min(max(self._effective_ur_local(node_id, overrides), 0.0), 1.0 - _EPS_SAT)
            value = -math.log(1.0 - ur_loc)
            for supplier in self._repo.predecessors(node_id):
                arc = self._repo.get_arc(supplier.id, node_id)
                assert arc is not None  # supplier est un predecesseur : l'arc existe
                survival = math.exp(-ell[supplier.id])
                value -= math.log(max(1.0 - arc.beta + arc.beta * survival, _SURVIVAL_FLOOR))
            ell[node_id] = value
        return ell

    def _batch_draws(self, overrides: dict[str, NDArray[np.float64]]) -> int:
        """Nombre de tirages S des overrides d'un lot (1 si aucun override).

        Raises:
            ValueError: si les tableaux n'ont pas tous la meme forme (S,),
                ou si un override vise un noeud inconnu du depot.
        """
        unknown = sorted(nid for nid in overrides if self._repo.get_node(nid) is None)
        if unknown:
            raise ValueError(f"Override(s) sur nœud(s) inconnu(s) : {unknown}")
        shapes = {np.asarray(v, dtype=float).shape for v in overrides.values()}
        if len(shapes) > 1 or any(len(shape) != 1 for shape in shapes):
            raise ValueError(f"Overrides de formes incohérentes (attendu (S,)) : {sorted(shapes)}")
        return next(iter(shapes))[0] if shapes else 1

    def compute_ur_batch(
        self,
        overrides: dict[str, NDArray[np.float64]] | None = None,
        clip: tuple[float, float] = (0.0, 1.0),
    ) -> dict[str, NDArray[np.float64]]:
        """Ur propage pour S tirages simultanes - passe topologique vectorisee.

        Memes formules que :meth:`_compute_ur`, mais chaque valeur de la passe
        est un vecteur numpy de forme (S,) : le tirage s de chaque noeud ne
        depend que des tirages s de ses fournisseurs, les S propagations sont
        donc rigoureusement independantes et calculees en une seule passe.
        Methode PURE : aucune ecriture dans le depot.

        Avec ``S = 1`` et sans override, le resultat coincide avec
        :meth:`_compute_ur` a 1e-12 pres (teste sur graphes aleatoires).

        Benchmark indicatif (mesure, Python 3.12 / numpy 2.4, Windows, depot
        memoire 10 rangs x 100 noeuds) : 1 000 noeuds x S = 500 tirages ~=
        0.03 s la passe complete, contre ~= 1.5 s pour 500 passes scalaires
        equivalentes (~0.003 s l'une) - le cout est domine par le parcours du
        graphe, pas par l'axe S.

        Args:
            overrides: ``{node_id: tableau (S,) de ur_local}`` - valeurs
                locales tirees pour les noeuds choisis ; les autres noeuds
                gardent leur ``ur_local`` effectif (diffuse sur l'axe S).
                ``None`` ou vide : S = 1 (propagation de reference).
            clip: bornes ``(lo, hi)`` des valeurs propagees - memes regles
                que :meth:`_compute_ur` (``hi < 1.0`` clippe aussi les
                valeurs locales effectives : jumeau epsilon-regularise).

        Returns:
            ``{node_id: tableau (S,) des Ur propages}``.

        Raises:
            ValueError: si les tableaux d'override n'ont pas tous la meme
                forme (S,), ou si un override vise un noeud inconnu.
        """
        overrides = overrides or {}
        n_draws = self._batch_draws(overrides)
        lo, hi = clip
        regularized = hi < 1.0
        ur: dict[str, NDArray[np.float64]] = {}
        for node_id in self._repo.topological_order():
            if node_id in overrides:
                ur_loc = np.asarray(overrides[node_id], dtype=float)
            else:
                ur_loc = np.full(n_draws, self._effective_ur_local(node_id, {}), dtype=float)
            if regularized:
                ur_loc = np.clip(ur_loc, lo, hi)
            attenuation = np.ones(n_draws, dtype=float)
            for supplier in self._repo.predecessors(node_id):
                arc = self._repo.get_arc(supplier.id, node_id)
                assert arc is not None  # supplier est un predecesseur : l'arc existe
                attenuation *= 1.0 - arc.beta * ur[supplier.id]
            ur[node_id] = np.clip(1.0 - (1.0 - ur_loc) * attenuation, lo, hi)
        return ur

    def compute_ell_batch(
        self, overrides: dict[str, NDArray[np.float64]] | None = None
    ) -> dict[str, NDArray[np.float64]]:
        """Log-survie l du jumeau epsilon-regularise pour S tirages simultanes.

        Version vectorisee de :meth:`_compute_ell` - memes formules, chaque
        valeur de la passe etant un vecteur numpy (S,) ; memes conventions
        d'overrides que :meth:`compute_ur_batch`. Methode PURE : aucune
        ecriture dans le depot. Avec S = 1, coincide avec
        :meth:`_compute_ell` au bruit d'arrondi pres (teste).

        Args:
            overrides: ``{node_id: tableau (S,) de ur_local}`` - valeurs
                locales tirees pour les noeuds choisis ; ``None`` ou vide :
                S = 1 (reference).

        Returns:
            ``{node_id: tableau (S,) des l_i >= 0}``.

        Raises:
            ValueError: si les tableaux d'override n'ont pas tous la meme
                forme (S,), ou si un override vise un noeud inconnu.
        """
        overrides = overrides or {}
        n_draws = self._batch_draws(overrides)
        hi = 1.0 - _EPS_SAT
        ell: dict[str, NDArray[np.float64]] = {}
        for node_id in self._repo.topological_order():
            if node_id in overrides:
                ur_loc = np.asarray(overrides[node_id], dtype=float)
            else:
                ur_loc = np.full(n_draws, self._effective_ur_local(node_id, {}), dtype=float)
            value = -np.log(1.0 - np.clip(ur_loc, 0.0, hi))
            for supplier in self._repo.predecessors(node_id):
                arc = self._repo.get_arc(supplier.id, node_id)
                assert arc is not None  # supplier est un predecesseur : l'arc existe
                survival = np.exp(-ell[supplier.id])
                value -= np.log(np.maximum(1.0 - arc.beta + arc.beta * survival, _SURVIVAL_FLOOR))
            ell[node_id] = value
        return ell

    # Propagations persistantes

    def propagate_descending(self) -> dict[str, float]:
        """Calcule et persiste Ud sur chaque noeud. Retourne {id: ud}."""
        ud = self._compute_ud()
        now = time.time()
        for node_id, value in ud.items():
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de _compute_ud() sur le meme depot
            node.urgency.ud = value
            node.urgency.timestamp = now
            self._repo.update_node(node)
        return ud

    def propagate_ascending(self) -> dict[str, float]:
        """Calcule et persiste Ur sur chaque noeud. Retourne {id: ur}."""
        ur = self._compute_ur()
        now = time.time()
        for node_id, value in ur.items():
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de _compute_ur() sur le meme depot
            node.urgency.ur = value
            node.urgency.timestamp = now
            self._repo.update_node(node)
        return ur

    def propagate_all(self) -> dict[str, UrgencyState]:
        """Propagation descendante (Ud) puis montante (Ur).

        Persiste les valeurs et retourne {node_id: UrgencyState}.

        Reinitialise aussi l'etat incremental : tout vient d'etre recalcule,
        plus rien n'est sale et la version de structure du depot est resynchronisee.
        """
        self.propagate_descending()
        self.propagate_ascending()
        self._dirty_ud.clear()
        self._dirty_ur.clear()
        self._all_dirty = False
        self._seen_structure_version = self._repo_structure_version()
        return {node.id: node.urgency for node in self._repo.nodes()}

    def propagate_incremental(self) -> dict[str, UrgencyState]:
        """Propagation restreinte aux noeuds affectes par les ensembles sales.

        Affectes_Ur = union, sur s  dans  dirty_ur, de {s} et descendants(s) - Ur
        se propage en aval ; Affectes_Ud = union, sur s  dans  dirty_ud, de {s} et
        ancestors(s) - Ud se propage en amont. Le Ud est recalcule en ordre topologique INVERSE
        restreint aux Affectes_Ud (les Ud des successeurs non affectes sont
        relus du cache ``node.urgency.ud``), puis le Ur en ordre topologique
        restreint aux Affectes_Ur (Ur des predecesseurs non affectes relus du
        cache). Les timestamps sont poses comme dans :meth:`propagate_all`
        (un ``time.time()`` par phase, sur les seuls noeuds recalcules). Les
        ensembles sales sont vides en fin d'appel.

        Delegue a :meth:`propagate_all` quand TOUT est sale : apres
        :meth:`invalidate`, avant la premiere propagation, ou si la version
        de structure du depot memoire a change depuis la derniere propagation
        complete (mutation de structure hors orchestrateur).

        CHOIX SIMPLE documente : si un noeud HORS zone affectee n'a jamais ete
        propage (cache absent - ``urgency.ud`` ou ``urgency.ur`` None), on
        delegue au complet plutot que d'elargir les ensembles affectes ; le
        cas ne survient qu'une fois (a la premiere propagation d'un graphe),
        l'elargissement ne ferait gagner aucune passe.

        Returns:
            ``{node_id: UrgencyState}`` de TOUS les noeuds (recalcules +
            caches) - meme contrat de retour que :meth:`propagate_all`.
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
            if never_propagated:  # cache absent hors zone affectee -> complet
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
        """Recalcule et persiste Ud sur les seuls noeuds ``affected``.

        Parcours en ordre topologique inverse (clients avant fournisseurs),
        restreint a ``affected``. Noeud " frontiere " : un successeur hors
        zone affectee contribue par son Ud en CACHE (``urgency.ud``), garanti
        non-None par le balayage " cache absent " de l'appelant ; un
        successeur affecte contribue par sa valeur fraiche (deja calculee,
        l'ordre inverse visitant les clients d'abord).
        """
        fresh: dict[str, float] = {}
        for node_id in reversed(order):
            if node_id not in affected:
                continue
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de topological_order() du meme depot
            ud_loc = effective_ud_local(node.status, node.urgency.ud_local)
            attenuation = 1.0
            for client in self._repo.successors(node_id):
                if client.id in fresh:
                    ud_k = fresh[client.id]
                else:
                    cached = client.urgency.ud  # frontiere : successeur non affecte
                    assert cached is not None  # garanti par le balayage " cache absent "
                    ud_k = cached
                arc = self._repo.get_arc(node_id, client.id)
                assert arc is not None  # client est un successeur : l'arc existe
                attenuation *= 1.0 - arc.gamma * ud_k
            fresh[node_id] = _clip01(1.0 - (1.0 - ud_loc) * attenuation)
        now = time.time()
        for node_id, value in fresh.items():
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de la boucle ci-dessus, meme depot
            node.urgency.ud = value
            node.urgency.timestamp = now
            self._repo.update_node(node)

    def _recompute_ur_restricted(self, order: list[str], affected: set[str]) -> None:
        """Recalcule et persiste Ur sur les seuls noeuds ``affected``.

        Parcours en ordre topologique (fournisseurs avant clients), restreint
        a ``affected``. Noeud " frontiere " : un predecesseur hors zone
        affectee contribue par son Ur en CACHE (``urgency.ur``), garanti
        non-None par le balayage " cache absent " de l'appelant ; un
        predecesseur affecte contribue par sa valeur fraiche.
        """
        fresh: dict[str, float] = {}
        for node_id in order:
            if node_id not in affected:
                continue
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de topological_order() du meme depot
            ur_loc = effective_ur_local(node.status, node.urgency.ur_local)
            attenuation = 1.0
            for supplier in self._repo.predecessors(node_id):
                if supplier.id in fresh:
                    ur_j = fresh[supplier.id]
                else:
                    cached = supplier.urgency.ur  # frontiere : predecesseur non affecte
                    assert cached is not None  # garanti par le balayage " cache absent "
                    ur_j = cached
                arc = self._repo.get_arc(supplier.id, node_id)
                assert arc is not None  # supplier est un predecesseur : l'arc existe
                attenuation *= 1.0 - arc.beta * ur_j
            fresh[node_id] = _clip01(1.0 - (1.0 - ur_loc) * attenuation)
        now = time.time()
        for node_id, value in fresh.items():
            node = self._repo.get_node(node_id)
            assert node is not None  # id issu de la boucle ci-dessus, meme depot
            node.urgency.ur = value
            node.urgency.timestamp = now
            self._repo.update_node(node)

    # What-if / statuts

    def simulate_shock(self, node_id: str, new_ur_local: float) -> dict[str, float]:
        """Choc what-if : DeltaUr par noeud si node_id passait a new_ur_local.

        Ne persiste RIEN : ni le ur_local simule, ni les Ur recalcules.
        Retourne {node_id: delta_ur} (Ur choque - Ur de reference).
        """
        if self._repo.get_node(node_id) is None:
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        baseline = self._compute_ur()
        shocked = self._compute_ur(overrides={node_id: _clip01(new_ur_local)})
        return {nid: shocked[nid] - baseline[nid] for nid in baseline}

    def simulate_shock_detailed(self, node_id: str, new_ur_local: float) -> ShockDetail:
        """Choc what-if detaille : DeltaUr standard ET Deltal log-survie par noeud.

        Methode PURE : rien n'est persiste. ``delta_ur`` provient du pipeline
        standard - identique a :meth:`simulate_shock`. ``delta_ell`` provient
        du jumeau epsilon-regularise (:meth:`_compute_ell`) : meme recurrence
        montante ecrite en espace survie, chaque valeur locale effective
        (choquee comprise) clipee dans [0, 1-epsilon] (epsilon = 1e-9) pour qu'aucun
        produit de survie ne s'annule, puis l(p) = -ln(1-p) accumule en
        espace log ; Deltal_i = l(Ur'_i) - l(Ur_i).

        l est la MEME convention log-survie que la decomposition
        ``explain_ur_local`` (les ``ells``) de
        :mod:`supplyscore.core.explain` : additive le long de la chaine dans
        le noisy-OR (les l des facteurs s'ajoutent la ou les survies se
        multiplient). Sur un reseau sature (Ur = 1.0 partout en aval), DeltaUr
        vaut 0 par ecrasement du clip alors que Deltal reste strictement
        discriminant : il mesure l'aggravation en profondeur du choc (hors
        saturation, Deltal_i = ln((1 - Ur_i)/(1 - Ur'_i)) du pipeline standard).

        Args:
            node_id: noeud choque.
            new_ur_local: ``ur_local`` simule du noeud (clipe dans [0, 1]).

        Returns:
            :class:`ShockDetail` - ``delta_ur`` et ``delta_ell`` par noeud.

        Raises:
            KeyError: si ``node_id`` est inconnu du depot.
        """
        if self._repo.get_node(node_id) is None:
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        overrides = {node_id: _clip01(new_ur_local)}
        baseline = self._compute_ur()
        shocked = self._compute_ur(overrides=overrides)
        baseline_ell = self._compute_ell()
        shocked_ell = self._compute_ell(overrides=overrides)
        return ShockDetail(
            delta_ur={nid: shocked[nid] - baseline[nid] for nid in baseline},
            delta_ell={nid: shocked_ell[nid] - baseline_ell[nid] for nid in baseline_ell},
        )

    def apply_status(self, node_id: str, status: TaskStatus) -> None:
        """Pose le statut sur le noeud SANS propager.

        La methode persiste uniquement le nouveau statut ; appeler
        :meth:`propagate_all` (ou ``evaluate_all`` cote orchestrateur,
        unique point de propagation) ensuite pour recalculer Ud/Ur.

        Args:
            node_id: identifiant du noeud.
            status: nouveau statut a persister.

        Raises:
            KeyError: si ``node_id`` est inconnu du depot.
        """
        node = self._repo.get_node(node_id)
        if node is None:
            raise KeyError(f"Nœud inconnu : {node_id!r}")
        node.status = status
        self._repo.update_node(node)
