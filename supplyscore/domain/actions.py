"""Catalogue d'actions correctives — cœur de la couche prescriptive HÉLIOS v7.

Une :class:`ActionSpec` décrit une action corrective candidate avec DEUX
applications de même sémantique :

- :attr:`~ActionSpec.apply_to_rollout` — application SIMULÉE, pure, consommée
  par les rollouts contrefactuels Monte Carlo (worker U9) ;
- :attr:`~ActionSpec.apply_to_project` — application RÉELLE, qui écrit dans le
  projet via :class:`~supplyscore.services.mutations.MutationService` (jamais
  d'écriture directe).

Les deux applications doivent produire le MÊME effet relatif sur le système
(cf. tests d'équivalence de ce module) — c'est ce qui rend la prescription
contrefactuelle honnête : ce qui est simulé est ce qui serait réellement fait.

Contrat du state de rollout
----------------------------
:data:`RolloutState` est un dictionnaire à 4 clés, propriété du moteur Monte
Carlo (U9) ; ce module ne fait qu'y lire/écrire selon la convention suivante
(documentée ici faute d'implémentation commune au moment de l'écriture) :

- ``"ur_local"`` : tableau (numpy ou compatible) — trajectoire d'urgence
  locale agrégée du nœud sur l'horizon du rollout. Modifié par
  :func:`_apply_rollout_expedition_express` (le contrat de rollout n'isolant
  pas le bloc temporel, la réduction de lead time est reportée sur
  l'agrégat).
- ``"hazard"`` : tableau — trajectoire de hazard (risque de rupture/stock)
  du nœud. Modifié par :func:`_apply_rollout_boost_capacite`.
- ``"deadlines_h"`` : ``dict[str, float]`` — échéances en heures, par clé
  métier (jalon...). Modifié par :func:`_apply_rollout_replanifier_jalon`,
  qui décale UNIQUEMENT l'entrée de valeur minimale (l'échéance la plus
  proche) — même règle de sélection que :func:`_apply_project_replanifier_jalon`
  côté réel (:func:`~supplyscore.domain.milestones.next_active_milestone`),
  pour que les deux applications portent sur le même jalon.
- ``"arc_beta"`` : ``dict[str, float]`` — contribution beta actuellement
  comptée dans la propagation montante, par id d'arc
  (:attr:`~supplyscore.domain.models.SupplyArc.id`). Un arc de secours pas
  encore promu y apparaît sous la clé ``f"{arc.id}:backup"`` (convention de
  ce module) ; :func:`_apply_rollout_promouvoir_arc_secours` le promeut en
  ajoutant son beta à la contribution nominale et en retirant l'entrée
  ``:backup`` — s'il y en a plusieurs, celle de plus petite ``source_id``
  est choisie, même règle de départage que côté réel.

Chaque ``apply_to_rollout`` est PURE : le ``state`` reçu n'est jamais
modifié en place, une copie modifiée est retournée (cf. :func:`_clone_state`).
Cette copie est SUPERFICIELLE : les clés non touchées par une action donnée
restent des références PARTAGÉES avec le ``state`` d'entrée (ex. tout le
state retourné par les actions identité). Un consommateur qui dérive
plusieurs rollouts à partir d'un même state parent (ex. un arbre de
scénarios) ne doit donc jamais muter en place un conteneur reçu en retour —
seule la création de nouveaux conteneurs (comme le fait ce module) préserve
la pureté de bout en bout.

Identité d'opérateur des écritures automatiques
-------------------------------------------------
``apply_to_project`` ne reçoit pas d'``operator_id`` (contrat gelé :
``apply_to_project(service, node_id) -> None``) : les écritures réelles sont
donc attribuées à l'identité constante :data:`_OPERATEUR_ACTION`
(``source="action"`` côté :class:`~supplyscore.services.mutations.MutationService`),
distincte des éditions humaines. Un moteur d'exécution qui connaît
l'opérateur réel (déclencheur humain d'une prescription) peut l'enrichir en
aval, dans son propre journal — hors périmètre de ce catalogue.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypedDict

from supplyscore.domain.milestones import Milestone, next_active_milestone
from supplyscore.domain.models import ArcKind, SupplyArc, SupplyNode, UrgencyState

if TYPE_CHECKING:
    from supplyscore.services.orchestrator import SupplyScoreService

#: Identité d'opérateur des écritures automatiques du catalogue (cf. docstring
#: de module) — distincte d'un ``operator_id`` humain.
_OPERATEUR_ACTION = "action:catalogue"

_UNE_SEMAINE_S: float = 7.0 * 24.0 * 3600.0
_UNE_SEMAINE_H: float = 7.0 * 24.0
_DEUX_SEMAINES_S: float = 2.0 * _UNE_SEMAINE_S
_DEUX_SEMAINES_H: float = 2.0 * _UNE_SEMAINE_H

#: Facteur d'expédition express — réduction documentée de 30 % du lead time,
#: appliqué à l'identique côté rollout (:func:`_apply_rollout_expedition_express`)
#: pour rendre le test d'équivalence sim/réel exact.
_FACTEUR_EXPRESS: float = 0.7

#: Amortissement documenté de la trajectoire de hazard après renfort de
#: capacité (débit + volume) — cf. :func:`_apply_rollout_boost_capacite`.
_FACTEUR_HAZARD_CAPACITE: float = 0.75

#: Renforts documentés de ``boost_capacite`` : +30 % de débit, +20 % de volume max.
_FACTEUR_FLOW_BOOST: float = 1.3
_FACTEUR_VOLUME_BOOST: float = 1.2

#: Suffixe marquant, dans ``state["arc_beta"]``, un arc de secours pas encore
#: promu (cf. docstring de module).
_SUFFIXE_BACKUP: str = ":backup"

#: Liste FERMÉE des objectifs opérationnels mesurables, référencée par le
#: journal d'interventions (U16) pour qualifier l'effet visé d'une action.
OBJECTIFS_OPERATIONNELS: tuple[str, ...] = (
    "tenir_echeance_client",  # respecter la deadline d'origine (accélération)
    "renegocier_echeance",  # décaler la deadline en accord avec le programme/client
    "fiabiliser_approvisionnement",  # réduire la dépendance à un fournisseur défaillant
    "augmenter_capacite",  # lever un goulot capacitaire ou de débit
    "realigner_ud_ur",  # réduire l'écart entre urgence déclarée et urgence réelle
    "maitriser_cout",  # contenir le surcoût d'intervention
)


# --- Contexte en lecture seule -----------------------------------------------------


@dataclass(frozen=True)
class ContexteAction:
    """Contexte en lecture seule d'un nœud, consommé par les préconditions.

    Attributes:
        node: nœud cible de l'action.
        arcs_entrants: arcs NOMINAUX entrants (fournisseurs actifs du nœud).
        arcs_backup: arcs BACKUP entrants (arcs de secours candidats à la
            promotion par l'action ``"promouvoir_arc_secours"`` de :data:`CATALOGUE_V1`).
        urgency: état d'urgence courant du nœud (alias de ``node.urgency``).
        milestones: jalons du nœud (ordre quelconque, cf.
            :mod:`supplyscore.domain.milestones`).
    """

    node: SupplyNode
    arcs_entrants: list[SupplyArc]
    arcs_backup: list[SupplyArc]
    urgency: UrgencyState
    milestones: list[Milestone]


def contexte_pour(service: SupplyScoreService, node_id: str) -> ContexteAction:
    """Construit le :class:`ContexteAction` d'un nœud depuis la façade applicative.

    Lecture seule : n'écrit rien, ne passe jamais par
    :class:`~supplyscore.services.mutations.MutationService`.

    Args:
        service: façade applicative (dépôt de graphe en mémoire, registre).
        node_id: identifiant du nœud.

    Returns:
        Le :class:`ContexteAction` du nœud.

    Raises:
        KeyError: si le nœud est inconnu du dépôt en mémoire.
    """
    node = service.repo.get_node(node_id)
    if node is None:
        raise KeyError(f"Nœud inconnu : {node_id!r}")
    arcs_entrants = [
        a for a in service.repo.arcs(kinds=(ArcKind.NOMINAL,)) if a.target_id == node_id
    ]
    arcs_backup = [a for a in service.repo.arcs(kinds=(ArcKind.BACKUP,)) if a.target_id == node_id]
    milestones = service.registry.list_milestones(node_id)
    return ContexteAction(
        node=node,
        arcs_entrants=arcs_entrants,
        arcs_backup=arcs_backup,
        urgency=node.urgency,
        milestones=milestones,
    )


# --- State de rollout (Monte Carlo contrefactuel, worker U9) -----------------------

#: State de rollout — dictionnaire à 4 clés, cf. docstring de module.
RolloutState = dict[str, Any]


def _clone_state(state: RolloutState) -> RolloutState:
    """Copie superficielle du state (nouveau dict de premier niveau).

    Chaque fonction ``apply_to_rollout`` qui modifie une clé imbriquée
    (``deadlines_h``, ``arc_beta``, ``ur_local``, ``hazard``) construit un
    NOUVEL objet pour cette clé plutôt que de muter l'existant — c'est cette
    discipline, combinée à cette copie superficielle, qui garantit la pureté
    (``state`` en entrée n'est jamais modifié).
    """
    return dict(state)


# --- Coût structuré -----------------------------------------------------------------


class CoutAction(TypedDict):
    """Coût structuré d'une action corrective (contrat gelé n° 8).

    Attributes:
        monetaire: intervalle ``(lo, hi)`` en euros, ou None si à chiffrer
            par projet (coût trop dépendant du contexte pour un défaut générique).
        temps_h: charge humaine en heures, ou None si sans objet.
        penalite_client_evitee: intervalle ``(lo, hi)`` de pénalité
            contractuelle évitée, ou None si sans objet.
        mobilisation: description qualitative des équipes/ressources mobilisées.
        p_echec_execution_defaut: probabilité d'échec d'exécution par
            défaut, dans [0, 1] (cf. :func:`_validate_catalogue`).
    """

    monetaire: tuple[float, float] | None
    temps_h: float | None
    penalite_client_evitee: tuple[float, float] | None
    mobilisation: str
    p_echec_execution_defaut: float


# --- Contrat ActionSpec (n° 8) -------------------------------------------------------


@dataclass(frozen=True)
class ActionSpec:
    """Action corrective candidate : effet simulé ET effet réel de même sémantique.

    Attributes:
        id: identifiant unique (clé de :data:`CATALOGUE_V1`).
        libelle: libellé d'affichage en français.
        preconditions: ``ctx -> bool`` — l'action est-elle applicable au nœud ?
        apply_to_rollout: ``state -> state`` — application SIMULÉE, PURE
            (cf. :data:`RolloutState`).
        apply_to_project: ``(service, node_id) -> None`` — application
            RÉELLE, via :class:`~supplyscore.services.mutations.MutationService`
            uniquement.
        delai_effet_weeks: ``(min, mode, max)`` — délai avant effet complet,
            en semaines (distribution triangulaire), ``min <= mode <= max``.
        cout: coût structuré (cf. :class:`CoutAction`).
        risque_secondaire: description française du risque secondaire de
            l'action (ce qu'elle peut dégrader ailleurs).
        incompatibles: ids d'actions ne pouvant pas être combinées avec
            celle-ci dans le même plan d'intervention (doivent exister dans
            :data:`CATALOGUE_V1`).
        objectifs_operationnels: sous-ensemble de :data:`OBJECTIFS_OPERATIONNELS`
            visé par l'action.
    """

    id: str
    libelle: str
    preconditions: Callable[[ContexteAction], bool]
    apply_to_rollout: Callable[[RolloutState], RolloutState]
    apply_to_project: Callable[[SupplyScoreService, str], None]
    delai_effet_weeks: tuple[float, float, float]
    cout: CoutAction
    risque_secondaire: str
    incompatibles: list[str]
    objectifs_operationnels: list[str]


# --- promouvoir_arc_secours ----------------------------------------------------------


def _precondition_promouvoir_arc_secours(ctx: ContexteAction) -> bool:
    """Vrai si au moins un arc de secours alimente le nœud."""
    return bool(ctx.arcs_backup)


def _apply_project_promouvoir_arc_secours(service: SupplyScoreService, node_id: str) -> None:
    """Promeut l'arc de secours entrant prioritaire en arc nominal.

    Sélectionne, parmi les arcs BACKUP entrants du nœud, celui de
    ``source_id`` le plus petit (ordre lexicographique — règle de départage
    déterministe et documentée, utile quand plusieurs arcs de secours
    existent) et le fait basculer en
    :attr:`~supplyscore.domain.models.ArcKind.NOMINAL` via
    :meth:`~supplyscore.services.mutations.MutationService.upsert_arc`.
    No-op silencieux si le nœud n'a aucun arc de secours entrant (la
    précondition n'est pas revérifiée ici — un appel direct reste possible).

    Raises:
        KeyError: si le nœud est inconnu du dépôt en mémoire.
    """
    if service.repo.get_node(node_id) is None:
        raise KeyError(f"Nœud inconnu : {node_id!r}")
    backups = [a for a in service.repo.arcs(kinds=(ArcKind.BACKUP,)) if a.target_id == node_id]
    if not backups:
        return
    chosen = min(backups, key=lambda a: a.source_id)
    promoted = dataclasses.replace(chosen, kind_arc=ArcKind.NOMINAL)
    service.mutations.upsert_arc(promoted, source="action", operator_id=_OPERATEUR_ACTION)


def _apply_rollout_promouvoir_arc_secours(state: RolloutState) -> RolloutState:
    """Active dans ``arc_beta`` l'arc de secours en attente prioritaire.

    Ajoute le beta de l'arc de secours (clé ``f"{arc_id}:backup"``) à la
    contribution nominale déjà présente sous ``arc_id`` (0.0 si absente) et
    retire l'entrée ``:backup`` — traduction, côté rollout, d'une dépendance
    désormais répartie sur un second fournisseur actif. S'il y a plusieurs
    entrées ``:backup`` en attente, celle de plus petite ``source_id`` est
    choisie — MÊME règle de départage que côté réel
    (:func:`_apply_project_promouvoir_arc_secours`), pour que les deux
    applications promeuvent toujours le même arc. No-op (copie inchangée)
    si aucune entrée ``:backup`` n'est présente.
    """
    new_state = _clone_state(state)
    arc_beta = dict(state.get("arc_beta", {}))
    backup_keys = [k for k in arc_beta if k.endswith(_SUFFIXE_BACKUP)]
    if backup_keys:
        backup_key = min(backup_keys, key=lambda k: k[: -len(_SUFFIXE_BACKUP)].partition("->")[0])
        arc_id = backup_key[: -len(_SUFFIXE_BACKUP)]
        beta = arc_beta.pop(backup_key)
        arc_beta[arc_id] = arc_beta.get(arc_id, 0.0) + beta
    new_state["arc_beta"] = arc_beta
    return new_state


# --- replanifier_jalon -----------------------------------------------------------------


def _precondition_replanifier_jalon(ctx: ContexteAction) -> bool:
    """Vrai si un jalon ACTIVE existe pour le nœud."""
    return next_active_milestone(ctx.milestones) is not None


def _apply_project_replanifier_jalon(service: SupplyScoreService, node_id: str) -> None:
    """Décale de 2 semaines la deadline du prochain jalon actif (règle §6.3).

    Règle « revue de programme » du protocole HÉLIOS §6.3 : seule
    ``deadline_ts`` est décalée, ``start_ts`` reste inchangé (le jalon est
    déjà en cours) — l'invariant ``start_ts < deadline_ts`` de
    :meth:`~supplyscore.services.mutations.MutationService.update_milestone`
    reste donc trivialement respecté. No-op si le nœud n'a aucun jalon actif.

    Raises:
        KeyError: si le nœud est inconnu du dépôt en mémoire.
    """
    if service.repo.get_node(node_id) is None:
        raise KeyError(f"Nœud inconnu : {node_id!r}")
    target = next_active_milestone(service.registry.list_milestones(node_id))
    if target is None:
        return
    service.mutations.update_milestone(
        target.id,
        {"deadline_ts": target.deadline_ts + _DEUX_SEMAINES_S},
        source="action",
        operator_id=_OPERATEUR_ACTION,
    )


def _apply_rollout_replanifier_jalon(state: RolloutState) -> RolloutState:
    """Décale de 2 semaines (336 h) l'échéance la plus proche de ``deadlines_h``.

    Même règle de sélection que côté réel
    (:func:`_apply_project_replanifier_jalon`, via
    :func:`~supplyscore.domain.milestones.next_active_milestone`) : seule
    l'entrée de valeur MINIMALE (l'échéance la plus proche) est décalée, les
    autres restent inchangées. No-op si ``deadlines_h`` est vide.
    """
    new_state = _clone_state(state)
    deadlines = dict(state.get("deadlines_h", {}))
    if deadlines:
        nearest_key = min(deadlines, key=lambda key: deadlines[key])
        deadlines[nearest_key] = deadlines[nearest_key] + _DEUX_SEMAINES_H
    new_state["deadlines_h"] = deadlines
    return new_state


# --- expedition_express -----------------------------------------------------------------


def _precondition_expedition_express(ctx: ContexteAction) -> bool:
    """Toujours applicable (aucune précondition métier au-delà du nœud existant)."""
    return True


def _apply_project_expedition_express(service: SupplyScoreService, node_id: str) -> None:
    """Réduit le lead time du nœud de 30 % (facteur documenté :data:`_FACTEUR_EXPRESS`).

    No-op si ``time.lead_time_h`` n'est pas renseigné (rien à accélérer).

    Raises:
        KeyError: si le nœud est inconnu du dépôt en mémoire.
    """
    node = service.repo.get_node(node_id)
    if node is None:
        raise KeyError(f"Nœud inconnu : {node_id!r}")
    lead_time_h = node.kpis.time.lead_time_h
    if lead_time_h is None:
        return
    service.mutations.update_kpis(
        node_id,
        {"time.lead_time_h": lead_time_h * _FACTEUR_EXPRESS},
        source="action",
        operator_id=_OPERATEUR_ACTION,
    )


def _apply_rollout_expedition_express(state: RolloutState) -> RolloutState:
    """Réduit de 30 % la trajectoire d'urgence locale ``ur_local`` (même facteur que le KPI).

    Simplification documentée : le contrat de rollout n'expose pas le bloc
    temporel isolément — la réduction du lead time est donc reportée sur la
    trajectoire agrégée ``ur_local``, DANS LA MÊME PROPORTION que la
    réduction réelle du KPI. C'est ce qui rend le test d'équivalence
    sim/réel exact (même variation relative des deux côtés).
    """
    new_state = _clone_state(state)
    new_state["ur_local"] = state["ur_local"] * _FACTEUR_EXPRESS
    return new_state


# --- boost_capacite -----------------------------------------------------------------------


def _precondition_boost_capacite(ctx: ContexteAction) -> bool:
    """Applicable si au moins un KPI de capacité/débit est renseigné."""
    inv = ctx.node.kpis.inventory
    return inv.flow_rate is not None or inv.max_volume_m3 is not None


def _apply_project_boost_capacite(service: SupplyScoreService, node_id: str) -> None:
    """Augmente le débit (+30 %) et/ou le volume max (+20 %) du nœud, si renseignés.

    Les deux KPIs sont indépendants : seuls ceux effectivement renseignés
    sont modifiés (no-op complet si ni l'un ni l'autre ne l'est).

    Raises:
        KeyError: si le nœud est inconnu du dépôt en mémoire.
    """
    node = service.repo.get_node(node_id)
    if node is None:
        raise KeyError(f"Nœud inconnu : {node_id!r}")
    inv = node.kpis.inventory
    changes: dict[str, float | None] = {}
    if inv.flow_rate is not None:
        changes["inventory.flow_rate"] = inv.flow_rate * _FACTEUR_FLOW_BOOST
    if inv.max_volume_m3 is not None:
        changes["inventory.max_volume_m3"] = inv.max_volume_m3 * _FACTEUR_VOLUME_BOOST
    if changes:
        service.mutations.update_kpis(
            node_id, changes, source="action", operator_id=_OPERATEUR_ACTION
        )


def _apply_rollout_boost_capacite(state: RolloutState) -> RolloutState:
    """Réduit de 25 % la trajectoire de hazard (rupture/stock) du nœud.

    Simplification documentée : un débit/volume accru réduit le risque de
    rupture plutôt que l'urgence temporelle — traduit ici par un
    amortissement de la trajectoire ``hazard``, distincte de ``ur_local``
    (utilisée par :func:`_apply_rollout_expedition_express`).
    """
    new_state = _clone_state(state)
    new_state["hazard"] = state["hazard"] * _FACTEUR_HAZARD_CAPACITE
    return new_state


# --- revue_declaration -----------------------------------------------------------------


def _precondition_revue_declaration(ctx: ContexteAction) -> bool:
    """Applicable si une urgence déclarée (Ud local) existe déjà pour le nœud."""
    return ctx.urgency.ud_local is not None


def _apply_project_revue_declaration(service: SupplyScoreService, node_id: str) -> None:
    """No-op côté écriture : déclenche une demande de réévaluation (couche insight).

    Aucun KPI n'est modifié — seule la couche d'explicabilité/insight (hors
    périmètre de ce module) consomme le déclenchement de cette action pour
    solliciter un nouveau questionnaire AHP auprès de l'opérateur terrain.
    """
    return None


def _apply_rollout_revue_declaration(state: RolloutState) -> RolloutState:
    """Identité : la révision de la déclaration n'a pas d'effet simulable direct."""
    return _clone_state(state)


# --- ne_rien_faire (bras de référence) -----------------------------------------------


def _precondition_ne_rien_faire(ctx: ContexteAction) -> bool:
    """Toujours applicable — bras de référence (baseline) du catalogue."""
    return True


def _apply_project_ne_rien_faire(service: SupplyScoreService, node_id: str) -> None:
    """No-op total : aucune écriture, par définition du bras de référence."""
    return None


def _apply_rollout_ne_rien_faire(state: RolloutState) -> RolloutState:
    """Identité stricte : retourne une copie inchangée du state."""
    return _clone_state(state)


# --- Catalogue V1 ---------------------------------------------------------------------


def _validate_catalogue(catalogue: dict[str, ActionSpec]) -> None:
    """Valide les invariants d'intégrité du catalogue.

    Raises:
        ValueError: id incohérent avec sa clé, ``incompatibles`` référençant
            un id absent du catalogue ou non symétrique,
            ``p_echec_execution_defaut`` hors [0, 1], ou
            ``delai_effet_weeks`` non croissant (``min <= mode <= max``) —
            un seul message, toutes les erreurs listées.
    """
    errors: list[str] = []
    for key, spec in catalogue.items():
        if spec.id != key:
            errors.append(f"{key} : id incohérent avec sa clé ({spec.id!r})")
        inconnus = [i for i in spec.incompatibles if i not in catalogue]
        if inconnus:
            errors.append(f"{key} : incompatibles inconnus {inconnus}")
        asymetriques = [
            i
            for i in spec.incompatibles
            if i in catalogue and key not in catalogue[i].incompatibles
        ]
        if asymetriques:
            errors.append(f"{key} : incompatibilité non symétrique avec {asymetriques}")
        p = spec.cout["p_echec_execution_defaut"]
        if not 0.0 <= p <= 1.0:
            errors.append(f"{key} : p_echec_execution_defaut hors [0, 1] ({p})")
        lo, mode, hi = spec.delai_effet_weeks
        if not lo <= mode <= hi:
            errors.append(f"{key} : delai_effet_weeks non croissant ({lo}, {mode}, {hi})")
    if errors:
        raise ValueError("Catalogue d'actions invalide : " + " ; ".join(errors))


#: Catalogue V1 — 6 actions correctives (contrat gelé n° 8).
CATALOGUE_V1: dict[str, ActionSpec] = {
    "promouvoir_arc_secours": ActionSpec(
        id="promouvoir_arc_secours",
        libelle="Promouvoir un arc de secours en arc nominal",
        preconditions=_precondition_promouvoir_arc_secours,
        apply_to_rollout=_apply_rollout_promouvoir_arc_secours,
        apply_to_project=_apply_project_promouvoir_arc_secours,
        delai_effet_weeks=(0.5, 1.0, 2.0),
        cout=CoutAction(
            monetaire=None,  # à chiffrer par projet (requalification fournisseur)
            temps_h=8.0,
            penalite_client_evitee=None,
            mobilisation="achats + qualité fournisseur de secours",
            p_echec_execution_defaut=0.15,
        ),
        risque_secondaire=(
            "le fournisseur de secours peut ne pas absorber le volume nominal complet "
            "(capacité ou qualité non qualifiées à ce niveau)"
        ),
        incompatibles=["ne_rien_faire"],
        objectifs_operationnels=["fiabiliser_approvisionnement"],
    ),
    "replanifier_jalon": ActionSpec(
        id="replanifier_jalon",
        libelle="Replanifier le jalon actif (+2 semaines)",
        preconditions=_precondition_replanifier_jalon,
        apply_to_rollout=_apply_rollout_replanifier_jalon,
        apply_to_project=_apply_project_replanifier_jalon,
        delai_effet_weeks=(0.0, 0.1, 0.5),
        cout=CoutAction(
            monetaire=None,
            temps_h=2.0,
            penalite_client_evitee=None,
            mobilisation="chef de projet + accord client",
            p_echec_execution_defaut=0.10,
        ),
        risque_secondaire=(
            "le client peut refuser le décalage et maintenir la pénalité contractuelle"
        ),
        incompatibles=["expedition_express", "ne_rien_faire"],
        objectifs_operationnels=["renegocier_echeance"],
    ),
    "expedition_express": ActionSpec(
        id="expedition_express",
        libelle="Expédition express (lead time réduit de 30 %)",
        preconditions=_precondition_expedition_express,
        apply_to_rollout=_apply_rollout_expedition_express,
        apply_to_project=_apply_project_expedition_express,
        delai_effet_weeks=(0.1, 0.3, 1.0),
        cout=CoutAction(
            monetaire=(1500.0, 6000.0),
            temps_h=1.0,
            penalite_client_evitee=(2000.0, 20000.0),
            mobilisation="transporteur express + douane prioritaire",
            p_echec_execution_defaut=0.05,
        ),
        risque_secondaire="surcoût carbone et logistique non recalibré par ce catalogue",
        incompatibles=["replanifier_jalon", "ne_rien_faire"],
        objectifs_operationnels=["tenir_echeance_client"],
    ),
    "boost_capacite": ActionSpec(
        id="boost_capacite",
        libelle="Renforcer la capacité (débit +30 %, volume +20 %)",
        preconditions=_precondition_boost_capacite,
        apply_to_rollout=_apply_rollout_boost_capacite,
        apply_to_project=_apply_project_boost_capacite,
        delai_effet_weeks=(1.0, 2.0, 3.0),
        cout=CoutAction(
            monetaire=(500.0, 3000.0),
            temps_h=4.0,
            penalite_client_evitee=None,
            mobilisation="production + logistique (heures supplémentaires)",
            p_echec_execution_defaut=0.10,
        ),
        risque_secondaire=(
            "la capacité supplémentaire peut rester sous-utilisée si la demande ne se confirme pas"
        ),
        incompatibles=["ne_rien_faire"],
        objectifs_operationnels=["augmenter_capacite"],
    ),
    "revue_declaration": ActionSpec(
        id="revue_declaration",
        libelle="Revue de la déclaration (réévaluation Ud)",
        preconditions=_precondition_revue_declaration,
        apply_to_rollout=_apply_rollout_revue_declaration,
        apply_to_project=_apply_project_revue_declaration,
        delai_effet_weeks=(0.0, 0.2, 1.0),
        cout=CoutAction(
            monetaire=None,
            temps_h=0.5,
            penalite_client_evitee=None,
            mobilisation="opérateur terrain (entretien court)",
            p_echec_execution_defaut=0.02,
        ),
        risque_secondaire="la réévaluation peut confirmer l'écart Ud/Ur sans le résoudre",
        incompatibles=["ne_rien_faire"],
        objectifs_operationnels=["realigner_ud_ur"],
    ),
    "ne_rien_faire": ActionSpec(
        id="ne_rien_faire",
        libelle="Ne rien faire (bras de référence)",
        preconditions=_precondition_ne_rien_faire,
        apply_to_rollout=_apply_rollout_ne_rien_faire,
        apply_to_project=_apply_project_ne_rien_faire,
        delai_effet_weeks=(0.0, 0.0, 0.0),
        cout=CoutAction(
            monetaire=(0.0, 0.0),
            temps_h=0.0,
            penalite_client_evitee=(0.0, 0.0),
            mobilisation="aucune",
            p_echec_execution_defaut=0.0,
        ),
        risque_secondaire="le risque initial reste entier, sans atténuation",
        incompatibles=[
            "promouvoir_arc_secours",
            "replanifier_jalon",
            "expedition_express",
            "boost_capacite",
            "revue_declaration",
        ],
        objectifs_operationnels=[],
    ),
}

_validate_catalogue(CATALOGUE_V1)
