"""Service de criticité systématique des nœuds (phase E15, Lot 15.2 ; Δl HÉLIOS v7, U3).

:class:`ServiceCriticite` répond à « quel nœud ferait le plus mal s'il
tombait ? » : pour CHAQUE nœud actif d'un projet, il simule le pire choc
local (``ur_local -> 1.0``) via
:meth:`~supplyscore.graph.propagation.PropagationEngine.simulate_shock_detailed`
(calcul PUR — aucune écriture), mesure le ΔUr propagé jusqu'au(x) client(s)
final(aux) (rang 0) et classe les nœuds du plus critique au moins critique.

Le service est PUR EN LECTURE : ``simulate_shock_detailed`` ne persiste ni le
``ur_local`` simulé ni les Ur recalculés — les :class:`~supplyscore.domain.models.UrgencyState`
du dépôt sont bit à bit identiques avant et après :meth:`ServiceCriticite.indice_criticite`.

CHOIX DOCUMENTÉ — nœuds déjà saturés : un réseau en crise (Ur = 1.0 partout
en aval) écrase tous les ΔUr à 0 par le clip [0, 1] — le choc « à vide » ne
distingue plus rien alors que c'est précisément là que le classement compte
(9 tours sur 19 de la campagne HÉLIOS étaient saturés). Chaque point porte
donc AUSSI ``delta_ell_final`` / ``delta_ell_max`` : l'écart de log-survie
l(p) = −ln(1−p) mesuré sur le jumeau ε-régularisé de
``simulate_shock_detailed`` (valeurs clipées dans [0, 1−ε], produits de
survie jamais nuls). Le tri devient ``(-ΔUr_final, -Δl_final, nom)`` :
identique hors saturation (Δl ordonne comme ΔUr, cf. test de propriété), et
strictement discriminant en pleine saturation — Δl départage les nœuds que
ΔUr = 0 rendait indiscernables, en mesurant l'aggravation en profondeur.

Complexité : une propagation de référence + une propagation choquée par nœud
actif (doublées par le jumeau ε-régularisé), soit O(n_actifs × (N + E)) sur
le dépôt entier — instantané sur les graphes du serious game, < 2 s visés sur
1 000 nœuds (DoD E15). :meth:`ServiceCriticite.criticite_probabiliste`
ajoute une passe Monte Carlo par lots (``compute_ur_batch``) : 2 propagations
vectorisées (S tirages) par nœud actif, lecture seule, seedée, déterministe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from supplyscore.core.status_rules import effective_ur_local
from supplyscore.domain.models import SupplyNode, TaskStatus

if TYPE_CHECKING:  # import différé : évite tout cycle services.criticite <-> orchestrator
    from supplyscore.services.orchestrator import SupplyScoreService

#: Seuil en deçà duquel un ΔUr est réputé nul (nœud non impacté par le choc).
_EPS_DELTA: float = 1e-12

#: Seuil d'impact au client final : un tirage « touche » le rang 0 si son
#: ΔUr_final dépasse 0.2 (cf. :meth:`ServiceCriticite.criticite_probabiliste`).
_SEUIL_IMPACT_FINAL: float = 0.2

#: Distribution des sévérités de choc de la criticité probabiliste, dérivée
#: des calibrations d'événements (:data:`supplyscore.domain.events.EVENT_CALIBRATION`) :
#: les niveaux sont les sévérités forfaitaires en cliquet des deux familles
#: graduées — accidents/pannes (mineure 0.4, majeure 0.7, critique 1.0) et
#: alertes financières (surveillée 0.3, procédure 0.6, défaut 0.9). Pondération
#: plausible documentée : les deux familles pèsent autant (0.5 chacune) et, au
#: sein d'une famille, la gravité suit la fréquence terrain décroissante
#: (mineure 0.6, intermédiaire 0.3, critique 0.1) — les incidents bénins sont
#: nettement plus fréquents que les défaillances franches (même logique que la
#: gradation bayésienne k/n de ``domain/events.py``).
_SEVERITES_CHOC: tuple[tuple[float, float], ...] = (
    (0.4, 0.5 * 0.6),  # accident/panne mineure
    (0.7, 0.5 * 0.3),  # accident/panne majeure
    (1.0, 0.5 * 0.1),  # accident/panne critique
    (0.3, 0.5 * 0.6),  # alerte financière « surveillée »
    (0.6, 0.5 * 0.3),  # alerte financière « procédure »
    (0.9, 0.5 * 0.1),  # alerte financière « défaut »
)


@dataclass(frozen=True)
class PointCriticite:
    """Criticité d'un nœud : effet du pire choc local (``ur_local -> 1.0``).

    Attributes:
        node_id: identifiant du nœud choqué.
        node_name: nom lisible du nœud choqué.
        rank: rang dans le classement de criticité (1 = le plus critique).
        delta_ur_final: ΔUr du/des client(s) final(aux) du projet (rang 0)
            si CE nœud passait à ``ur_local = 1.0`` — le plus grand ΔUr
            parmi les nœuds de rang 0 du projet, 0.0 si le choc ne les
            atteint pas.
        delta_ur_max: plus grand ΔUr observé sur TOUT le graphe (le nœud
            choqué lui-même compris).
        delta_ell_final: Δl log-survie du/des client(s) final(aux) — même
            convention que ``delta_ur_final`` mais sur le jumeau
            ε-régularisé : reste discriminant quand la saturation écrase
            ΔUr à 0 (cf. choix documenté en tête de module).
        delta_ell_max: plus grand Δl observé sur tout le graphe.
        nb_impactes: nombre de nœuds dont ``|ΔUr| > 1e-12`` (le nœud choqué
            compris s'il bouge).
    """

    node_id: str
    node_name: str
    rank: int
    delta_ur_final: float
    delta_ur_max: float
    delta_ell_final: float
    delta_ell_max: float
    nb_impactes: int


@dataclass(frozen=True)
class PointCriticiteProbabiliste:
    """Criticité probabiliste d'un nœud sous chocs de sévérité calibrée.

    Attributes:
        node_id: identifiant du nœud choqué.
        node_name: nom lisible du nœud choqué.
        p_impact_final: probabilité empirique P(ΔUr_final > 0.2) — part des
            tirages dont le choc fait monter le(s) client(s) final(aux) de
            plus de 0.2.
        q50_ell: médiane des Δl au client final sur les tirages.
        q90_ell: quantile 90 % des Δl au client final sur les tirages.
    """

    node_id: str
    node_name: str
    p_impact_final: float
    q50_ell: float
    q90_ell: float


class ServiceCriticite:
    """Analyse systématique de criticité — lecture seule au-dessus de la façade.

    Toutes les lectures passent par les composants du
    :class:`~supplyscore.services.orchestrator.SupplyScoreService` fourni
    (graphe en mémoire, registre, moteur de propagation) ; le service ne
    recalcule rien hors de ``simulate_shock_detailed`` / ``compute_ur_batch``
    / ``compute_ell_batch`` et n'écrit jamais.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service de criticité sur la façade de l'application.

        Args:
            service: façade :class:`~supplyscore.services.orchestrator.SupplyScoreService`
                (graphe, registre, moteur de propagation).
        """
        self._service = service

    # --- API publique -------------------------------------------------------------------

    def indice_criticite(self, project_id: str) -> list[PointCriticite]:
        """Criticité de chaque nœud actif du projet, du plus au moins critique.

        Pour chaque nœud ACTIF du projet (statut
        :attr:`~supplyscore.domain.models.TaskStatus.ACTIVE`, onboarding
        terminé), simule le pire choc local ``ur_local -> 1.0`` via
        ``simulate_shock_detailed`` (PUR — rien n'est persisté) et mesure :

        - ``delta_ur_final`` : le plus grand ΔUr parmi les nœuds de rang 0
          du projet (0.0 si le choc ne les atteint pas) ;
        - ``delta_ur_max`` : le plus grand ΔUr sur tout le graphe ;
        - ``delta_ell_final`` / ``delta_ell_max`` : mêmes mesures en Δl
          log-survie (jumeau ε-régularisé) ;
        - ``nb_impactes`` : le nombre de nœuds avec ``|ΔUr| > 1e-12``.

        Tri : ``delta_ur_final`` décroissant, départagé par
        ``delta_ell_final`` décroissant puis par nom croissant ; le champ
        ``rank`` reflète la position finale (1 = le plus critique). Hors
        saturation, Δl ordonne comme ΔUr — le classement est identique à
        l'ancien tri ; sur un réseau saturé (ΔUr tous nuls), Δl reste
        discriminant et classe les nœuds non trivialement (cf. choix
        documenté en tête de module).

        Args:
            project_id: projet à analyser.

        Returns:
            Un :class:`PointCriticite` par nœud actif, triés.

        Raises:
            ValueError: si le projet est inconnu du registre ou ne compte
                aucun nœud actif (messages en français).
        """
        actifs, finals = self._actifs_et_finals(project_id)

        mesures: list[tuple[SupplyNode, float, float, float, float, int]] = []
        for node in actifs:
            detail = self._service.propagation.simulate_shock_detailed(node.id, 1.0)
            delta_final = max((detail.delta_ur[final_id] for final_id in finals), default=0.0)
            delta_max = max(detail.delta_ur.values(), default=0.0)
            ell_final = max((detail.delta_ell[final_id] for final_id in finals), default=0.0)
            ell_max = max(detail.delta_ell.values(), default=0.0)
            nb_impactes = sum(1 for delta in detail.delta_ur.values() if abs(delta) > _EPS_DELTA)
            mesures.append((node, delta_final, delta_max, ell_final, ell_max, nb_impactes))

        mesures.sort(key=lambda mesure: (-mesure[1], -mesure[3], mesure[0].name))
        return [
            PointCriticite(
                node_id=node.id,
                node_name=node.name,
                rank=position,
                delta_ur_final=delta_final,
                delta_ur_max=delta_max,
                delta_ell_final=ell_final,
                delta_ell_max=ell_max,
                nb_impactes=nb_impactes,
            )
            for position, (node, delta_final, delta_max, ell_final, ell_max, nb_impactes) in (
                enumerate(mesures, start=1)
            )
        ]

    def top(self, project_id: str, n: int = 15) -> list[PointCriticite]:
        """Les ``n`` nœuds les plus critiques du projet (tornado UI, Lot 15.4).

        Args:
            project_id: projet à analyser.
            n: nombre maximal de points retournés (``n <= 0`` rend ``[]``).

        Returns:
            Le préfixe de longueur <= ``n`` de :meth:`indice_criticite`.

        Raises:
            ValueError: si le projet est inconnu ou sans nœud actif
                (mêmes règles que :meth:`indice_criticite`).
        """
        return self.indice_criticite(project_id)[: max(0, n)]

    def criticite_probabiliste(
        self, project_id: str, n_draws: int = 500, seed: int = 0
    ) -> list[PointCriticiteProbabiliste]:
        """Criticité probabiliste : chocs de sévérité calibrée, propagés par lots.

        Pour chaque nœud actif du projet, ``n_draws`` sévérités de choc sont
        tirées de :data:`_SEVERITES_CHOC` — la distribution dérivée des
        sévérités forfaitaires graduées de
        :data:`supplyscore.domain.events.EVENT_CALIBRATION` (accidents/pannes
        et alertes financières, gravités pondérées par fréquence plausible,
        cf. la constante). Chaque tirage choque le nœud en CLIQUET —
        ``ur_local`` simulé = max(ur_local effectif, sévérité), même
        sémantique que l'opérateur CLIQUET de ``domain/events.py`` (une
        défaillance n'améliore jamais l'état) — puis le lot entier est
        propagé en une passe vectorisée, en double : pipeline standard pour
        ΔUr (:meth:`~supplyscore.graph.propagation.PropagationEngine.compute_ur_batch`)
        et jumeau ε-régularisé pour Δl
        (:meth:`~supplyscore.graph.propagation.PropagationEngine.compute_ell_batch`).

        Par nœud, sur la distribution des tirages au(x) client(s) final(aux)
        (le plus grand delta parmi les nœuds de rang 0, par tirage) :

        - ``p_impact_final`` = P(ΔUr_final > 0.2) ;
        - ``q50_ell`` / ``q90_ell`` = quantiles 50 % / 90 % des Δl_final.

        Lecture seule, seedée, déterministe : les nœuds actifs sont parcourus
        par identifiant croissant et le générateur ``numpy.random.default_rng``
        est initialisé une seule fois — mêmes entrées, mêmes sorties. Tri du
        résultat : ``p_impact_final`` décroissant, puis ``q90_ell`` et
        ``q50_ell`` décroissants, puis nom croissant.

        Args:
            project_id: projet à analyser.
            n_draws: nombre de tirages Monte Carlo par nœud (>= 1).
            seed: graine du générateur pseudo-aléatoire.

        Returns:
            Un :class:`PointCriticiteProbabiliste` par nœud actif, triés.

        Raises:
            ValueError: si le projet est inconnu, sans nœud actif, ou si
                ``n_draws`` < 1 (messages en français).
        """
        if n_draws < 1:
            raise ValueError(f"n_draws doit être >= 1 (reçu {n_draws})")
        actifs, finals = self._actifs_et_finals(project_id)
        actifs = sorted(actifs, key=lambda node: node.id)

        rng = np.random.default_rng(seed)
        niveaux = np.array([niveau for niveau, _ in _SEVERITES_CHOC])
        poids = np.array([poids for _, poids in _SEVERITES_CHOC])
        poids = poids / poids.sum()

        propagation = self._service.propagation
        base_ur = {nid: arr[0] for nid, arr in propagation.compute_ur_batch().items()}
        base_ell = {nid: arr[0] for nid, arr in propagation.compute_ell_batch().items()}

        points: list[PointCriticiteProbabiliste] = []
        for node in actifs:
            severites = rng.choice(niveaux, size=n_draws, p=poids)
            ur_loc = effective_ur_local(node.status, node.urgency.ur_local)
            overrides = {node.id: np.minimum(np.maximum(severites, ur_loc), 1.0)}

            shocked_ur = propagation.compute_ur_batch(overrides)
            shocked_ell = propagation.compute_ell_batch(overrides)
            if finals:
                delta_ur_final = np.max(
                    np.stack([shocked_ur[fid] - base_ur[fid] for fid in finals]), axis=0
                )
                delta_ell_final = np.max(
                    np.stack([shocked_ell[fid] - base_ell[fid] for fid in finals]), axis=0
                )
            else:  # pas de rang 0 dans le projet : deltas finaux nuls par convention
                delta_ur_final = np.zeros(n_draws)
                delta_ell_final = np.zeros(n_draws)

            points.append(
                PointCriticiteProbabiliste(
                    node_id=node.id,
                    node_name=node.name,
                    p_impact_final=float(np.mean(delta_ur_final > _SEUIL_IMPACT_FINAL)),
                    q50_ell=float(np.quantile(delta_ell_final, 0.5)),
                    q90_ell=float(np.quantile(delta_ell_final, 0.9)),
                )
            )

        points.sort(key=lambda p: (-p.p_impact_final, -p.q90_ell, -p.q50_ell, p.node_name))
        return points

    # --- Aides internes (lecture seule) ---------------------------------------------------

    def _actifs_et_finals(self, project_id: str) -> tuple[list[SupplyNode], list[str]]:
        """Nœuds actifs du projet et identifiants de ses nœuds de rang 0.

        Args:
            project_id: projet à analyser.

        Returns:
            Tuple ``(nœuds actifs, ids des nœuds de rang 0)``.

        Raises:
            ValueError: si le projet est inconnu du registre ou ne compte
                aucun nœud actif (messages en français).
        """
        service = self._service
        if service.registry.get_project(project_id) is None:
            raise ValueError(f"Projet inconnu : {project_id!r}")
        project_nodes = service.repo.nodes_by_project(project_id)
        actifs = [
            node
            for node in project_nodes
            if node.status == TaskStatus.ACTIVE and node.onboarding_state != "draft"
        ]
        if not actifs:
            raise ValueError(
                f"Analyse de criticité impossible pour le projet {project_id!r} : "
                "aucun nœud actif (statut ACTIVE, onboarding terminé)."
            )
        finals = [node.id for node in project_nodes if node.rank == 0]
        return actifs, finals
