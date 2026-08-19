"""Catalogue d'actions correctives - coeur de la couche prescriptive HELIOS v7.

Une :class:`ActionSpec` decrit une action corrective candidate avec DEUX
applications de meme semantique :

- :attr:`~ActionSpec.apply_to_rollout` - application SIMULEE, pure, consommee
  par les rollouts contrefactuels Monte Carlo (worker U9) ;
- :attr:`~ActionSpec.apply_to_project` - application REELLE, qui ecrit dans le
  projet via :class:`~supplyscore.services.mutations.MutationService` (jamais
  d'ecriture directe).

Les deux applications doivent produire le MEME effet relatif sur le systeme
(cf. tests d'equivalence de ce module) - c'est ce qui rend la prescription
contrefactuelle honnete : ce qui est simule est ce qui serait reellement fait.

Contrat du state de rollout
----------------------------
:data:`RolloutState` est un dictionnaire a 4 cles, propriete du moteur Monte
Carlo (U9) ; ce module ne fait qu'y lire/ecrire selon la convention suivante
(documentee ici faute d'implementation commune au moment de l'ecriture) :

- ``"ur_local"`` : tableau (numpy ou compatible) - trajectoire d'urgence
  locale agregee du noeud sur l'horizon du rollout. Modifie par
  :func:`_apply_rollout_expedition_express` (le contrat de rollout n'isolant
  pas le bloc temporel, la reduction de lead time est reportee sur
  l'agregat).
- ``"hazard"`` : tableau - trajectoire de hazard (risque de rupture/stock)
  du noeud. Modifie par :func:`_apply_rollout_boost_capacite`.
- ``"deadlines_h"`` : ``dict[str, float]`` - echeances en heures, par cle
  metier (jalon...). Modifie par :func:`_apply_rollout_replanifier_jalon`,
  qui decale UNIQUEMENT l'entree de valeur minimale (l'echeance la plus
  proche) - meme regle de selection que :func:`_apply_project_replanifier_jalon`
  cote reel (:func:`~supplyscore.domain.milestones.next_active_milestone`),
  pour que les deux applications portent sur le meme jalon.
- ``"arc_beta"`` : ``dict[str, float]`` - contribution beta actuellement
  comptee dans la propagation montante, par id d'arc
  (:attr:`~supplyscore.domain.models.SupplyArc.id`). Un arc de secours pas
  encore promu y apparait sous la cle ``f"{arc.id}:backup"`` (convention de
  ce module) ; :func:`_apply_rollout_promouvoir_arc_secours` le promeut en
  ajoutant son beta a la contribution nominale et en retirant l'entree
  ``:backup`` - s'il y en a plusieurs, celle de plus petite ``source_id``
  est choisie, meme regle de departage que cote reel.

Chaque ``apply_to_rollout`` est PURE : le ``state`` recu n'est jamais
modifie en place, une copie modifiee est retournee (cf. :func:`_clone_state`).
Cette copie est SUPERFICIELLE : les cles non touchees par une action donnee
restent des references PARTAGEES avec le ``state`` d'entree (ex. tout le
state retourne par les actions identite). Un consommateur qui derive
plusieurs rollouts a partir d'un meme state parent (ex. un arbre de
scenarios) ne doit donc jamais muter en place un conteneur recu en retour -
seule la creation de nouveaux conteneurs (comme le fait ce module) preserve
la purete de bout en bout.

Identite d'operateur des ecritures automatiques
-------------------------------------------------
``apply_to_project`` ne recoit pas d'``operator_id`` (contrat gele :
``apply_to_project(service, node_id) -> None``) : les ecritures reelles sont
donc attribuees a l'identite constante :data:`_OPERATEUR_ACTION`
(``source="action"`` cote :class:`~supplyscore.services.mutations.MutationService`),
distincte des editions humaines. Un moteur d'execution qui connait
l'operateur reel (declencheur humain d'une prescription) peut l'enrichir en
aval, dans son propre journal - hors perimetre de ce catalogue.
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

#: Identite d'operateur des ecritures automatiques du catalogue (cf. docstring de module) - distincte d'un ``operator_id`` humain.
_OPERATEUR_ACTION = "action:catalogue"

_UNE_SEMAINE_S: float = 7.0 * 24.0 * 3600.0
_UNE_SEMAINE_H: float = 7.0 * 24.0
_DEUX_SEMAINES_S: float = 2.0 * _UNE_SEMAINE_S
_DEUX_SEMAINES_H: float = 2.0 * _UNE_SEMAINE_H

#: Facteur d'expedition express - reduction documentee de 30 % du lead time, applique a l'identique cote rollout (:func:`_apply_rollout_expedition_express`) pour rendre le test d'equivalence sim/reel exact.
_FACTEUR_EXPRESS: float = 0.7

#: Amortissement documente de la trajectoire de hazard apres renfort de capacite (debit + volume) - cf. :func:`_apply_rollout_boost_capacite`.
_FACTEUR_HAZARD_CAPACITE: float = 0.75

#: Renforts documentes de ``boost_capacite`` : +30 % de debit, +20 % de volume max.
_FACTEUR_FLOW_BOOST: float = 1.3
_FACTEUR_VOLUME_BOOST: float = 1.2

#: Suffixe marquant, dans ``state["arc_beta"]``, un arc de secours pas encore promu (cf. docstring de module).
_SUFFIXE_BACKUP: str = ":backup"

#: Liste FERMEE des objectifs operationnels mesurables, referencee par le journal d'interventions (U16) pour qualifier l'effet vise d'une action.
OBJECTIFS_OPERATIONNELS: tuple[str, ...] = (
    "tenir_echeance_client",  # respecter la deadline d'origine (acceleration)
    "renegocier_echeance",  # decaler la deadline en accord avec le programme/client
    "fiabiliser_approvisionnement",  # reduire la dependance a un fournisseur defaillant
    "augmenter_capacite",  # lever un goulot capacitaire ou de debit
    "realigner_ud_ur",  # reduire l'ecart entre urgence declaree et urgence reelle
    "maitriser_cout",  # contenir le surcout d'intervention
)


# Contexte en lecture seule


@dataclass(frozen=True)
class ContexteAction:
    """Contexte en lecture seule d'un noeud, consomme par les preconditions.

    Attributes:
        node: noeud cible de l'action.
        arcs_entrants: arcs NOMINAUX entrants (fournisseurs actifs du noeud).
        arcs_backup: arcs BACKUP entrants (arcs de secours candidats a la
            promotion par l'action ``"promouvoir_arc_secours"`` de :data:`CATALOGUE_V1`).
        urgency: etat d'urgence courant du noeud (alias de ``node.urgency``).
        milestones: jalons du noeud (ordre quelconque, cf.
            :mod:`supplyscore.domain.milestones`).
    """

    node: SupplyNode
    arcs_entrants: list[SupplyArc]
    arcs_backup: list[SupplyArc]
    urgency: UrgencyState
    milestones: list[Milestone]


def contexte_pour(service: SupplyScoreService, node_id: str) -> ContexteAction:
    """Construit le :class:`ContexteAction` d'un noeud depuis la facade applicative.

    Lecture seule : n'ecrit rien, ne passe jamais par
    :class:`~supplyscore.services.mutations.MutationService`.

    Args:
        service: facade applicative (depot de graphe en memoire, registre).
        node_id: identifiant du noeud.

    Returns:
        Le :class:`ContexteAction` du noeud.

    Raises:
        KeyError: si le noeud est inconnu du depot en memoire.
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


# State de rollout (Monte Carlo contrefactuel, worker U9)

#: State de rollout - dictionnaire a 4 cles, cf. docstring de module.
RolloutState = dict[str, Any]


def _clone_state(state: RolloutState) -> RolloutState:
    """Copie superficielle du state (nouveau dict de premier niveau).

    Chaque fonction ``apply_to_rollout`` qui modifie une cle imbriquee
    (``deadlines_h``, ``arc_beta``, ``ur_local``, ``hazard``) construit un
    NOUVEL objet pour cette cle plutot que de muter l'existant - c'est cette
    discipline, combinee a cette copie superficielle, qui garantit la purete
    (``state`` en entree n'est jamais modifie).
    """
    return dict(state)


# Cout structure


class CoutAction(TypedDict):
    """Cout structure d'une action corrective (contrat gele no 8).

    Attributes:
        monetaire: intervalle ``(lo, hi)`` en euros, ou None si a chiffrer
            par projet (cout trop dependant du contexte pour un defaut generique).
        temps_h: charge humaine en heures, ou None si sans objet.
        penalite_client_evitee: intervalle ``(lo, hi)`` de penalite
            contractuelle evitee, ou None si sans objet.
        mobilisation: description qualitative des equipes/ressources mobilisees.
        p_echec_execution_defaut: probabilite d'echec d'execution par
            defaut, dans [0, 1] (cf. :func:`_validate_catalogue`).
    """

    monetaire: tuple[float, float] | None
    temps_h: float | None
    penalite_client_evitee: tuple[float, float] | None
    mobilisation: str
    p_echec_execution_defaut: float


# Contrat ActionSpec (no 8)


@dataclass(frozen=True)
class ActionSpec:
    """Action corrective candidate : effet simule ET effet reel de meme semantique.

    Attributes:
        id: identifiant unique (cle de :data:`CATALOGUE_V1`).
        libelle: libelle d'affichage en francais.
        preconditions: ``ctx -> bool`` - l'action est-elle applicable au noeud ?
        apply_to_rollout: ``state -> state`` - application SIMULEE, PURE
            (cf. :data:`RolloutState`).
        apply_to_project: ``(service, node_id) -> None`` - application
            REELLE, via :class:`~supplyscore.services.mutations.MutationService`
            uniquement.
        delai_effet_weeks: ``(min, mode, max)`` - delai avant effet complet,
            en semaines (distribution triangulaire), ``min <= mode <= max``.
        cout: cout structure (cf. :class:`CoutAction`).
        risque_secondaire: description francaise du risque secondaire de
            l'action (ce qu'elle peut degrader ailleurs).
        incompatibles: ids d'actions ne pouvant pas etre combinees avec
            celle-ci dans le meme plan d'intervention (doivent exister dans
            :data:`CATALOGUE_V1`).
        objectifs_operationnels: sous-ensemble de :data:`OBJECTIFS_OPERATIONNELS`
            vise par l'action.
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


# promouvoir_arc_secours


def _precondition_promouvoir_arc_secours(ctx: ContexteAction) -> bool:
    """Vrai si au moins un arc de secours alimente le noeud."""
    return bool(ctx.arcs_backup)


def _apply_project_promouvoir_arc_secours(service: SupplyScoreService, node_id: str) -> None:
    """Promeut l'arc de secours entrant prioritaire en arc nominal.

    Selectionne, parmi les arcs BACKUP entrants du noeud, celui de
    ``source_id`` le plus petit (ordre lexicographique - regle de departage
    deterministe et documentee, utile quand plusieurs arcs de secours
    existent) et le fait basculer en
    :attr:`~supplyscore.domain.models.ArcKind.NOMINAL` via
    :meth:`~supplyscore.services.mutations.MutationService.upsert_arc`.
    No-op silencieux si le noeud n'a aucun arc de secours entrant (la
    precondition n'est pas reverifiee ici - un appel direct reste possible).

    Raises:
        KeyError: si le noeud est inconnu du depot en memoire.
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

    Ajoute le beta de l'arc de secours (cle ``f"{arc_id}:backup"``) a la
    contribution nominale deja presente sous ``arc_id`` (0.0 si absente) et
    retire l'entree ``:backup`` - traduction, cote rollout, d'une dependance
    desormais repartie sur un second fournisseur actif. S'il y a plusieurs
    entrees ``:backup`` en attente, celle de plus petite ``source_id`` est
    choisie - MEME regle de departage que cote reel
    (:func:`_apply_project_promouvoir_arc_secours`), pour que les deux
    applications promeuvent toujours le meme arc. No-op (copie inchangee)
    si aucune entree ``:backup`` n'est presente.
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


# replanifier_jalon


def _precondition_replanifier_jalon(ctx: ContexteAction) -> bool:
    """Vrai si un jalon ACTIVE existe pour le noeud."""
    return next_active_milestone(ctx.milestones) is not None


def _apply_project_replanifier_jalon(service: SupplyScoreService, node_id: str) -> None:
    """Decale de 2 semaines la deadline du prochain jalon actif (regle section 6.3).

    Regle " revue de programme " du protocole HELIOS section 6.3 : seule
    ``deadline_ts`` est decalee, ``start_ts`` reste inchange (le jalon est
    deja en cours) - l'invariant ``start_ts < deadline_ts`` de
    :meth:`~supplyscore.services.mutations.MutationService.update_milestone`
    reste donc trivialement respecte. No-op si le noeud n'a aucun jalon actif.

    Raises:
        KeyError: si le noeud est inconnu du depot en memoire.
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
    """Decale de 2 semaines (336 h) l'echeance la plus proche de ``deadlines_h``.

    Meme regle de selection que cote reel
    (:func:`_apply_project_replanifier_jalon`, via
    :func:`~supplyscore.domain.milestones.next_active_milestone`) : seule
    l'entree de valeur MINIMALE (l'echeance la plus proche) est decalee, les
    autres restent inchangees. No-op si ``deadlines_h`` est vide.
    """
    new_state = _clone_state(state)
    deadlines = dict(state.get("deadlines_h", {}))
    if deadlines:
        nearest_key = min(deadlines, key=lambda key: deadlines[key])
        deadlines[nearest_key] = deadlines[nearest_key] + _DEUX_SEMAINES_H
    new_state["deadlines_h"] = deadlines
    return new_state


# expedition_express


def _precondition_expedition_express(ctx: ContexteAction) -> bool:
    """Toujours applicable (aucune precondition metier au-dela du noeud existant)."""
    return True


def _apply_project_expedition_express(service: SupplyScoreService, node_id: str) -> None:
    """Reduit le lead time du noeud de 30 % (facteur documente :data:`_FACTEUR_EXPRESS`).

    No-op si ``time.lead_time_h`` n'est pas renseigne (rien a accelerer).

    Raises:
        KeyError: si le noeud est inconnu du depot en memoire.
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
    """Reduit de 30 % la trajectoire d'urgence locale ``ur_local`` (meme facteur que le KPI).

    Simplification documentee : le contrat de rollout n'expose pas le bloc
    temporel isolement - la reduction du lead time est donc reportee sur la
    trajectoire agregee ``ur_local``, DANS LA MEME PROPORTION que la
    reduction reelle du KPI. C'est ce qui rend le test d'equivalence
    sim/reel exact (meme variation relative des deux cotes).
    """
    new_state = _clone_state(state)
    new_state["ur_local"] = state["ur_local"] * _FACTEUR_EXPRESS
    return new_state


# boost_capacite


def _precondition_boost_capacite(ctx: ContexteAction) -> bool:
    """Applicable si au moins un KPI de capacite/debit est renseigne."""
    inv = ctx.node.kpis.inventory
    return inv.flow_rate is not None or inv.max_volume_m3 is not None


def _apply_project_boost_capacite(service: SupplyScoreService, node_id: str) -> None:
    """Augmente le debit (+30 %) et/ou le volume max (+20 %) du noeud, si renseignes.

    Les deux KPIs sont independants : seuls ceux effectivement renseignes
    sont modifies (no-op complet si ni l'un ni l'autre ne l'est).

    Raises:
        KeyError: si le noeud est inconnu du depot en memoire.
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
    """Reduit de 25 % la trajectoire de hazard (rupture/stock) du noeud.

    Simplification documentee : un debit/volume accru reduit le risque de
    rupture plutot que l'urgence temporelle - traduit ici par un
    amortissement de la trajectoire ``hazard``, distincte de ``ur_local``
    (utilisee par :func:`_apply_rollout_expedition_express`).
    """
    new_state = _clone_state(state)
    new_state["hazard"] = state["hazard"] * _FACTEUR_HAZARD_CAPACITE
    return new_state


# revue_declaration


def _precondition_revue_declaration(ctx: ContexteAction) -> bool:
    """Applicable si une urgence declaree (Ud local) existe deja pour le noeud."""
    return ctx.urgency.ud_local is not None


def _apply_project_revue_declaration(service: SupplyScoreService, node_id: str) -> None:
    """No-op cote ecriture : declenche une demande de reevaluation (couche insight).

    Aucun KPI n'est modifie - seule la couche d'explicabilite/insight (hors
    perimetre de ce module) consomme le declenchement de cette action pour
    solliciter un nouveau questionnaire AHP aupres de l'operateur terrain.
    """
    return None


def _apply_rollout_revue_declaration(state: RolloutState) -> RolloutState:
    """Identite : la revision de la declaration n'a pas d'effet simulable direct."""
    return _clone_state(state)


# ne_rien_faire (bras de reference)


def _precondition_ne_rien_faire(ctx: ContexteAction) -> bool:
    """Toujours applicable - bras de reference (baseline) du catalogue."""
    return True


def _apply_project_ne_rien_faire(service: SupplyScoreService, node_id: str) -> None:
    """No-op total : aucune ecriture, par definition du bras de reference."""
    return None


def _apply_rollout_ne_rien_faire(state: RolloutState) -> RolloutState:
    """Identite stricte : retourne une copie inchangee du state."""
    return _clone_state(state)


# Catalogue V1


def _validate_catalogue(catalogue: dict[str, ActionSpec]) -> None:
    """Valide les invariants d'integrite du catalogue.

    Raises:
        ValueError: id incoherent avec sa cle, ``incompatibles`` referencant
            un id absent du catalogue ou non symetrique,
            ``p_echec_execution_defaut`` hors [0, 1], ou
            ``delai_effet_weeks`` non croissant (``min <= mode <= max``) -
            un seul message, toutes les erreurs listees.
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


#: Catalogue V1 - 6 actions correctives (contrat gele no 8).
CATALOGUE_V1: dict[str, ActionSpec] = {
    "promouvoir_arc_secours": ActionSpec(
        id="promouvoir_arc_secours",
        libelle="Promouvoir un arc de secours en arc nominal",
        preconditions=_precondition_promouvoir_arc_secours,
        apply_to_rollout=_apply_rollout_promouvoir_arc_secours,
        apply_to_project=_apply_project_promouvoir_arc_secours,
        delai_effet_weeks=(0.5, 1.0, 2.0),
        cout=CoutAction(
            monetaire=None,  # a chiffrer par projet (requalification fournisseur)
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
