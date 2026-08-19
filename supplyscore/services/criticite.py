"""Service de criticite systematique des noeuds (phase E15, Lot 15.2 ; Deltal HELIOS v7, U3).

:class:`ServiceCriticite` repond a " quel noeud ferait le plus mal s'il
tombait ? " : pour CHAQUE noeud actif d'un projet, il simule le pire choc
local (``ur_local -> 1.0``) via
:meth:`~supplyscore.graph.propagation.PropagationEngine.simulate_shock_detailed`
(calcul PUR - aucune ecriture), mesure le DeltaUr propage jusqu'au(x) client(s)
final(aux) (rang 0) et classe les noeuds du plus critique au moins critique.

Le service est PUR EN LECTURE : ``simulate_shock_detailed`` ne persiste ni le
``ur_local`` simule ni les Ur recalcules - les :class:`~supplyscore.domain.models.UrgencyState`
du depot sont bit a bit identiques avant et apres :meth:`ServiceCriticite.indice_criticite`.

CHOIX DOCUMENTE - noeuds deja satures : un reseau en crise (Ur = 1.0 partout
en aval) ecrase tous les DeltaUr a 0 par le clip [0, 1] - le choc " a vide " ne
distingue plus rien alors que c'est precisement la que le classement compte
(9 tours sur 19 de la campagne HELIOS etaient satures). Chaque point porte
donc AUSSI ``delta_ell_final`` / ``delta_ell_max`` : l'ecart de log-survie
l(p) = -ln(1-p) mesure sur le jumeau epsilon-regularise de
``simulate_shock_detailed`` (valeurs clipees dans [0, 1-epsilon], produits de
survie jamais nuls). Le tri devient ``(-DeltaUr_final, -Deltal_final, nom)`` :
identique hors saturation (Deltal ordonne comme DeltaUr, cf. test de propriete), et
strictement discriminant en pleine saturation - Deltal departage les noeuds que
DeltaUr = 0 rendait indiscernables, en mesurant l'aggravation en profondeur.

Complexite : une propagation de reference + une propagation choquee par noeud
actif (doublees par le jumeau epsilon-regularise), soit O(n_actifs x (N + E)) sur
le depot entier - instantane sur les graphes du serious game, < 2 s vises sur
1 000 noeuds (DoD E15). :meth:`ServiceCriticite.criticite_probabiliste`
ajoute une passe Monte Carlo par lots (``compute_ur_batch``) : 2 propagations
vectorisees (S tirages) par noeud actif, lecture seule, seedee, deterministe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from supplyscore.core.status_rules import effective_ur_local
from supplyscore.domain.models import SupplyNode, TaskStatus

if TYPE_CHECKING:  # import differe : evite tout cycle services.criticite <-> orchestrator
    from supplyscore.services.orchestrator import SupplyScoreService

#: Seuil en deca duquel un DeltaUr est repute nul (noeud non impacte par le choc).
_EPS_DELTA: float = 1e-12

#: Seuil d'impact au client final : un tirage " touche " le rang 0 si son DeltaUr_final depasse 0.2 (cf. :meth:`ServiceCriticite.criticite_probabiliste`).
_SEUIL_IMPACT_FINAL: float = 0.2

#: Distribution des severites de choc de la criticite probabiliste, derivee des calibrations d'evenements (:data:`supplyscore.domain.events.EVENT_CALIBRATION`) : les niveaux sont les severites forfaitaires en cliquet des deux familles graduees - accidents/pannes (mineure 0.4, majeure 0.7, critique 1.0) et alertes financieres (surveillee 0.3, procedure 0.6, defaut 0.9). Ponderation plausible documentee : les deux familles pesent autant (0.5 chacune) et, au sein d'une famille, la gravite suit la frequence terrain decroissante (mineure 0.6, intermediaire 0.3, critique 0.1) - les incidents benins sont nettement plus frequents que les defaillances franches (meme logique que la gradation bayesienne k/n de ``domain/events.py``).
_SEVERITES_CHOC: tuple[tuple[float, float], ...] = (
    (0.4, 0.5 * 0.6),  # accident/panne mineure
    (0.7, 0.5 * 0.3),  # accident/panne majeure
    (1.0, 0.5 * 0.1),  # accident/panne critique
    (0.3, 0.5 * 0.6),  # alerte financiere " surveillee "
    (0.6, 0.5 * 0.3),  # alerte financiere " procedure "
    (0.9, 0.5 * 0.1),  # alerte financiere " defaut "
)


@dataclass(frozen=True)
class PointCriticite:
    """Criticite d'un noeud : effet du pire choc local (``ur_local -> 1.0``).

    Attributes:
        node_id: identifiant du noeud choque.
        node_name: nom lisible du noeud choque.
        rank: rang dans le classement de criticite (1 = le plus critique).
        delta_ur_final: DeltaUr du/des client(s) final(aux) du projet (rang 0)
            si CE noeud passait a ``ur_local = 1.0`` - le plus grand DeltaUr
            parmi les noeuds de rang 0 du projet, 0.0 si le choc ne les
            atteint pas.
        delta_ur_max: plus grand DeltaUr observe sur TOUT le graphe (le noeud
            choque lui-meme compris).
        delta_ell_final: Deltal log-survie du/des client(s) final(aux) - meme
            convention que ``delta_ur_final`` mais sur le jumeau
            epsilon-regularise : reste discriminant quand la saturation ecrase
            DeltaUr a 0 (cf. choix documente en tete de module).
        delta_ell_max: plus grand Deltal observe sur tout le graphe.
        nb_impactes: nombre de noeuds dont ``|DeltaUr| > 1e-12`` (le noeud choque
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
    """Criticite probabiliste d'un noeud sous chocs de severite calibree.

    Attributes:
        node_id: identifiant du noeud choque.
        node_name: nom lisible du noeud choque.
        p_impact_final: probabilite empirique P(DeltaUr_final > 0.2) - part des
            tirages dont le choc fait monter le(s) client(s) final(aux) de
            plus de 0.2.
        q50_ell: mediane des Deltal au client final sur les tirages.
        q90_ell: quantile 90 % des Deltal au client final sur les tirages.
    """

    node_id: str
    node_name: str
    p_impact_final: float
    q50_ell: float
    q90_ell: float


class ServiceCriticite:
    """Analyse systematique de criticite - lecture seule au-dessus de la facade.

    Toutes les lectures passent par les composants du
    :class:`~supplyscore.services.orchestrator.SupplyScoreService` fourni
    (graphe en memoire, registre, moteur de propagation) ; le service ne
    recalcule rien hors de ``simulate_shock_detailed`` / ``compute_ur_batch``
    / ``compute_ell_batch`` et n'ecrit jamais.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service de criticite sur la facade de l'application.

        Args:
            service: facade :class:`~supplyscore.services.orchestrator.SupplyScoreService`
                (graphe, registre, moteur de propagation).
        """
        self._service = service

    # API publique

    def indice_criticite(self, project_id: str) -> list[PointCriticite]:
        """Criticite de chaque noeud actif du projet, du plus au moins critique.

        Pour chaque noeud ACTIF du projet (statut
        :attr:`~supplyscore.domain.models.TaskStatus.ACTIVE`, onboarding
        termine), simule le pire choc local ``ur_local -> 1.0`` via
        ``simulate_shock_detailed`` (PUR - rien n'est persiste) et mesure :

        - ``delta_ur_final`` : le plus grand DeltaUr parmi les noeuds de rang 0
          du projet (0.0 si le choc ne les atteint pas) ;
        - ``delta_ur_max`` : le plus grand DeltaUr sur tout le graphe ;
        - ``delta_ell_final`` / ``delta_ell_max`` : memes mesures en Deltal
          log-survie (jumeau epsilon-regularise) ;
        - ``nb_impactes`` : le nombre de noeuds avec ``|DeltaUr| > 1e-12``.

        Tri : ``delta_ur_final`` decroissant, departage par
        ``delta_ell_final`` decroissant puis par nom croissant ; le champ
        ``rank`` reflete la position finale (1 = le plus critique). Hors
        saturation, Deltal ordonne comme DeltaUr - le classement est identique a
        l'ancien tri ; sur un reseau sature (DeltaUr tous nuls), Deltal reste
        discriminant et classe les noeuds non trivialement (cf. choix
        documente en tete de module).

        Args:
            project_id: projet a analyser.

        Returns:
            Un :class:`PointCriticite` par noeud actif, tries.

        Raises:
            ValueError: si le projet est inconnu du registre ou ne compte
                aucun noeud actif (messages en francais).
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
        """Les ``n`` noeuds les plus critiques du projet (tornado UI, Lot 15.4).

        Args:
            project_id: projet a analyser.
            n: nombre maximal de points retournes (``n <= 0`` rend ``[]``).

        Returns:
            Le prefixe de longueur <= ``n`` de :meth:`indice_criticite`.

        Raises:
            ValueError: si le projet est inconnu ou sans noeud actif
                (memes regles que :meth:`indice_criticite`).
        """
        return self.indice_criticite(project_id)[: max(0, n)]

    def criticite_probabiliste(
        self, project_id: str, n_draws: int = 500, seed: int = 0
    ) -> list[PointCriticiteProbabiliste]:
        """Criticite probabiliste : chocs de severite calibree, propages par lots.

        Pour chaque noeud actif du projet, ``n_draws`` severites de choc sont
        tirees de :data:`_SEVERITES_CHOC` - la distribution derivee des
        severites forfaitaires graduees de
        :data:`supplyscore.domain.events.EVENT_CALIBRATION` (accidents/pannes
        et alertes financieres, gravites ponderees par frequence plausible,
        cf. la constante). Chaque tirage choque le noeud en CLIQUET -
        ``ur_local`` simule = max(ur_local effectif, severite), meme
        semantique que l'operateur CLIQUET de ``domain/events.py`` (une
        defaillance n'ameliore jamais l'etat) - puis le lot entier est
        propage en une passe vectorisee, en double : pipeline standard pour
        DeltaUr (:meth:`~supplyscore.graph.propagation.PropagationEngine.compute_ur_batch`)
        et jumeau epsilon-regularise pour Deltal
        (:meth:`~supplyscore.graph.propagation.PropagationEngine.compute_ell_batch`).

        Par noeud, sur la distribution des tirages au(x) client(s) final(aux)
        (le plus grand delta parmi les noeuds de rang 0, par tirage) :

        - ``p_impact_final`` = P(DeltaUr_final > 0.2) ;
        - ``q50_ell`` / ``q90_ell`` = quantiles 50 % / 90 % des Deltal_final.

        Lecture seule, seedee, deterministe : les noeuds actifs sont parcourus
        par identifiant croissant et le generateur ``numpy.random.default_rng``
        est initialise une seule fois - memes entrees, memes sorties. Tri du
        resultat : ``p_impact_final`` decroissant, puis ``q90_ell`` et
        ``q50_ell`` decroissants, puis nom croissant.

        Args:
            project_id: projet a analyser.
            n_draws: nombre de tirages Monte Carlo par noeud (>= 1).
            seed: graine du generateur pseudo-aleatoire.

        Returns:
            Un :class:`PointCriticiteProbabiliste` par noeud actif, tries.

        Raises:
            ValueError: si le projet est inconnu, sans noeud actif, ou si
                ``n_draws`` < 1 (messages en francais).
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

    # Aides internes (lecture seule)

    def _actifs_et_finals(self, project_id: str) -> tuple[list[SupplyNode], list[str]]:
        """Noeuds actifs du projet et identifiants de ses noeuds de rang 0.

        Args:
            project_id: projet a analyser.

        Returns:
            Tuple ``(noeuds actifs, ids des noeuds de rang 0)``.

        Raises:
            ValueError: si le projet est inconnu du registre ou ne compte
                aucun noeud actif (messages en francais).
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
