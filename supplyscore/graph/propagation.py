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

Dé-saturation Δl (HÉLIOS v7, U3) : sur un réseau saturé (Ur = 1.0 partout en
aval), le clip [0, 1] écrase tous les ΔUr de :meth:`PropagationEngine.simulate_shock`
à 0. :meth:`PropagationEngine.simulate_shock_detailed` fournit en plus Δl, un
écart de log-survie l(p) = −ln(1−p) calculé sur un jumeau ε-régularisé : même
récurrence montante écrite en espace survie, valeurs locales effectives
clipées dans [0, 1−ε] (ε = 1e-9) pour qu'aucun produit de survie ne s'annule,
l accumulé en espace log — strictement discriminant même en pleine
saturation. :meth:`PropagationEngine.compute_ur_batch` et
:meth:`PropagationEngine.compute_ell_batch` vectorisent les mêmes passes
topologiques sur S tirages simultanés (criticité probabiliste, lecture seule).
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

#: Seuil de saturation ε du jumeau régularisé de :meth:`simulate_shock_detailed` :
#: chaque valeur LOCALE effective y est clipée dans [0, 1−ε], si bien qu'aucun
#: produit de survie ne s'annule et que l(p) = −ln(1−p) reste fini partout.
#: Même valeur que ``supplyscore.core.explain._EPS_SAT`` (cohérence E8).
_EPS_SAT: float = 1e-9

#: Plancher des facteurs de survie du jumeau log-survie — garde purement
#: numérique (β = 1 avec survie amont sous le plus petit flottant normal),
#: jamais atteinte sur des graphes réalistes : garantit l fini dans tous les cas.
_SURVIVAL_FLOOR: float = 2.2250738585072014e-308


def _clip01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


@dataclass(frozen=True)
class ShockDetail:
    """Choc what-if détaillé : ΔUr standard ET Δl en log-survie régularisée.

    Attributes:
        delta_ur: ``{node_id: ΔUr}`` — identique à
            :meth:`PropagationEngine.simulate_shock` (Ur choqué − Ur de
            référence, pipeline standard clipé dans [0, 1]).
        delta_ell: ``{node_id: Δl}`` — écart de log-survie l(p) = −ln(1−p)
            entre l'état choqué et la référence, calculés tous deux sur le
            jumeau ε-régularisé (récurrence en espace survie, valeurs
            locales clipées dans [0, 1−ε], l accumulé en log) : reste
            strictement informatif là où le clip [0, 1] écrase ΔUr à 0
            (réseau saturé).
    """

    delta_ur: dict[str, float]
    delta_ell: dict[str, float]


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

    def _compute_ur(
        self,
        overrides: dict[str, float] | None = None,
        clip: tuple[float, float] = (0.0, 1.0),
    ) -> dict[str, float]:
        """Ur propagé, calculé du rang N vers le rang 0 (ordre topologique).

        Args:
            overrides: ``{node_id: ur_local}`` what-if substitués aux valeurs
                effectives (cf. :meth:`simulate_shock`).
            clip: bornes ``(lo, hi)`` des valeurs propagées. Le défaut
                ``(0.0, 1.0)`` reproduit le pipeline standard à l'identique
                (bit à bit). Un ``hi < 1.0`` active le jumeau ε-régularisé :
                la valeur LOCALE effective est alors clipée elle aussi dans
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
                assert arc is not None  # supplier est un prédécesseur : l'arc existe
                attenuation *= 1.0 - arc.beta * ur[supplier.id]
            ur[node_id] = min(max(1.0 - (1.0 - ur_loc) * attenuation, lo), hi)
        return ur

    def _compute_ell(self, overrides: dict[str, float] | None = None) -> dict[str, float]:
        """Log-survie l propagée du jumeau ε-régularisé (rang N vers rang 0).

        Même récurrence montante que :meth:`_compute_ur`, écrite en espace
        survie : s_i = (1 − Ur_loc_i)·Π_j ((1 − β_ji) + β_ji·s_j) — identité
        algébrique de 1 − β·Ur_j avec Ur_j = 1 − s_j — la valeur locale
        effective étant clipée dans [0, 1−ε] (ε = 1e-9). Aucun facteur ne
        s'annule donc, et l_i = −ln(s_i) est accumulé en espace log : exact
        en profondeur, jamais écrasé par le clip [0, 1] du pipeline standard
        ni par un plafond à 1−ε sur les valeurs propagées.

        Args:
            overrides: ``{node_id: ur_local}`` what-if substitués aux valeurs
                effectives (mêmes règles que :meth:`_compute_ur`).

        Returns:
            ``{node_id: l_i}`` avec l_i ≥ 0 fini ; hors saturation,
            l_i = −ln(1 − Ur_i) du pipeline standard à l'arrondi près.
        """
        overrides = overrides or {}
        ell: dict[str, float] = {}
        for node_id in self._repo.topological_order():
            ur_loc = min(max(self._effective_ur_local(node_id, overrides), 0.0), 1.0 - _EPS_SAT)
            value = -math.log(1.0 - ur_loc)
            for supplier in self._repo.predecessors(node_id):
                arc = self._repo.get_arc(supplier.id, node_id)
                assert arc is not None  # supplier est un prédécesseur : l'arc existe
                survival = math.exp(-ell[supplier.id])
                value -= math.log(max(1.0 - arc.beta + arc.beta * survival, _SURVIVAL_FLOOR))
            ell[node_id] = value
        return ell

    def _batch_draws(self, overrides: dict[str, NDArray[np.float64]]) -> int:
        """Nombre de tirages S des overrides d'un lot (1 si aucun override).

        Raises:
            ValueError: si les tableaux n'ont pas tous la même forme (S,),
                ou si un override vise un nœud inconnu du dépôt.
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
        """Ur propagé pour S tirages simultanés — passe topologique vectorisée.

        Mêmes formules que :meth:`_compute_ur`, mais chaque valeur de la passe
        est un vecteur numpy de forme (S,) : le tirage s de chaque nœud ne
        dépend que des tirages s de ses fournisseurs, les S propagations sont
        donc rigoureusement indépendantes et calculées en une seule passe.
        Méthode PURE : aucune écriture dans le dépôt.

        Avec ``S = 1`` et sans override, le résultat coïncide avec
        :meth:`_compute_ur` à 1e-12 près (testé sur graphes aléatoires).

        Benchmark indicatif (mesuré, Python 3.12 / numpy 2.4, Windows, dépôt
        mémoire 10 rangs × 100 nœuds) : 1 000 nœuds × S = 500 tirages ≈
        0.03 s la passe complète, contre ≈ 1.5 s pour 500 passes scalaires
        équivalentes (~0.003 s l'une) — le coût est dominé par le parcours du
        graphe, pas par l'axe S.

        Args:
            overrides: ``{node_id: tableau (S,) de ur_local}`` — valeurs
                locales tirées pour les nœuds choisis ; les autres nœuds
                gardent leur ``ur_local`` effectif (diffusé sur l'axe S).
                ``None`` ou vide : S = 1 (propagation de référence).
            clip: bornes ``(lo, hi)`` des valeurs propagées — mêmes règles
                que :meth:`_compute_ur` (``hi < 1.0`` clippe aussi les
                valeurs locales effectives : jumeau ε-régularisé).

        Returns:
            ``{node_id: tableau (S,) des Ur propagés}``.

        Raises:
            ValueError: si les tableaux d'override n'ont pas tous la même
                forme (S,), ou si un override vise un nœud inconnu.
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
                assert arc is not None  # supplier est un prédécesseur : l'arc existe
                attenuation *= 1.0 - arc.beta * ur[supplier.id]
            ur[node_id] = np.clip(1.0 - (1.0 - ur_loc) * attenuation, lo, hi)
        return ur

    def compute_ell_batch(
        self, overrides: dict[str, NDArray[np.float64]] | None = None
    ) -> dict[str, NDArray[np.float64]]:
        """Log-survie l du jumeau ε-régularisé pour S tirages simultanés.

        Version vectorisée de :meth:`_compute_ell` — mêmes formules, chaque
        valeur de la passe étant un vecteur numpy (S,) ; mêmes conventions
        d'overrides que :meth:`compute_ur_batch`. Méthode PURE : aucune
        écriture dans le dépôt. Avec S = 1, coïncide avec
        :meth:`_compute_ell` au bruit d'arrondi près (testé).

        Args:
            overrides: ``{node_id: tableau (S,) de ur_local}`` — valeurs
                locales tirées pour les nœuds choisis ; ``None`` ou vide :
                S = 1 (référence).

        Returns:
            ``{node_id: tableau (S,) des l_i ≥ 0}``.

        Raises:
            ValueError: si les tableaux d'override n'ont pas tous la même
                forme (S,), ou si un override vise un nœud inconnu.
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
                assert arc is not None  # supplier est un prédécesseur : l'arc existe
                survival = np.exp(-ell[supplier.id])
                value -= np.log(np.maximum(1.0 - arc.beta + arc.beta * survival, _SURVIVAL_FLOOR))
            ell[node_id] = value
        return ell

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

    def simulate_shock_detailed(self, node_id: str, new_ur_local: float) -> ShockDetail:
        """Choc what-if détaillé : ΔUr standard ET Δl log-survie par nœud.

        Méthode PURE : rien n'est persisté. ``delta_ur`` provient du pipeline
        standard — identique à :meth:`simulate_shock`. ``delta_ell`` provient
        du jumeau ε-régularisé (:meth:`_compute_ell`) : même récurrence
        montante écrite en espace survie, chaque valeur locale effective
        (choquée comprise) clipée dans [0, 1−ε] (ε = 1e-9) pour qu'aucun
        produit de survie ne s'annule, puis l(p) = −ln(1−p) accumulé en
        espace log ; Δl_i = l(Ur'_i) − l(Ur_i).

        l est la MÊME convention log-survie que la décomposition
        ``explain_ur_local`` (les ``ells``) de
        :mod:`supplyscore.core.explain` : additive le long de la chaîne dans
        le noisy-OR (les l des facteurs s'ajoutent là où les survies se
        multiplient). Sur un réseau saturé (Ur = 1.0 partout en aval), ΔUr
        vaut 0 par écrasement du clip alors que Δl reste strictement
        discriminant : il mesure l'aggravation en profondeur du choc (hors
        saturation, Δl_i = ln((1 − Ur_i)/(1 − Ur'_i)) du pipeline standard).

        Args:
            node_id: nœud choqué.
            new_ur_local: ``ur_local`` simulé du nœud (clipé dans [0, 1]).

        Returns:
            :class:`ShockDetail` — ``delta_ur`` et ``delta_ell`` par nœud.

        Raises:
            KeyError: si ``node_id`` est inconnu du dépôt.
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
