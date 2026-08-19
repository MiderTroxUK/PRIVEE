"""Journal des interventions - actions correctives tracees (contrat no9, HELIOS v7).

:class:`InterventionJournal` consigne le cycle de vie complet d'une
intervention decidee sur un noeud : ouverture (etat AVANT observable, action,
acteur, objectif operationnel declare), execution effective (date d'effet),
PROPOSITION - jamais imposition - d'un resultat operationnel calcule sur la
fenetre ``[date_effet, date_effet + 4 semaines[``, et cloture humaine.
Le rail suivi ici est :class:`~supplyscore.services.decisions.DecisionService`
(snapshot automatique depuis ``node.urgency``, horloge du PROJET du noeud via
``clock_for``, ecriture dans la base CLIENT du noeud, operateur souverain).

Definitions FIGEES (voir ``docs/modele_mathematique.md``, section 13) :

- **Rupture (" issue defavorable ")** : UNE SEULE definition dans tout le
  systeme, celle de :mod:`~supplyscore.services.calibration` (jalon rate, OU
  noeud abandonne, OU evenement critique/defaut non annule) - reutilisee ici
  via :func:`~supplyscore.services.calibration.issues_defavorables`, jamais
  redupliquee.
- **Resultat operationnel** (label CAUSAL, model-free), sur la fenetre
  ``[date_effet, date_effet + 4 semaines[`` :

  - ``'resolu'`` : aucune issue defavorable ET l'objectif operationnel
    declare a l'ouverture est atteint - proxy model-free (:meth:`
    InterventionJournal.proposer_resultat` ne regarde jamais Ud/Ur/H, voir
    plus bas) : au moins un jalon du noeud, dont l'echeance tombe DANS la
    fenetre, a ete livre (DONE) ;
  - ``'partiel'`` : amelioration du KPI cible sans atteinte - dans ce module,
    aucune issue defavorable mais aucun jalon livre dans la fenetre (y
    compris quand aucun jalon n'y echoit : l'atteinte n'est alors pas
    verifiable automatiquement, l'operateur tranche via :meth:`clore`) ;
  - ``'echec'`` : issue defavorable constatee dans la fenetre, OU
    l'intervention a ete explicitement marquee non executee ;
  - ``'en_cours'`` : pas encore de date d'effet posee, ou fenetre
    d'observation pas encore ecoulee sans issue constatee (censure a droite,
    meme logique que :mod:`~supplyscore.services.calibration`).

  :meth:`proposer_resultat` ne fait QUE proposer (aucune ecriture) : " en
  revue comme ailleurs dans SupplyScore, l'operateur reste l'autorite finale "
  - c'est :meth:`clore` qui ecrit le resultat que l'humain retient.
- **Etat de risque** (sortie d'alerte, DeltaP, DeltaUr) : information D'INTERFACE
  SEULEMENT, portee par des colonnes SEPAREES (``etat_risque_avant``/
  ``etat_risque_apres``, capturees AUTOMATIQUEMENT depuis ``node.urgency`` a
  l'ouverture et a la cloture) - jamais lue par :meth:`proposer_resultat`,
  jamais un label d'apprentissage.

``etat_avant``/``etat_apres`` (colonnes ``etat_*_json``, DISTINCTES des
colonnes ``etat_risque_*``) portent l'etat OBSERVABLE contractuel du contrat
no9 : ``ur_local``, ``ud_local``, ``hidden_risk``, ``false_urgency``, et
``p_issue`` si l'appelant le fournit (``p_issue`` n'existe pas sur
:class:`~supplyscore.domain.models.UrgencyState` - probabilite d'issue d'un
modele de prescription externe, jamais calculee par ce module).
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

#: Longueur de la fenetre d'observation du resultat operationnel, en semaines.
_FENETRE_SEMAINES: int = 4

#: Valeurs autorisees de la colonne ``resultat`` (contrat no9).
_RESULTATS_VALIDES: frozenset[str] = frozenset({"resolu", "partiel", "echec", "en_cours"})


@dataclass(frozen=True)
class Intervention:
    """Intervention consignee dans le journal (contrat no9).

    Attributes:
        id: identifiant unique (UUID4).
        node_id: noeud sur lequel l'intervention agit.
        date_ts: date d'ouverture de la ligne (= ``decidee_ts``), ancre
            chronologique de l'index ``idx_interventions_node_date``.
        etat_avant: etat OBSERVABLE declare a l'ouverture (``ur_local``,
            ``ud_local``, ``hidden_risk``, ``false_urgency``, et ``p_issue``
            si fourni) - jamais l'etat de risque d'interface.
        action_id: identifiant de l'action de prescription appliquee.
        acteur: personne ou role ayant decide/execute l'intervention.
        objectif_operationnel: objectif declare a l'ouverture (texte libre).
        decidee_ts: instant de la decision, en secondes epoch.
        executee: None (pas encore statue), True (executee) ou False (ne
            sera pas executee).
        executee_ts: instant ou :meth:`InterventionJournal.marquer_executee`
            a ete appelee, ou None.
        date_effet_ts: instant a partir duquel l'action produit son effet -
            ancre la fenetre d'observation du resultat operationnel.
        resultat: ``'resolu'`` | ``'partiel'`` | ``'echec'`` | ``'en_cours'``.
        etat_apres: etat OBSERVABLE declare a la cloture, ou None tant que
            l'intervention n'est pas close.
        etat_risque_avant: etat de risque D'INTERFACE a l'ouverture (snapshot
            complet de ``node.urgency``), jamais lu pour le resultat.
        etat_risque_apres: etat de risque D'INTERFACE a la cloture, ou None.
        succes: derive de ``resultat`` a la cloture (resolu -> True,
            echec -> False, partiel/en_cours -> None).
        effets_voisins: effets observes sur des noeuds voisins (texte libre).
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
    """Serialise une :class:`Intervention` en ligne prete pour ``insert_intervention``."""
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
    """Journal des interventions : ouverture, execution, proposition, cloture.

    S'appuie sur la facade :class:`SupplyScoreService` : le registre fournit
    les noeuds (etat d'urgence courant, jalons), ``clock_for`` l'horloge
    effective du projet, et la base CLIENT du noeud porte la table
    ``interventions``.
    """

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le journal des interventions au-dessus de la facade.

        Args:
            service: facade applicative (registre, bases client, horloges).
        """
        self._service = service

    # aides internes (memes que DecisionService)

    def _node(self, node_id: str) -> SupplyNode:
        """Lecture fraiche du noeud depuis le registre.

        Args:
            node_id: identifiant du noeud.

        Returns:
            Le :class:`~supplyscore.domain.models.SupplyNode` du registre.

        Raises:
            ValueError: si le noeud est inconnu du registre.
        """
        node = self._service.registry.get_node(node_id)
        if node is None:
            raise ValueError(f"nœud inconnu du registre : {node_id!r}")
        return node

    def _clock_of(self, node: SupplyNode) -> Clock:
        """Horloge effective du noeud : celle de SON projet (reelle ou de jeu)."""
        if node.project_id:
            return self._service.clock_for(node.project_id)
        return self._service.clock

    def _row(self, intervention_id: str, node_id: str) -> dict[str, Any]:
        """Ligne brute de l'intervention (pas de getter dedie : filtrage en Python).

        Args:
            intervention_id: id de l'intervention recherchee.
            node_id: noeud porteur (chaque noeud a sa propre base CLIENT).

        Returns:
            La ligne brute (dict, cles = colonnes SQL) correspondante.

        Raises:
            ValueError: aucune intervention de cet id sur ce noeud.
        """
        for row in self._service.client_db(node_id).list_interventions(node_id):
            if row["id"] == intervention_id:
                return row
        raise ValueError(f"intervention inconnue : {intervention_id!r} (nœud {node_id!r})")

    @staticmethod
    def _etat_observable(urgence: UrgencyState) -> dict[str, float | None]:
        """Sous-ensemble OBSERVABLE contractuel de l'urgence courante (contrat no9)."""
        return {
            "ur_local": urgence.ur_local,
            "ud_local": urgence.ud_local,
            "hidden_risk": urgence.hidden_risk,
            "false_urgency": urgence.false_urgency,
        }

    @staticmethod
    def _etat_risque(urgence: UrgencyState) -> dict[str, float | None]:
        """Snapshot COMPLET de l'urgence courante - information d'INTERFACE seulement."""
        return {
            "ud_local": urgence.ud_local,
            "ur_local": urgence.ur_local,
            "ud": urgence.ud,
            "ur": urgence.ur,
            "adequation": urgence.adequation,
            "false_urgency": urgence.false_urgency,
            "hidden_risk": urgence.hidden_risk,
        }

    # ecriture : ouverture

    def record(
        self,
        node_id: str,
        action_id: str,
        acteur: str,
        objectif_operationnel: str,
        etat_avant: dict[str, Any] | None = None,
        notes: str = "",
    ) -> Intervention:
        """Ouvre une intervention : capture l'etat AVANT et journalise son objectif.

        ``etat_avant``, non fourni, est capture AUTOMATIQUEMENT depuis
        ``node.urgency`` (lecture fraiche du registre, observables
        contractuels seulement - ``p_issue`` n'y figure jamais
        automatiquement, un appelant qui dispose d'une probabilite d'issue
        externe peut la fournir en ecrasant ``etat_avant``).
        ``etat_risque_avant`` (interface) est TOUJOURS capture automatiquement,
        pleinement, et n'est jamais surchargeable.

        Args:
            node_id: identifiant du noeud concerne.
            action_id: identifiant de l'action de prescription appliquee.
            acteur: personne ou role decidant l'intervention (non vide).
            objectif_operationnel: objectif declare a l'ouverture (non vide).
            etat_avant: etat observable a l'ouverture ; None -> capture
                automatiquement depuis ``node.urgency``.
            notes: commentaire libre initial.

        Returns:
            L':class:`Intervention` telle que persistee (``resultat`` vaut
            ``'en_cours'``).

        Raises:
            ValueError: ``acteur``/``objectif_operationnel`` vide (ou blanc),
                ou noeud inconnu du registre - rien n'est alors ecrit.
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

    # ecriture : execution

    def marquer_executee(
        self,
        intervention_id: str,
        node_id: str,
        executee: bool,
        date_effet_ts: float | None,
    ) -> None:
        """Marque l'intervention comme executee (ou non) et pose sa date d'effet.

        ``date_effet_ts`` ancre la fenetre d'observation
        ``[date_effet, date_effet + 4 semaines[`` de :meth:`proposer_resultat` ;
        sans elle, le resultat operationnel reste ``'en_cours'`` indefiniment.

        Args:
            intervention_id: id de l'intervention a mettre a jour.
            node_id: noeud porteur de l'intervention.
            executee: True si l'action a ete effectivement executee.
            date_effet_ts: instant (epoch s) a partir duquel l'action produit
                son effet, ou None si non encore connu.

        Raises:
            ValueError: intervention inconnue sur ce noeud, ou noeud inconnu
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

    # lecture : proposition (jamais d'ecriture)

    def proposer_resultat(self, intervention_id: str, node_id: str) -> tuple[str, list[str]]:
        """Propose un resultat operationnel - NE modifie jamais la base.

        Applique la definition FIGEE du module sur la fenetre
        ``[date_effet, date_effet + 4 semaines[`` : issue defavorable
        (:func:`~supplyscore.services.calibration.issues_defavorables`, sur
        les jalons et evenements du noeud) d'abord, puis atteinte de
        l'objectif (proxy model-free : jalon livre DANS la fenetre) une fois
        la fenetre entierement ecoulee. Ne lit JAMAIS Ud/Ur/H - seulement des
        faits (jalons, evenements, statut du noeud) - conformement a la
        separation stricte entre resultat causal et etat de risque
        d'interface (voir le docstring du module).

        Args:
            intervention_id: id de l'intervention a evaluer.
            node_id: noeud porteur de l'intervention.

        Returns:
            ``(resultat_propose, causes)`` - ``causes`` explicite la
            proposition en francais (``[]`` pour ``'en_cours'`` sans motif
            particulier). RIEN n'est ecrit : c'est :meth:`clore` qui
            persiste le resultat retenu par l'operateur.

        Raises:
            ValueError: intervention inconnue sur ce noeud, ou noeud inconnu
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

        # Fenetre entierement ecoulee, aucune issue defavorable : l'atteinte de l'objectif s'evalue sur les jalons echeant DANS la fenetre (proxy KPI cible model-free - jamais Ud/Ur/H). Tout jalon ACTIVE encore en jeu dans la fenetre aurait deja ete signale ci-dessus par ``issues_defavorables`` une fois la fenetre close : seuls des jalons DONE peuvent donc subsister ici.
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

    # ecriture : cloture (humaine)

    def clore(
        self,
        intervention_id: str,
        node_id: str,
        resultat: str,
        etat_apres: dict[str, Any] | None = None,
        effets_voisins: list[str] | None = None,
        notes: str = "",
    ) -> None:
        """Cloture l'intervention avec le resultat RETENU par l'operateur.

        ``etat_apres``, non fourni, est capture AUTOMATIQUEMENT depuis
        ``node.urgency`` (meme regle que :meth:`record`). ``etat_risque_apres``
        (interface) est TOUJOURS capture automatiquement. ``succes`` est
        DERIVE de ``resultat`` : ``'resolu'`` -> True, ``'echec'`` -> False,
        ``'partiel'``/``'en_cours'`` -> None.

        Args:
            intervention_id: id de l'intervention a cloturer.
            node_id: noeud porteur de l'intervention.
            resultat: ``'resolu'`` | ``'partiel'`` | ``'echec'`` | ``'en_cours'``
                - c'est L'OPERATEUR qui choisit, eventuellement apres avoir
                consulte :meth:`proposer_resultat`.
            etat_apres: etat observable a la cloture ; None -> capture
                automatiquement depuis ``node.urgency``.
            effets_voisins: effets observes sur des noeuds voisins.
            notes: commentaire libre (remplace les notes existantes).

        Raises:
            ValueError: ``resultat`` hors des 4 valeurs autorisees, ou
                intervention/noeud inconnu - rien n'est alors ecrit.
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

    # lecture

    def list_for_node(self, node_id: str, only_open: bool = False) -> list[Intervention]:
        """Interventions du noeud, les plus anciennes d'abord.

        Args:
            node_id: identifiant du noeud.
            only_open: si True, ne retourne que les interventions dont le
                resultat operationnel est encore ``'en_cours'``.

        Returns:
            Les :class:`Intervention` du noeud, triees par ``date_ts`` croissant.
        """
        rows = self._service.client_db(node_id).list_interventions(node_id, only_open=only_open)
        return [_intervention_from_row(row) for row in rows]

    def stats_par_action(self, project_id: str) -> dict[str, dict[str, int]]:
        """Statistiques d'interventions par action, agregees sur le projet entier.

        Balaie le journal de CHAQUE noeud du projet (chaque noeud a sa propre
        base CLIENT) - c'est l'entree temps reel du modele d'effet des
        actions de prescription (nombre d'essais, taux d'execution, taux de
        succes observes par action).

        Args:
            project_id: identifiant du projet.

        Returns:
            Un dict ``action_id -> {"n", "n_executees", "n_succes",
            "n_echecs"}`` (compteurs entiers ; ``n`` compte TOUTES les
            interventions de l'action, executees ou non).
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

    # bootstrap / tests

    def import_synthetic(
        self, path_jsonl: str | Path, node_mapping: dict[str, str] | None = None
    ) -> int:
        """Rejoue un fichier JSONL synthetique (" interventions_truth ") dans le journal.

        Format tolere (une intervention par ligne JSON) : ``tour`` (numero de
        semaine synthetique - ancre arbitrairement sur l'epoch Unix, 0 = la
        semaine du 1er janvier 1970 ; ``date_ts = tour x 604 800`` s, un
        ancrage arbitraire mais deterministe, suffisant pour un rejeu de
        test/bootstrap), ``node`` (id de noeud, reecrit par ``node_mapping``
        si fourni), ``action_id``, ``etat_avant`` (dict, stocke tel quel),
        ``decidee`` (bool ; si explicitement ``False``, la ligne est une
        candidate NON retenue par le generateur et n'est PAS importee),
        ``executee`` (bool), ``date_effet`` (numero de semaine synthetique,
        comme ``tour``), ``resultat_operationnel`` (une des 4 valeurs
        figees ; retombe sur ``'en_cours'`` si absente ou invalide),
        ``effets_voisins`` (liste). Cles inconnues tolerees et ignorees.

        Args:
            path_jsonl: chemin du fichier JSONL a rejouer.
            node_mapping: reecriture optionnelle ``id du fichier -> id reel``
                (rejoue un fichier generique sur des ids de noeuds differents).

        Returns:
            Le nombre de lignes effectivement importees (les candidates
            ``decidee: false`` ne sont pas comptees).

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
                    continue  # candidate non retenue par le generateur : pas une vraie intervention
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
