"""Journal des interventions — actions correctives tracées (contrat n°9, HÉLIOS v7).

:class:`InterventionJournal` consigne le cycle de vie complet d'une
intervention décidée sur un nœud : ouverture (état AVANT observable, action,
acteur, objectif opérationnel déclaré), exécution effective (date d'effet),
PROPOSITION — jamais imposition — d'un résultat opérationnel calculé sur la
fenêtre ``[date_effet, date_effet + 4 semaines[``, et clôture humaine.
Le rail suivi ici est :class:`~supplyscore.services.decisions.DecisionService`
(snapshot automatique depuis ``node.urgency``, horloge du PROJET du nœud via
``clock_for``, écriture dans la base CLIENT du nœud, opérateur souverain).

Définitions FIGÉES (voir ``docs/modele_mathematique.md``, §13) :

- **Rupture (« issue défavorable »)** : UNE SEULE définition dans tout le
  système, celle de :mod:`~supplyscore.services.calibration` (jalon raté, OU
  nœud abandonné, OU événement critique/défaut non annulé) — réutilisée ici
  via :func:`~supplyscore.services.calibration.issues_defavorables`, jamais
  redupliquée.
- **Résultat opérationnel** (label CAUSAL, model-free), sur la fenêtre
  ``[date_effet, date_effet + 4 semaines[`` :

  - ``'resolu'`` : aucune issue défavorable ET l'objectif opérationnel
    déclaré à l'ouverture est atteint — proxy model-free (:meth:`
    InterventionJournal.proposer_resultat` ne regarde jamais Ud/Ur/H, voir
    plus bas) : au moins un jalon du nœud, dont l'échéance tombe DANS la
    fenêtre, a été livré (DONE) ;
  - ``'partiel'`` : amélioration du KPI cible sans atteinte — dans ce module,
    aucune issue défavorable mais aucun jalon livré dans la fenêtre (y
    compris quand aucun jalon n'y échoit : l'atteinte n'est alors pas
    vérifiable automatiquement, l'opérateur tranche via :meth:`clore`) ;
  - ``'echec'`` : issue défavorable constatée dans la fenêtre, OU
    l'intervention a été explicitement marquée non exécutée ;
  - ``'en_cours'`` : pas encore de date d'effet posée, ou fenêtre
    d'observation pas encore écoulée sans issue constatée (censure à droite,
    même logique que :mod:`~supplyscore.services.calibration`).

  :meth:`proposer_resultat` ne fait QUE proposer (aucune écriture) : « en
  revue comme ailleurs dans SupplyScore, l'opérateur reste l'autorité finale »
  — c'est :meth:`clore` qui écrit le résultat que l'humain retient.
- **État de risque** (sortie d'alerte, ΔP, ΔUr) : information D'INTERFACE
  SEULEMENT, portée par des colonnes SÉPARÉES (``etat_risque_avant``/
  ``etat_risque_apres``, capturées AUTOMATIQUEMENT depuis ``node.urgency`` à
  l'ouverture et à la clôture) — jamais lue par :meth:`proposer_resultat`,
  jamais un label d'apprentissage.

``etat_avant``/``etat_apres`` (colonnes ``etat_*_json``, DISTINCTES des
colonnes ``etat_risque_*``) portent l'état OBSERVABLE contractuel du contrat
n°9 : ``ur_local``, ``ud_local``, ``hidden_risk``, ``false_urgency``, et
``p_issue`` si l'appelant le fournit (``p_issue`` n'existe pas sur
:class:`~supplyscore.domain.models.UrgencyState` — probabilité d'issue d'un
modèle de prescription externe, jamais calculée par ce module).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from supplyscore.core.clock import WEEK_SECONDS
from supplyscore.domain.milestones import MilestoneStatus
from supplyscore.services.calibration import issues_defavorables

if TYPE_CHECKING:
    from supplyscore.core.clock import Clock
    from supplyscore.domain.models import SupplyNode, UrgencyState
    from supplyscore.services.orchestrator import SupplyScoreService

#: Longueur de la fenêtre d'observation du résultat opérationnel, en semaines.
_FENETRE_SEMAINES: int = 4

#: Valeurs autorisées de la colonne ``resultat`` (contrat n°9).
_RESULTATS_VALIDES: frozenset[str] = frozenset({"resolu", "partiel", "echec", "en_cours"})


@dataclass(frozen=True)
class Intervention:
    """Intervention consignée dans le journal (contrat n°9).

    Attributes:
        id: identifiant unique (UUID4).
        node_id: nœud sur lequel l'intervention agit.
        date_ts: date d'ouverture de la ligne (= ``decidee_ts``), ancre
            chronologique de l'index ``idx_interventions_node_date``.
        etat_avant: état OBSERVABLE déclaré à l'ouverture (``ur_local``,
            ``ud_local``, ``hidden_risk``, ``false_urgency``, et ``p_issue``
            si fourni) — jamais l'état de risque d'interface.
        action_id: identifiant de l'action de prescription appliquée.
        acteur: personne ou rôle ayant décidé/exécuté l'intervention.
        objectif_operationnel: objectif déclaré à l'ouverture (texte libre).
        decidee_ts: instant de la décision, en secondes epoch.
        executee: None (pas encore statué), True (exécutée) ou False (ne
            sera pas exécutée).
        executee_ts: instant où :meth:`InterventionJournal.marquer_executee`
            a été appelée, ou None.
        date_effet_ts: instant à partir duquel l'action produit son effet —
            ancre la fenêtre d'observation du résultat opérationnel.
        resultat: ``'resolu'`` | ``'partiel'`` | ``'echec'`` | ``'en_cours'``.
        etat_apres: état OBSERVABLE déclaré à la clôture, ou None tant que
            l'intervention n'est pas close.
        etat_risque_avant: état de risque D'INTERFACE à l'ouverture (snapshot
            complet de ``node.urgency``), jamais lu pour le résultat.
        etat_risque_apres: état de risque D'INTERFACE à la clôture, ou None.
        succes: dérivé de ``resultat`` à la clôture (resolu -> True,
            echec -> False, partiel/en_cours -> None).
        effets_voisins: effets observés sur des nœuds voisins (texte libre).
        notes: commentaire libre.
    """

    id: str
    node_id: str
    date_ts: float
    etat_avant: dict[str, Any]
    action_id: str
    acteur: str
    objectif_operationnel: str
    decidee_ts: float
    executee: bool | None
    executee_ts: float | None
    date_effet_ts: float | None
    resultat: str
    etat_apres: dict[str, Any] | None
    etat_risque_avant: dict[str, Any]
    etat_risque_apres: dict[str, Any] | None
    succes: bool | None
    effets_voisins: list[str]
    notes: str


def _row_from_intervention(iv: Intervention) -> dict[str, Any]:
    """Sérialise une :class:`Intervention` en ligne prête pour ``insert_intervention``."""
    return {
        "id": iv.id,
        "node_id": iv.node_id,
        "date_ts": iv.date_ts,
        "etat_avant_json": json.dumps(iv.etat_avant, sort_keys=True),
        "action_id": iv.action_id,
        "acteur": iv.acteur,
        "objectif_operationnel": iv.objectif_operationnel,
        "decidee_ts": iv.decidee_ts,
        "executee": None if iv.executee is None else int(iv.executee),
        "executee_ts": iv.executee_ts,
        "date_effet_ts": iv.date_effet_ts,
        "resultat": iv.resultat,
        "etat_apres_json": None
        if iv.etat_apres is None
        else json.dumps(iv.etat_apres, sort_keys=True),
        "etat_risque_avant_json": json.dumps(iv.etat_risque_avant, sort_keys=True),
        "etat_risque_apres_json": (
            None
            if iv.etat_risque_apres is None
            else json.dumps(iv.etat_risque_apres, sort_keys=True)
        ),
        "succes": None if iv.succes is None else int(iv.succes),
        "effets_voisins_json": json.dumps(iv.effets_voisins),
        "notes": iv.notes,
    }


def _intervention_from_row(row: Mapping[str, Any]) -> Intervention:
    """Reconstruit une :class:`Intervention` depuis une ligne de la table ``interventions``."""
    return Intervention(
        id=row["id"],
        node_id=row["node_id"],
        date_ts=row["date_ts"],
        etat_avant=json.loads(row["etat_avant_json"]),
        action_id=row["action_id"],
        acteur=row["acteur"],
        objectif_operationnel=row["objectif_operationnel"],
        decidee_ts=row["decidee_ts"],
        executee=None if row["executee"] is None else bool(row["executee"]),
        executee_ts=row["executee_ts"],
        date_effet_ts=row["date_effet_ts"],
        resultat=row["resultat"],
        etat_apres=(None if row["etat_apres_json"] is None else json.loads(row["etat_apres_json"])),
        etat_risque_avant=json.loads(row["etat_risque_avant_json"]),
        etat_risque_apres=(
            None
            if row["etat_risque_apres_json"] is None
            else json.loads(row["etat_risque_apres_json"])
        ),
        succes=None if row["succes"] is None else bool(row["succes"]),
        effets_voisins=list(json.loads(row["effets_voisins_json"])),
        notes=row["notes"],
    )


class InterventionJournal:
    """Journal des interventions : ouverture, exécution, proposition, clôture.

    S'appuie sur la façade :class:`SupplyScoreService` : le registre fournit
    les nœuds (état d'urgence courant, jalons), ``clock_for`` l'horloge
    effective du projet, et la base CLIENT du nœud porte la table
    ``interventions``.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le journal des interventions au-dessus de la façade.

        Args:
            service: façade applicative (registre, bases client, horloges).
        """
        self._service = service

    # -- aides internes (mêmes que DecisionService) --

    def _node(self, node_id: str) -> SupplyNode:
        """Lecture fraîche du nœud depuis le registre.

        Args:
            node_id: identifiant du nœud.

        Returns:
            Le :class:`~supplyscore.domain.models.SupplyNode` du registre.

        Raises:
            ValueError: si le nœud est inconnu du registre.
        """
        node = self._service.registry.get_node(node_id)
        if node is None:
            raise ValueError(f"nœud inconnu du registre : {node_id!r}")
        return node

    def _clock_of(self, node: SupplyNode) -> Clock:
        """Horloge effective du nœud : celle de SON projet (réelle ou de jeu)."""
        if node.project_id:
            return self._service.clock_for(node.project_id)
        return self._service.clock

    def _row(self, intervention_id: str, node_id: str) -> dict[str, Any]:
        """Ligne brute de l'intervention (pas de getter dédié : filtrage en Python).

        Args:
            intervention_id: id de l'intervention recherchée.
            node_id: nœud porteur (chaque nœud a sa propre base CLIENT).

        Returns:
            La ligne brute (dict, clés = colonnes SQL) correspondante.

        Raises:
            ValueError: aucune intervention de cet id sur ce nœud.
        """
        for row in self._service.client_db(node_id).list_interventions(node_id):
            if row["id"] == intervention_id:
                return row
        raise ValueError(f"intervention inconnue : {intervention_id!r} (nœud {node_id!r})")

    @staticmethod
    def _etat_observable(urgence: UrgencyState) -> dict[str, float | None]:
        """Sous-ensemble OBSERVABLE contractuel de l'urgence courante (contrat n°9)."""
        return {
            "ur_local": urgence.ur_local,
            "ud_local": urgence.ud_local,
            "hidden_risk": urgence.hidden_risk,
            "false_urgency": urgence.false_urgency,
        }

    @staticmethod
    def _etat_risque(urgence: UrgencyState) -> dict[str, float | None]:
        """Snapshot COMPLET de l'urgence courante — information d'INTERFACE seulement."""
        return {
            "ud_local": urgence.ud_local,
            "ur_local": urgence.ur_local,
            "ud": urgence.ud,
            "ur": urgence.ur,
            "adequation": urgence.adequation,
            "false_urgency": urgence.false_urgency,
            "hidden_risk": urgence.hidden_risk,
        }

    # -- écriture : ouverture --

    def record(
        self,
        node_id: str,
        action_id: str,
        acteur: str,
        objectif_operationnel: str,
        etat_avant: dict[str, Any] | None = None,
        notes: str = "",
    ) -> Intervention:
        """Ouvre une intervention : capture l'état AVANT et journalise son objectif.

        ``etat_avant``, non fourni, est capturé AUTOMATIQUEMENT depuis
        ``node.urgency`` (lecture fraîche du registre, observables
        contractuels seulement — ``p_issue`` n'y figure jamais
        automatiquement, un appelant qui dispose d'une probabilité d'issue
        externe peut la fournir en écrasant ``etat_avant``).
        ``etat_risque_avant`` (interface) est TOUJOURS capturé automatiquement,
        pleinement, et n'est jamais surchargeable.

        Args:
            node_id: identifiant du nœud concerné.
            action_id: identifiant de l'action de prescription appliquée.
            acteur: personne ou rôle décidant l'intervention (non vide).
            objectif_operationnel: objectif déclaré à l'ouverture (non vide).
            etat_avant: état observable à l'ouverture ; None -> capturé
                automatiquement depuis ``node.urgency``.
            notes: commentaire libre initial.

        Returns:
            L':class:`Intervention` telle que persistée (``resultat`` vaut
            ``'en_cours'``).

        Raises:
            ValueError: ``acteur``/``objectif_operationnel`` vide (ou blanc),
                ou nœud inconnu du registre — rien n'est alors écrit.
        """
        if not acteur.strip():
            raise ValueError("L'acteur de l'intervention ne peut pas être vide.")
        if not objectif_operationnel.strip():
            raise ValueError("L'objectif opérationnel ne peut pas être vide.")
        node = self._node(node_id)
        now = self._clock_of(node).now()
        urgence = node.urgency
        intervention = Intervention(
            id=str(uuid.uuid4()),
            node_id=node_id,
            date_ts=now,
            etat_avant=dict(etat_avant)
            if etat_avant is not None
            else self._etat_observable(urgence),
            action_id=action_id,
            acteur=acteur,
            objectif_operationnel=objectif_operationnel,
            decidee_ts=now,
            executee=None,
            executee_ts=None,
            date_effet_ts=None,
            resultat="en_cours",
            etat_apres=None,
            etat_risque_avant=self._etat_risque(urgence),
            etat_risque_apres=None,
            succes=None,
            effets_voisins=[],
            notes=notes,
        )
        self._service.client_db(node_id).insert_intervention(_row_from_intervention(intervention))
        return intervention

    # -- écriture : exécution --

    def marquer_executee(
        self,
        intervention_id: str,
        node_id: str,
        executee: bool,
        date_effet_ts: float | None,
    ) -> None:
        """Marque l'intervention comme exécutée (ou non) et pose sa date d'effet.

        ``date_effet_ts`` ancre la fenêtre d'observation
        ``[date_effet, date_effet + 4 semaines[`` de :meth:`proposer_resultat` ;
        sans elle, le résultat opérationnel reste ``'en_cours'`` indéfiniment.

        Args:
            intervention_id: id de l'intervention à mettre à jour.
            node_id: nœud porteur de l'intervention.
            executee: True si l'action a été effectivement exécutée.
            date_effet_ts: instant (epoch s) à partir duquel l'action produit
                son effet, ou None si non encore connu.

        Raises:
            ValueError: intervention inconnue sur ce nœud, ou nœud inconnu
                du registre.
        """
        node = self._node(node_id)
        now = self._clock_of(node).now()
        self._row(intervention_id, node_id)  # existence -> ValueError sinon
        self._service.client_db(node_id).update_intervention(
            intervention_id,
            {
                "executee": int(executee),
                "executee_ts": now,
                "date_effet_ts": date_effet_ts,
            },
        )

    # -- lecture : proposition (jamais d'écriture) --

    def proposer_resultat(self, intervention_id: str, node_id: str) -> tuple[str, list[str]]:
        """Propose un résultat opérationnel — NE modifie jamais la base.

        Applique la définition FIGÉE du module sur la fenêtre
        ``[date_effet, date_effet + 4 semaines[`` : issue défavorable
        (:func:`~supplyscore.services.calibration.issues_defavorables`, sur
        les jalons et événements du nœud) d'abord, puis atteinte de
        l'objectif (proxy model-free : jalon livré DANS la fenêtre) une fois
        la fenêtre entièrement écoulée. Ne lit JAMAIS Ud/Ur/H — seulement des
        faits (jalons, événements, statut du nœud) — conformément à la
        séparation stricte entre résultat causal et état de risque
        d'interface (voir le docstring du module).

        Args:
            intervention_id: id de l'intervention à évaluer.
            node_id: nœud porteur de l'intervention.

        Returns:
            ``(resultat_propose, causes)`` — ``causes`` explicite la
            proposition en français (``[]`` pour ``'en_cours'`` sans motif
            particulier). RIEN n'est écrit : c'est :meth:`clore` qui
            persiste le résultat retenu par l'opérateur.

        Raises:
            ValueError: intervention inconnue sur ce nœud, ou nœud inconnu
                du registre.
        """
        row = self._row(intervention_id, node_id)
        if row["executee"] == 0:
            return "echec", ["intervention marquée non exécutée : objectif non poursuivi"]

        date_effet_ts = row["date_effet_ts"]
        if date_effet_ts is None:
            return "en_cours", [
                "aucune date d'effet posée : la fenêtre d'observation n'a pas commencé"
            ]

        node = self._node(node_id)
        now_ts = self._clock_of(node).now()
        fin_ts = date_effet_ts + _FENETRE_SEMAINES * WEEK_SECONDS
        milestones = self._service.registry.list_milestones(node_id)
        evenements = self._service.client_db(node_id).list_events(node_id)

        causes = issues_defavorables(
            node=node,
            debut_ts=date_effet_ts,
            fin_ts=fin_ts,
            milestones=milestones,
            now_ts=now_ts,
            evenements=evenements,
        )
        if causes:
            return "echec", causes

        if now_ts < fin_ts:
            return "en_cours", []

        # Fenêtre entièrement écoulée, aucune issue défavorable : l'atteinte
        # de l'objectif s'évalue sur les jalons échéant DANS la fenêtre (proxy
        # KPI cible model-free — jamais Ud/Ur/H). Tout jalon ACTIVE encore en
        # jeu dans la fenêtre aurait déjà été signalé ci-dessus par
        # ``issues_defavorables`` une fois la fenêtre close : seuls des jalons
        # DONE peuvent donc subsister ici.
        jalons_fenetre = [m for m in milestones if date_effet_ts <= m.deadline_ts < fin_ts]
        jalons_livres = [m for m in jalons_fenetre if m.status is MilestoneStatus.DONE]
        if jalons_livres:
            return "resolu", [
                f"objectif atteint : jalon « {m.name} » livré dans la fenêtre"
                for m in jalons_livres
            ]
        return "partiel", [
            "aucun jalon livré dans la fenêtre : atteinte de l'objectif non vérifiable"
            " automatiquement, confirmation de l'opérateur requise via clore()"
        ]

    # -- écriture : clôture (humaine) --

    def clore(
        self,
        intervention_id: str,
        node_id: str,
        resultat: str,
        etat_apres: dict[str, Any] | None = None,
        effets_voisins: list[str] | None = None,
        notes: str = "",
    ) -> None:
        """Clôture l'intervention avec le résultat RETENU par l'opérateur.

        ``etat_apres``, non fourni, est capturé AUTOMATIQUEMENT depuis
        ``node.urgency`` (même règle que :meth:`record`). ``etat_risque_apres``
        (interface) est TOUJOURS capturé automatiquement. ``succes`` est
        DÉRIVÉ de ``resultat`` : ``'resolu'`` -> True, ``'echec'`` -> False,
        ``'partiel'``/``'en_cours'`` -> None.

        Args:
            intervention_id: id de l'intervention à clôturer.
            node_id: nœud porteur de l'intervention.
            resultat: ``'resolu'`` | ``'partiel'`` | ``'echec'`` | ``'en_cours'``
                — c'est L'OPÉRATEUR qui choisit, éventuellement après avoir
                consulté :meth:`proposer_resultat`.
            etat_apres: état observable à la clôture ; None -> capturé
                automatiquement depuis ``node.urgency``.
            effets_voisins: effets observés sur des nœuds voisins.
            notes: commentaire libre (remplace les notes existantes).

        Raises:
            ValueError: ``resultat`` hors des 4 valeurs autorisées, ou
                intervention/nœud inconnu — rien n'est alors écrit.
        """
        if resultat not in _RESULTATS_VALIDES:
            raise ValueError(
                f"resultat invalide : {resultat!r} (attendu un de {sorted(_RESULTATS_VALIDES)})"
            )
        self._row(intervention_id, node_id)  # existence -> ValueError sinon
        node = self._node(node_id)
        urgence = node.urgency
        if resultat == "resolu":
            succes: int | None = 1
        elif resultat == "echec":
            succes = 0
        else:
            succes = None
        self._service.client_db(node_id).update_intervention(
            intervention_id,
            {
                "resultat": resultat,
                "etat_apres_json": json.dumps(
                    dict(etat_apres) if etat_apres is not None else self._etat_observable(urgence),
                    sort_keys=True,
                ),
                "etat_risque_apres_json": json.dumps(self._etat_risque(urgence), sort_keys=True),
                "succes": succes,
                "effets_voisins_json": json.dumps(list(effets_voisins) if effets_voisins else []),
                "notes": notes,
            },
        )

    # -- lecture --

    def list_for_node(self, node_id: str, only_open: bool = False) -> list[Intervention]:
        """Interventions du nœud, les plus anciennes d'abord.

        Args:
            node_id: identifiant du nœud.
            only_open: si True, ne retourne que les interventions dont le
                résultat opérationnel est encore ``'en_cours'``.

        Returns:
            Les :class:`Intervention` du nœud, triées par ``date_ts`` croissant.
        """
        rows = self._service.client_db(node_id).list_interventions(node_id, only_open=only_open)
        return [_intervention_from_row(row) for row in rows]

    def stats_par_action(self, project_id: str) -> dict[str, dict[str, int]]:
        """Statistiques d'interventions par action, agrégées sur le projet entier.

        Balaie le journal de CHAQUE nœud du projet (chaque nœud a sa propre
        base CLIENT) — c'est l'entrée temps réel du modèle d'effet des
        actions de prescription (nombre d'essais, taux d'exécution, taux de
        succès observés par action).

        Args:
            project_id: identifiant du projet.

        Returns:
            Un dict ``action_id -> {"n", "n_executees", "n_succes",
            "n_echecs"}`` (compteurs entiers ; ``n`` compte TOUTES les
            interventions de l'action, exécutées ou non).
        """
        stats: dict[str, dict[str, int]] = {}
        for node in self._service.registry.list_nodes(project_id):
            for row in self._service.client_db(node.id).list_interventions(node.id):
                bucket = stats.setdefault(
                    row["action_id"], {"n": 0, "n_executees": 0, "n_succes": 0, "n_echecs": 0}
                )
                bucket["n"] += 1
                if row["executee"] == 1:
                    bucket["n_executees"] += 1
                if row["succes"] == 1:
                    bucket["n_succes"] += 1
                elif row["succes"] == 0:
                    bucket["n_echecs"] += 1
        return stats

    # -- bootstrap / tests --

    def import_synthetic(
        self, path_jsonl: str | Path, node_mapping: dict[str, str] | None = None
    ) -> int:
        """Rejoue un fichier JSONL synthétique (« interventions_truth ») dans le journal.

        Format toléré (une intervention par ligne JSON) : ``tour`` (numéro de
        semaine synthétique — ancré arbitrairement sur l'epoch Unix, 0 = la
        semaine du 1er janvier 1970 ; ``date_ts = tour × 604 800`` s, un
        ancrage arbitraire mais déterministe, suffisant pour un rejeu de
        test/bootstrap), ``node`` (id de nœud, réécrit par ``node_mapping``
        si fourni), ``action_id``, ``etat_avant`` (dict, stocké tel quel),
        ``decidee`` (bool ; si explicitement ``False``, la ligne est une
        candidate NON retenue par le générateur et n'est PAS importée),
        ``executee`` (bool), ``date_effet`` (numéro de semaine synthétique,
        comme ``tour``), ``resultat_operationnel`` (une des 4 valeurs
        figées ; retombe sur ``'en_cours'`` si absente ou invalide),
        ``effets_voisins`` (liste). Clés inconnues tolérées et ignorées.

        Args:
            path_jsonl: chemin du fichier JSONL à rejouer.
            node_mapping: réécriture optionnelle ``id du fichier -> id réel``
                (rejoue un fichier générique sur des ids de nœuds différents).

        Returns:
            Le nombre de lignes effectivement importées (les candidates
            ``decidee: false`` ne sont pas comptées).

        Raises:
            ValueError: une ligne non vide n'est pas un objet JSON valide,
                ou il lui manque ``node``/``action_id``.
        """
        chemin = Path(path_jsonl)
        importees = 0
        with chemin.open(encoding="utf-8") as fichier:
            for numero_ligne, ligne_brute in enumerate(fichier, start=1):
                ligne_brute = ligne_brute.strip()
                if not ligne_brute:
                    continue
                try:
                    ligne: dict[str, Any] = json.loads(ligne_brute)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"{chemin} ligne {numero_ligne} : JSON invalide ({exc})"
                    ) from exc
                if ligne.get("decidee") is False:
                    continue  # candidate non retenue par le générateur : pas une vraie intervention
                node_id = ligne.get("node")
                action_id = ligne.get("action_id")
                if not node_id or not action_id:
                    raise ValueError(
                        f"{chemin} ligne {numero_ligne} : 'node' et 'action_id' requis"
                    )
                if node_mapping is not None:
                    node_id = node_mapping.get(node_id, node_id)

                tour = float(ligne.get("tour", 0) or 0)
                date_ts = tour * WEEK_SECONDS
                date_effet_brut = ligne.get("date_effet")
                date_effet_ts = (
                    None if date_effet_brut is None else float(date_effet_brut) * WEEK_SECONDS
                )
                executee_brut = ligne.get("executee")
                resultat = ligne.get("resultat_operationnel", "en_cours")
                if resultat not in _RESULTATS_VALIDES:
                    resultat = "en_cours"
                if resultat == "resolu":
                    succes: bool | None = True
                elif resultat == "echec":
                    succes = False
                else:
                    succes = None

                intervention = Intervention(
                    id=str(uuid.uuid4()),
                    node_id=node_id,
                    date_ts=date_ts,
                    etat_avant=dict(ligne.get("etat_avant") or {}),
                    action_id=action_id,
                    acteur="import_synthetic",
                    objectif_operationnel=ligne.get("objectif_operationnel", ""),
                    decidee_ts=date_ts,
                    executee=None if executee_brut is None else bool(executee_brut),
                    executee_ts=date_ts if executee_brut else None,
                    date_effet_ts=date_effet_ts,
                    resultat=resultat,
                    etat_apres=None,
                    etat_risque_avant={},
                    etat_risque_apres=None,
                    succes=succes,
                    effets_voisins=[str(e) for e in (ligne.get("effets_voisins") or [])],
                    notes=f"importé depuis {chemin.name}",
                )
                self._service.client_db(node_id).insert_intervention(
                    _row_from_intervention(intervention)
                )
                importees += 1
        return importees
