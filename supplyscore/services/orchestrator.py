"""Couche d'orchestration — relie le core mathématique, le graphe et la persistance.

Pipeline complet pour un projet à la date t :
  1. Ud_local  : dernier questionnaire AHP de chaque nœud (lissé EMA si historique)
  2. Ur_local  : UrModel sur les KPIs du nœud
  3. Propagation descendante (Ud) et montante (Ur) sur le DAG
  4. Adéquation A, fausse urgence F, risque caché H par nœud
  5. Persistance de l'historique d'urgence dans la base du client
"""

from __future__ import annotations

import dataclasses
import threading
import zlib
from collections import OrderedDict
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np

from supplyscore.core import (
    BLOCKS,
    CONSISTENCY_THRESHOLD,
    AdequationEngine,
    UrModel,
    compute_ud,
    run_ahp,
    ud_smoothed,
)
from supplyscore.core.clock import Clock, GameClock, SystemClock, iso_week, project_hours
from supplyscore.data import ClientDatabase, RandomSupplyChainGenerator, RegistryDatabase
from supplyscore.domain.milestones import MilestoneStatus, derive_node_status
from supplyscore.domain.models import (
    AHPAssessment,
    Project,
    SupplyArc,
    SupplyNode,
    TaskStatus,
    UrgencyState,
)
from supplyscore.graph import GraphRepository, InMemoryGraphRepository, PropagationEngine
from supplyscore.mc.lead_time import N_TIRAGES_MAX, N_TIRAGES_MIN, ResultatMC, SimulateurLeadTime
from supplyscore.mcda.promethee import Critere, PrometheeII, ResultatPromethee
from supplyscore.services.mutations import MutationService

#: nombre maximal de ClientDatabase gardées ouvertes simultanément (cache LRU).
_CLIENT_CACHE_SIZE = 64


class SupplyScoreService:
    """Façade unique consommée par l'UI et les scripts.

    Thread-safety : le serveur Dash sert chaque requête dans un thread
    distinct ; les méthodes publiques mutantes prennent donc ``self._lock``
    (RLock réentrant — les méthodes peuvent s'appeler entre elles).
    """

    def __init__(
        self,
        db_dir: Path | str = "data_store",
        repo: GraphRepository | None = None,
        ur_model: UrModel | None = None,
        adequation: AdequationEngine | None = None,
        rho_smoothing: float = 0.3,
        clock: Clock | None = None,
    ):
        """Initialise la façade et ses dépendances (bases, graphe, modèles).

        Args:
            db_dir: répertoire racine des bases SQLite.
            repo: dépôt de graphe (en mémoire par défaut).
            ur_model: modèle d'urgence réelle (défaut : ``UrModel()``).
            adequation: moteur d'adéquation (défaut : ``AdequationEngine()``).
            rho_smoothing: coefficient de lissage EMA du Ud_local.
            clock: horloge par défaut (mode « réel ») ; chaque projet peut
                la remplacer par une :class:`GameClock` via
                :meth:`set_clock_mode` (mode « jeu », serious game).
        """
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.registry = RegistryDatabase(self.db_dir)
        self.repo = repo if repo is not None else InMemoryGraphRepository()
        self.ur_model = ur_model if ur_model is not None else UrModel()
        self.adequation = adequation if adequation is not None else AdequationEngine()
        self.propagation = PropagationEngine(self.repo)
        self.rho = rho_smoothing
        self.clock: Clock = clock if clock is not None else SystemClock()
        self._client_dbs: OrderedDict[str, ClientDatabase] = OrderedDict()
        self._lock = threading.RLock()
        #: Cache léger du UrModel effectif par projet (omega FBWM fusionné),
        #: invalidé projet par projet dans :meth:`set_poids_criteres`.
        self._ur_models: dict[str, UrModel] = {}
        #: Dernier résultat Monte Carlo par projet (IC95 pour l'UI), purgé au
        #: retour en mode analytique. Cf. :meth:`last_mc_result`.
        self._last_mc: dict[str, ResultatMC] = {}
        self.mutations = MutationService(
            registry=self.registry,
            client_db_factory=self.client_db,
            clock=self.clock,
            repo=self.repo,
        )

    # --- cycle de vie -----------------------------------------------------------

    def close(self) -> None:
        """Ferme le registre et toutes les bases client encore ouvertes."""
        with self._lock:
            for db in self._client_dbs.values():
                db.close()
            self._client_dbs.clear()
            self.registry.close()

    def __enter__(self) -> SupplyScoreService:
        """Entre dans le context manager (retourne la façade elle-même)."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Sort du context manager en fermant toutes les bases."""
        self.close()

    # --- accès bases client --------------------------------------------------

    def client_db(self, node_id: str) -> ClientDatabase:
        """Retourne (en la créant au besoin) la base SQLite dédiée au nœud.

        Le cache est un LRU borné à ``_CLIENT_CACHE_SIZE`` entrées : la base la
        plus anciennement utilisée est fermée puis évincée au-delà de la borne.
        """
        with self._lock:
            db = self._client_dbs.get(node_id)
            if db is not None:
                self._client_dbs.move_to_end(node_id)
                return db
            db = ClientDatabase(self.db_dir, node_id)
            self._client_dbs[node_id] = db
            if len(self._client_dbs) > _CLIENT_CACHE_SIZE:
                _, evicted = self._client_dbs.popitem(last=False)
                evicted.close()
            return db

    # --- gestion projet / graphe ----------------------------------------------

    def create_project(
        self, project: Project, nodes: list[SupplyNode], arcs: list[SupplyArc]
    ) -> None:
        """Persiste le projet, ses nœuds et ses arcs, et alimente le graphe."""
        with self._lock:
            self.registry.save_project(project)
            for n in nodes:
                self.registry.save_node(n)
                self.repo.add_node(n)
            for a in arcs:
                self.registry.save_arc(a)
                self.repo.add_arc(a)

    def load_graph_from_registry(self) -> None:
        """Recharge le graphe en mémoire depuis la base registre (au démarrage)."""
        self.repo.clear()
        for n in self.registry.list_nodes():
            self.repo.add_node(n)
        for a in self.registry.list_arcs():
            self.repo.add_arc(a)

    def add_node(
        self,
        node: SupplyNode,
        supplies_to: list[str] | None = None,
        gamma: float = 0.5,
        beta: float = 0.5,
    ) -> None:
        """Ajoute un client/fournisseur de rang quelconque, relié à ses clients aval.

        Après l'ajout des arcs, les rangs de TOUS les nœuds sont recalés sur la
        définition canonique « plus longue distance vers un puits » (faiblesse
        #10 : le rang « 1 + max(cibles) » déduit par l'UI peut diverger de
        cette définition dans les graphes en diamant).
        """
        with self._lock:
            self.registry.save_node(node)
            self.repo.add_node(node)
            for target in supplies_to or []:
                arc = SupplyArc(source_id=node.id, target_id=target, gamma=gamma, beta=beta)
                self.registry.save_arc(arc)
                self.repo.add_arc(arc)
            self._reassign_ranks()

    def remove_arc(self, source_id: str, target_id: str) -> None:
        """Retire l'arc fournisseur -> client, recale les rangs puis réévalue.

        L'arc est retiré du dépôt en mémoire ET du registre SQLite ; les rangs
        canoniques sont ensuite recalculés (un fournisseur devenu isolé passe
        au rang 0) et le réseau entier est réévalué avec persistance.

        Args:
            source_id: id du nœud fournisseur (origine de l'arc).
            target_id: id du nœud client (cible de l'arc).

        Raises:
            KeyError: si l'arc est inconnu (message en français, rien n'est
                modifié dans ce cas).
        """
        with self._lock:
            self.repo.remove_arc(source_id, target_id)  # KeyError français si absent
            self.registry.delete_arc(source_id, target_id)
            self._reassign_ranks()
            self.evaluate_all(persist=True)

    def remove_node(self, node_id: str) -> None:
        """Supprime le nœud du graphe et du registre — sa base SQLite est ARCHIVÉE.

        Le fichier ``<node_id>.sqlite`` du client n'est PAS supprimé : il est
        conservé en archive (historique des évaluations AHP, snapshots KPI,
        série d'urgence) pour audit ultérieur. Seule la connexion ouverte est
        fermée proprement puis évincée du cache LRU. La suppression cascade
        dans le registre (arcs incidents, tags, jalons, onboarding), puis les
        rangs canoniques sont recalculés et le réseau réévalué.

        Args:
            node_id: id du nœud à supprimer.

        Raises:
            KeyError: si le nœud est inconnu (message en français, rien n'est
                modifié dans ce cas).
        """
        with self._lock:
            if self.repo.get_node(node_id) is None:
                raise KeyError(f"Nœud inconnu : {node_id!r}")
            db = self._client_dbs.pop(node_id, None)
            if db is not None:
                db.close()  # le FICHIER sqlite reste sur disque (archive)
            self.registry.delete_node(node_id)  # cascade arcs/tags/jalons/onboarding
            self.repo.remove_node(node_id)
            self._reassign_ranks()
            self.evaluate_all(persist=True)

    def reassign_ranks(self) -> None:
        """Recale les rangs canoniques (API publique — éditeurs de graphe)."""
        with self._lock:
            self._reassign_ranks()

    def _reassign_ranks(self) -> None:
        """Recale tous les rangs sur la définition canonique et persiste les écarts.

        Le rang canonique d'un nœud est sa plus longue distance vers un puits
        via les arcs NOMINAUX (``InMemoryGraphRepository.assign_ranks``). Pour
        un dépôt qui n'expose pas ``assign_ranks``, la même définition est
        recalculée ici à partir du contrat :class:`GraphRepository` (tri
        topologique + successeurs nominaux). Chaque nœud dont le rang a changé
        est mis à jour dans le dépôt ET sauvegardé dans le registre.
        """
        with self._lock:
            previous = {node.id: node.rank for node in self.repo.nodes()}
            ranks: dict[str, int]
            if isinstance(self.repo, InMemoryGraphRepository):
                ranks = self.repo.assign_ranks()
            else:  # définition canonique recalculée via le contrat abstrait
                ranks = {}
                for node_id in reversed(self.repo.topological_order()):
                    successors = self.repo.successors(node_id)
                    ranks[node_id] = 1 + max(ranks[s.id] for s in successors) if successors else 0
            for node_id, rank in ranks.items():
                if previous.get(node_id) == rank:
                    continue
                node = self.repo.get_node(node_id)
                if node is None:  # pragma: no cover - assign_ranks ne renvoie que des nœuds connus
                    continue
                node.rank = rank
                self.repo.update_node(node)
                self.registry.save_node(node)

    def set_status(self, node_id: str, status: TaskStatus) -> dict[str, UrgencyState]:
        """Tâche finie/abandonnée : pose le statut puis réévalue UNE fois le réseau.

        Si le nœud a des jalons, le statut CASCADE sur eux (marquer un nœud
        terminé termine ses jalons actifs, l'abandonner les abandonne) — le
        statut global dérivant des jalons, c'est la seule façon cohérente de
        le changer. ``evaluate_all(persist=True)`` (appelé une seule fois) se
        charge ensuite des règles de statut et de la propagation.
        """
        with self._lock:
            status = TaskStatus(status)
            milestones = self.registry.list_milestones(node_id)
            if milestones and status in (TaskStatus.DONE, TaskStatus.ABANDONED):
                target = (
                    MilestoneStatus.DONE if status == TaskStatus.DONE else MilestoneStatus.ABANDONED
                )
                for milestone in milestones:
                    if milestone.status == MilestoneStatus.ACTIVE:
                        milestone.status = target
                        if target == MilestoneStatus.DONE:
                            milestone.progress = 1.0
                        self.registry.save_milestone(milestone)
            self.registry.set_node_status(node_id, status)
            node = self.repo.get_node(node_id)
            if node is not None:
                node.status = status
                self.repo.update_node(node)
            return self.evaluate_all(persist=True)

    # --- horloge bimodale par projet ---------------------------------------------

    def clock_for(self, project_id: str) -> Clock:
        """Horloge effective du projet : GameClock si mode « jeu », sinon l'horloge réelle."""
        raw = self.registry.get_setting(project_id, "clock")
        if isinstance(raw, dict) and raw.get("mode") == "game":
            return GameClock(
                start_ts=float(raw["start_ts"]),
                weeks_elapsed=int(raw.get("weeks_elapsed", 0)),
            )
        return self.clock

    def clock_mode(self, project_id: str) -> str:
        """Mode d'horloge du projet : ``"game"`` ou ``"real"`` (défaut)."""
        raw = self.registry.get_setting(project_id, "clock")
        if isinstance(raw, dict) and raw.get("mode") == "game":
            return "game"
        return "real"

    def set_clock_mode(self, project_id: str, mode: str) -> None:
        """Bascule l'horloge du projet entre temps réel et temps de jeu.

        En mode « jeu », l'origine est posée à l'instant de la bascule et les
        semaines écoulées repartent de zéro (sauf si le projet était déjà en
        mode jeu : son avancement est conservé).
        """
        with self._lock:
            if mode not in ("real", "game"):
                raise ValueError(f"mode d'horloge inconnu : {mode!r} (attendu 'real' ou 'game')")
            if mode == "real":
                self.registry.set_setting(project_id, "clock", {"mode": "real"})
                return
            raw = self.registry.get_setting(project_id, "clock")
            if isinstance(raw, dict) and raw.get("mode") == "game":
                return  # déjà en mode jeu : on conserve l'avancement
            self.registry.set_setting(
                project_id,
                "clock",
                {"mode": "game", "start_ts": self.clock.now(), "weeks_elapsed": 0},
            )

    def advance_week(self, project_id: str, n: int = 1) -> dict[str, UrgencyState]:
        """Avance le temps de jeu de ``n`` semaine(s) puis réévalue tout le réseau.

        Réservé aux projets en mode « jeu » (ValueError sinon).
        """
        with self._lock:
            raw = self.registry.get_setting(project_id, "clock")
            if not (isinstance(raw, dict) and raw.get("mode") == "game"):
                raise ValueError(
                    "Le projet n'est pas en mode « jeu » : "
                    "basculer l'horloge avec set_clock_mode(project_id, 'game') d'abord."
                )
            game = GameClock(
                start_ts=float(raw["start_ts"]),
                weeks_elapsed=int(raw.get("weeks_elapsed", 0)),
            )
            game.advance_weeks(n)
            self.registry.set_setting(
                project_id,
                "clock",
                {"mode": "game", "start_ts": game.start_ts, "weeks_elapsed": game.weeks_elapsed},
            )
            return self.evaluate_all(persist=True)

    # --- pondération FBWM des blocs d'Ur + classement PROMETHEE (E12) ---------------

    def set_poids_criteres(
        self,
        project_id: str,
        poids: dict[str, float],
        methode: str = "fbwm",
        xi_star: float | None = None,
        iso_week_val: str | None = None,
    ) -> None:
        """Persiste les poids des blocs d'Ur du projet (sortie FBWM ou saisie).

        Les poids alimentent le ``omega`` de l'OU probabiliste de
        :class:`UrModel` via :meth:`_ur_model_for` ; les blocs absents du
        dictionnaire conservent leur poids par défaut.

        Args:
            project_id: projet porteur des poids.
            poids: poids par nom de bloc (clés ⊆ :data:`BLOCKS`, valeurs
                >= 0, somme strictement positive).
            methode: provenance des poids (``"fbwm"`` par défaut).
            xi_star: ξ* du solveur FBWM (indicateur de cohérence), ou None.
            iso_week_val: semaine ISO de rattachement ; None → semaine
                courante du projet (selon SON horloge).

        Raises:
            ValueError: bloc inconnu, poids négatif ou somme des poids non
                strictement positive (messages en français).
        """
        with self._lock:
            inconnus = sorted(set(poids) - set(BLOCKS))
            if inconnus:
                raise ValueError(
                    f"Bloc(s) inconnu(s) dans les poids : {inconnus} "
                    f"(blocs valides : {list(BLOCKS)})"
                )
            negatifs = {nom: w for nom, w in poids.items() if w < 0}
            if negatifs:
                raise ValueError(f"Poids négatif(s) interdit(s) : {negatifs}")
            if sum(poids.values()) <= 0:
                raise ValueError("La somme des poids doit être strictement positive.")
            if iso_week_val is None:
                iso_week_val = iso_week(self.clock_for(project_id).now())
            self.registry.set_setting(
                project_id,
                "omega_ur",
                {
                    "poids": {nom: float(w) for nom, w in poids.items()},
                    "methode": methode,
                    "xi_star": xi_star,
                    "iso_week": iso_week_val,
                },
            )
            self._ur_models.pop(project_id, None)  # invalide le cache du projet

    def poids_criteres(self, project_id: str) -> dict[str, float] | None:
        """Poids des blocs d'Ur stockés pour le projet, ou None si absents."""
        raw = self.registry.get_setting(project_id, "omega_ur")
        if not isinstance(raw, dict):
            return None
        poids = raw.get("poids")
        if not isinstance(poids, dict):
            return None
        return {str(nom): float(w) for nom, w in poids.items()}

    def _ur_model_for(self, project_id: str | None) -> UrModel:
        """Modèle Ur effectif du projet : omega FBWM fusionné, sinon le défaut.

        Sans poids stockés, retourne ``self.ur_model`` tel quel ; sinon une
        copie via :func:`dataclasses.replace` avec
        ``omega = {**omega_defaut, **poids_stockés}``. Cache léger par
        projet, invalidé par :meth:`set_poids_criteres`.

        Args:
            project_id: projet concerné ; None → modèle par défaut.

        Returns:
            Le :class:`UrModel` à utiliser pour les nœuds du projet.
        """
        if project_id is None:
            return self.ur_model
        with self._lock:
            cached = self._ur_models.get(project_id)
            if cached is not None:
                return cached
            poids = self.poids_criteres(project_id)
            if poids is None:
                model = self.ur_model
            else:
                model = dataclasses.replace(self.ur_model, omega={**self.ur_model.omega, **poids})
            self._ur_models[project_id] = model
            return model

    def classement_promethee(self, project_id: str) -> ResultatPromethee:
        """Classement PROMETHEE II des nœuds du projet « à traiter en priorité ».

        Alternatives : les nœuds ACTIFS du projet (statut ACTIVE, onboarding
        terminé). Valeurs : les six blocs d'urgence de
        :meth:`UrModel.blocks` au temps du projet — mêmes règles que
        :meth:`refresh_ur_local` (temps et jalons par projet, via
        :meth:`_project_times`) ; blocs calculés en ANALYTIQUE, le mode
        Monte Carlo (E13) ne concerne que l'agrégation d'Ur. Critères : les
        six blocs en sens « max », fonction de préférence par défaut
        (:class:`LineaireIndifference`). Poids : l'omega effectif du projet
        (poids FBWM stockés complétés par les défauts ; uniformes sans poids
        stockés) — les blocs de poids nul sont exclus du classement, comme
        ils le sont de l'OU probabiliste.

        Args:
            project_id: projet à classer.

        Returns:
            Le :class:`ResultatPromethee` (φ, φ⁺, φ⁻, classement complet).

        Raises:
            ValueError: si le projet compte moins de 2 nœuds actifs.
        """
        with self._lock:
            actifs = [
                node
                for node in self.repo.nodes_by_project(project_id)
                if node.status == TaskStatus.ACTIVE and node.onboarding_state != "draft"
            ]
            if len(actifs) < 2:
                raise ValueError(
                    f"Classement PROMETHEE impossible pour le projet {project_id!r} : "
                    f"au moins 2 nœuds actifs sont requis (trouvé : {len(actifs)})."
                )
            t_h, t0 = self._project_times().get(project_id, (0.0, 0.0))
            model = self._ur_model_for(project_id)
            valeurs: dict[str, dict[str, float | None]] = {
                node.id: model.blocks(
                    t_h,
                    node.kpis,
                    milestones=self.registry.list_milestones(node.id),
                    t0_ts=t0,
                )
                for node in actifs
            }
            retenus = [nom for nom in BLOCKS if model.omega.get(nom, 1.0) > 0.0]
            criteres = [Critere(nom=nom, sens="max") for nom in retenus]
            poids = {nom: model.omega.get(nom, 1.0) for nom in retenus}
            return PrometheeII(criteres, poids).classer(valeurs)

    # --- mode Monte Carlo du lead time (E13) -----------------------------------------

    def set_lead_time_mode(
        self,
        project_id: str,
        mode: str,
        n_tirages: int = 10_000,
        graine: int | None = None,
    ) -> None:
        """Choisit le mode de calcul de u_time du projet (analytique ou Monte Carlo).

        CHOIX DOCUMENTÉ : ``n_tirages`` est validé ICI, à l'écriture, contre
        les bornes du simulateur — une configuration invalide ne peut donc
        jamais atteindre :meth:`evaluate_all` (le garde-fou mémoire
        N × n_nœuds, lui, reste évalué à l'exécution car il dépend de la
        taille courante du graphe).

        Repasser en mode analytique purge le dernier résultat MC mémorisé du
        projet (:meth:`last_mc_result` retourne alors None — l'UI n'affiche
        pas d'IC95 périmé).

        Args:
            project_id: projet concerné.
            mode: ``"analytique"`` ou ``"monte_carlo"``.
            n_tirages: nombre de tirages N (mode MC), dans
                [:data:`N_TIRAGES_MIN`, :data:`N_TIRAGES_MAX`].
            graine: graine PCG64 figée, ou None → graine STABLE dérivée de
                (project_id, semaine ISO du projet) à chaque évaluation.

        Raises:
            ValueError: mode inconnu ou ``n_tirages`` hors bornes
                (messages en français).
        """
        with self._lock:
            if mode not in ("analytique", "monte_carlo"):
                raise ValueError(
                    f"Mode de lead time inconnu : {mode!r} (attendu 'analytique' ou 'monte_carlo')"
                )
            if not N_TIRAGES_MIN <= n_tirages <= N_TIRAGES_MAX:
                raise ValueError(
                    f"n_tirages doit être dans [{N_TIRAGES_MIN}, {N_TIRAGES_MAX}], reçu {n_tirages}"
                )
            self.registry.set_setting(
                project_id,
                "lead_time",
                {"mode": mode, "n_tirages": int(n_tirages), "graine": graine},
            )
            if mode == "analytique":
                self._last_mc.pop(project_id, None)

    def lead_time_mode(self, project_id: str) -> dict[str, Any]:
        """Configuration lead time du projet (``{"mode": "analytique"}`` par défaut)."""
        raw = self.registry.get_setting(project_id, "lead_time")
        if isinstance(raw, dict) and raw.get("mode") in ("analytique", "monte_carlo"):
            return dict(raw)
        return {"mode": "analytique"}

    def last_mc_result(self, project_id: str) -> ResultatMC | None:
        """Dernier :class:`ResultatMC` du projet (IC95 pour l'UI), ou None.

        Renseigné à chaque :meth:`evaluate_all` automatique (``t=None``)
        d'un projet en mode « monte_carlo » ; None pour un projet analytique
        (y compris après un retour en mode analytique, qui purge l'entrée).
        """
        return self._last_mc.get(project_id)

    # --- questionnaire AHP -----------------------------------------------------

    def submit_assessment(self, assessment: AHPAssessment) -> int:
        """Enregistre un questionnaire hebdo et met à jour le Ud_local lissé du nœud.

        Garde-fou serveur (faiblesse #9) : une évaluation incohérente au sens
        de Saaty (``consistency_ratio >= CONSISTENCY_THRESHOLD``) est REFUSÉE
        ici même — RIEN n'est persisté. L'UI vérifie déjà le CR, mais un appel
        direct au service ne peut plus contourner ce contrôle.

        Si ``assessment.iso_week`` est vide, la semaine ISO est posée depuis
        l'horloge du projet (``clock_for``) quand ``project_id`` est renseigné,
        sinon depuis l'horloge par défaut du service.

        Raises:
            ValueError: si le ratio de cohérence atteint le seuil de Saaty
                (jugements incohérents, message en français).
        """
        with self._lock:
            if assessment.consistency_ratio >= CONSISTENCY_THRESHOLD:
                raise ValueError(
                    f"Évaluation refusée : CR = {assessment.consistency_ratio:.3f}"
                    f" >= {CONSISTENCY_THRESHOLD:.2f} — jugements incohérents,"
                    " révisez les comparaisons."
                )
            if not assessment.iso_week:
                clock = (
                    self.clock_for(assessment.project_id) if assessment.project_id else self.clock
                )
                assessment.iso_week = iso_week(clock.now())
            db = self.client_db(assessment.node_id)
            rowid = db.save_assessment(assessment)
            node = self.repo.get_node(assessment.node_id)
            if node is not None:
                prev = node.urgency.ud_local
                node.urgency.ud_local = ud_smoothed(prev, assessment.ud, self.rho)
                self.repo.update_node(node)
                self.registry.save_node(node)
            return rowid

    @staticmethod
    def build_assessment(
        node_id: str,
        project_id: str,
        operator_id: str,
        comparisons: dict[tuple[int, int], float],
        criteria_scores: list[float],
        notes: str = "",
    ) -> AHPAssessment:
        """Construit une évaluation complète depuis les réponses brutes du questionnaire."""
        res = run_ahp(comparisons, n=len(criteria_scores))
        ud = compute_ud(res.weights, np.asarray(criteria_scores, dtype=float))
        return AHPAssessment(
            node_id=node_id,
            project_id=project_id,
            operator_id=operator_id,
            comparisons=comparisons,
            criteria_scores=list(criteria_scores),
            weights=res.weights.tolist(),
            consistency_ratio=res.consistency_ratio,
            is_consistent=res.is_consistent,
            ud=ud,
            notes=notes,
        )

    # --- pipeline d'évaluation ---------------------------------------------------

    def _project_times(self) -> dict[str, tuple[float, float]]:
        """Temps courant par projet : ``project_id -> (t_heures, t0_ts epoch)``.

        ``t_heures`` est le temps écoulé depuis l'origine du projet selon SON
        horloge (réelle ou de jeu) — c'est le « t » des formules d'urgence.
        """
        times: dict[str, tuple[float, float]] = {}
        for project in self.registry.list_projects():
            origin = project.origin_ts
            now = self.clock_for(project.id).now()
            times[project.id] = (project_hours(now, origin), origin)
        return times

    def _mc_u_time_overrides(self, times: dict[str, tuple[float, float]]) -> dict[str, float]:
        """u_time simulés par nœud pour les projets en mode « monte_carlo ».

        Pour chaque projet en mode Monte Carlo, exécute UNE SEULE FOIS
        :class:`SimulateurLeadTime` puis ne consomme que les u_time des
        nœuds du projet. COÛT DOCUMENTÉ : le simulateur travaille sur le
        DÉPÔT ENTIER (sa récurrence suit le ``topological_order()`` global,
        il n'accepte pas de sous-ensemble) — chaque projet en mode MC coûte
        donc une passe complète N × n_nœuds(repo), les nœuds des autres
        projets étant simulés puis ignorés.

        La graine est celle stockée dans ``project_settings['lead_time']`` ;
        sinon une graine STABLE est dérivée de (project_id, semaine ISO du
        projet) via ``zlib.crc32`` — deux rafraîchissements de la même
        semaine produisent des résultats identiques bit à bit (le dashboard
        ne « clignote » pas), et la graine change naturellement à la semaine
        suivante. Le dernier :class:`ResultatMC` de chaque projet est
        mémorisé dans ``self._last_mc`` (cf. :meth:`last_mc_result`).

        Args:
            times: temps par projet, au format de :meth:`_project_times`.

        Returns:
            ``{node_id: u_time simulé}`` — les nœuds sans échéance (u_time
            None côté simulateur) sont absents (aucun override).

        Raises:
            ValueError: garde-fou mémoire du simulateur (N × n_nœuds trop
                grand pour le graphe courant).
        """
        overrides: dict[str, float] = {}
        for project in self.registry.list_projects():
            config = self.lead_time_mode(project.id)
            if config.get("mode") != "monte_carlo":
                continue
            nodes = self.repo.nodes_by_project(project.id)
            if not nodes:
                continue
            graine_stockee = config.get("graine")
            if graine_stockee is not None:
                graine = int(graine_stockee)
            else:
                semaine = iso_week(self.clock_for(project.id).now())
                graine = zlib.crc32(f"{project.id}:{semaine}".encode())
            t_h, t0 = times.get(project.id, (0.0, 0.0))
            simulateur = SimulateurLeadTime(
                self.repo, n_tirages=int(config.get("n_tirages", 10_000)), graine=graine
            )
            resultat = simulateur.executer(
                t=t_h,
                milestones_par_noeud={n.id: self.registry.list_milestones(n.id) for n in nodes},
                t0_ts=t0,
            )
            self._last_mc[project.id] = resultat
            for node in nodes:
                u = resultat.u_time.get(node.id)
                if u is not None:
                    overrides[node.id] = u
        return overrides

    def refresh_ur_local(self, t: float | None = None) -> None:
        """Recalcule Ur_local de chaque nœud depuis ses KPIs et jalons.

        Avec ``t=None`` (défaut), le temps de chaque nœud vient de l'horloge
        de SON projet, ses jalons pilotent u_time (mode v2), le modèle Ur
        appliqué est celui de SON projet (:meth:`_ur_model_for`, omega FBWM
        — E12) et les projets en mode « monte_carlo » reçoivent leur u_time
        simulé (:meth:`_mc_u_time_overrides` — E13). Avec un ``t`` explicite,
        comportement v1 : pas de jalons, temps forcé identique partout,
        ``self.ur_model`` pour tous et JAMAIS de Monte Carlo
        (rétro-compatibilité tests/outillage).

        Le statut dérivé des jalons est appliqué AVANT le calcul (un nœud
        dont tous les jalons sont terminés passe DONE) ; les règles de statut
        (DONE → 0, ABANDONED → 1) restent dans ``core.status_rules`` et
        priment sur l'override Monte Carlo.
        """
        times = self._project_times() if t is None else None
        mc_overrides = self._mc_u_time_overrides(times) if times is not None else {}
        for node in self.repo.nodes():
            if node.onboarding_state == "draft":
                # Nœud en cours d'onboarding : contribution neutre au pipeline
                # tant que le wizard n'est pas terminé.
                node.urgency.ur_local = 0.0
                self.repo.update_node(node)
                continue
            milestones = None
            t_h, t0 = (t if t is not None else 0.0), 0.0
            model = self.ur_model
            if times is not None:
                milestones = self.registry.list_milestones(node.id)
                derived = derive_node_status(milestones)
                if derived is not None and derived != node.status:
                    node.status = derived
                    self.registry.set_node_status(node.id, derived)
                if node.project_id and node.project_id in times:
                    t_h, t0 = times[node.project_id]
                model = self._ur_model_for(node.project_id)
            node.urgency.ur_local = model.ur_local(
                t_h,
                node.kpis,
                status=node.status,
                milestones=milestones,
                t0_ts=t0,
                u_time_override=mc_overrides.get(node.id),
            )
            self.repo.update_node(node)

    def evaluate_all(
        self, t: float | None = None, persist: bool = False
    ) -> dict[str, UrgencyState]:
        """Pipeline complet : Ur_local -> propagation -> adéquation (-> persistance).

        Avec ``persist=True``, chaque état est journalisé dans la base du
        client ET l'état courant est figé dans le registre (table
        ``node_urgency``) pour survivre à un redémarrage.

        Horodatage (correctif E11) : en mode automatique (``t=None``), les
        états sont horodatés par l'horloge de LEUR projet — en mode « jeu »
        l'historique tombe ainsi dans la bonne semaine SIMULÉE, pas dans la
        semaine réelle du poste (le moteur de propagation, lui, horodate à
        l'heure murale).

        Modes E12/E13 : en mode automatique, chaque nœud est évalué avec le
        UrModel de SON projet (omega FBWM) et, pour les projets en mode
        « monte_carlo », avec le u_time simulé ; avec un ``t`` explicite,
        comportement v1 strict (``self.ur_model``, jamais de Monte Carlo) —
        cf. :meth:`refresh_ur_local`.
        """
        with self._lock:
            self.refresh_ur_local(t=t)
            project_now: dict[str, float] = {}
            if t is None:
                for project in self.registry.list_projects():
                    project_now[project.id] = self.clock_for(project.id).now()
            states = self.propagation.propagate_all()
            for node_id, state in states.items():
                ud = state.ud if state.ud is not None else 0.0
                ur = state.ur if state.ur is not None else 0.0
                evaluated = self.adequation.evaluate(ud, ur)
                state.adequation = evaluated.adequation
                state.false_urgency = evaluated.false_urgency
                state.hidden_risk = evaluated.hidden_risk
                node = self.repo.get_node(node_id)
                if node is not None:
                    if node.project_id in project_now:
                        state.timestamp = project_now[node.project_id]
                    node.urgency = state
                    self.repo.update_node(node)
                if persist:
                    self.registry.save_urgency(node_id, state)
                    self.client_db(node_id).save_urgency_state(node_id, state)
            return states

    def simulate_shock(self, node_id: str, new_ur_local: float) -> dict[str, float]:
        """Scénario catastrophe what-if : retourne les ΔUr propagés sans rien persister.

        CHOIX DOCUMENTÉ (E13) : le what-if reste ANALYTIQUE même pour un
        projet en mode « monte_carlo » — il doit répondre instantanément
        dans l'UI, là où une passe MC coûte N × n_nœuds tirages.
        """
        return self.propagation.simulate_shock(node_id, new_ur_local)

    # --- données de démonstration ---------------------------------------------------

    def seed_demo(self, n_ranks: int = 3, seed: int = 42) -> Project:
        """Génère un projet de test aléatoire complet (questionnaires inclus).

        Enrichissements v2 : origine temporelle = maintenant (les jalons
        deviennent de vraies échéances), 2-4 jalons par nœud, tags et
        taxonomie, ~1 arc de secours sur 10. Données de TEST uniquement —
        jamais en production.
        """
        with self._lock:
            gen = RandomSupplyChainGenerator(seed=seed)
            project, nodes, arcs = gen.generate(n_ranks=n_ranks)
            project.t0_ts = self.clock.now()

            categories, tags = gen.generate_tags(project.id)
            tag_ids = [tag.id for tag in tags]
            for node in nodes:
                node.tags = gen.pick_node_tags(tag_ids)
            backups = gen.generate_backup_arcs(nodes, arcs)

            self.registry.save_project(project)
            for category in categories:
                self.registry.save_tag_category(category)
            for tag in tags:
                self.registry.save_tag(tag)
            self.create_project(project, nodes, arcs + backups)
            for node in nodes:
                for milestone in gen.generate_milestones(node.id, project.t0_ts):
                    self.registry.save_milestone(milestone)
                assessment = gen.generate_assessment(node.id, project.id)
                self.submit_assessment(assessment)
            self.evaluate_all(persist=True)
            return project
