"""Moteur d'explicabilite - " pourquoi A = 32 " (phase E8, Lot 8.1).

Decompositions EXACTES des quatre etages du pipeline SupplyScore :

- **Ud (AHP)** : Ud = Sigma_j w_j-(s_j - 1)/8 est additive - la contribution
  kappa_j = w_j-(s_j - 1)/8 du critere j verifie Sigmakappa_j = Ud exactement ;
- **Ur_local (blocs KPI)** : Ur = 1 - Pi_m (1 - u_m)^omega_m n'est pas additive
  dans l'espace des urgences, mais l'est dans l'espace log-survie : en
  posant l_m = -omega_m-ln(1 - u_m) >= 0, Ur = 1 - exp(-Sigma l_m) et la part
  exacte du bloc m est l_m / Sigma l (somme 1 sur les blocs actifs) ;
- **propagation** : Ur_i = 1 - (1 - Ur_loc)-Pi_j (1 - beta_ji-Ur_j) a la meme
  structure produit -> memes parts log-survie (une part locale plus une
  part par fournisseur, somme 1) ; symetrique pour Ud descendant avec
  gamma_ik-Ud_k (quels clients tirent le besoin) ;
- **adequation** : pas de decomposition additive - l'equation est
  instanciee chiffree (e_under, e_over, penalty) telle que la calcule
  :class:`AdequationEngine`.

Regle de defendabilite : ce module APPELLE les memes fonctions que le
pipeline (:meth:`UrModel.blocks`, :meth:`UrModel.ur_local`,
:func:`compute_ud`, :meth:`AdequationEngine.adequation_asym`,
:mod:`supplyscore.core.status_rules`) au lieu de recopier les formules ;
la reconstruction ``1 - exp(-Sigma l)`` coincide avec ``ur_local()`` a 1e-12
pres. Les statuts DONE et ABANDONED court-circuitent Ur_local EN AMONT
(status_rules : DONE -> 0.0, ABANDONED -> 1.0) : la decomposition par blocs
ne s'applique donc qu'aux noeuds ACTIVE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from supplyscore.core.adequation import AdequationEngine
from supplyscore.core.ahp import CRITERIA, compute_ud
from supplyscore.core.status_rules import effective_ud_local, effective_ur_local
from supplyscore.core.ur_model import BLOCKS, UrModel, _clip01
from supplyscore.domain.milestones import Milestone, next_active_milestone, theoretical_progress
from supplyscore.domain.models import ArcKind, KPIBundle, SupplyArc, SupplyNode

#: Seuil de saturation : u >= 1 - epsilon => facteur de survie nul (part forcee).
_EPS_SAT: float = 1e-9


# Structures de resultat


@dataclass(frozen=True)
class BlockContribution:
    """Contribution d'un bloc KPI a l'urgence reelle locale Ur.

    Attributes:
        block: nom du bloc (cf. :data:`supplyscore.core.ur_model.BLOCKS`).
        u: urgence partielle u_m du bloc, ou None si non calculable.
        omega: poids d'agregation effectif omega_m du bloc.
        share: part EXACTE l_m/Sigmal en log-survie (somme 1 sur les blocs
            actifs ; 0 pour les blocs inactifs ; cas satures et tout-nuls
            traites, cf. :func:`explain_ur_local`).
        delta_without: contribution marginale Ur - Ur_sans_m (" sans ce
            bloc, Ur vaudrait... ") - intuitive mais NON additive :
            Sigma delta_without != Ur en general.
    """

    block: str
    u: float | None
    omega: float
    share: float
    delta_without: float


@dataclass(frozen=True)
class CriterionContribution:
    """Contribution additive exacte d'un critere AHP a Ud.

    Attributes:
        index: indice du critere (ordre de :data:`supplyscore.core.ahp.CRITERIA`).
        label: libelle du critere.
        weight: poids AHP normalise w_j (Sigma w = 1, comme dans ``compute_ud``).
        score: note s_j du critere sur l'echelle de Saaty [1, 9].
        contribution: kappa_j = w_j-(s_j - 1)/8 - additive : Sigma kappa_j = Ud
            exactement (a l'associativite flottante pres, < 1e-12).
    """

    index: int
    label: str
    weight: float
    score: float
    contribution: float


@dataclass(frozen=True)
class EdgeContribution:
    """Contribution d'un voisin (fournisseur ou client) a l'urgence propagee.

    Attributes:
        neighbor_id: identifiant du noeud voisin.
        neighbor_name: nom lisible du noeud voisin.
        coeff: coefficient de l'arc (beta_ji en montant, gamma_ik en descendant).
        u_neighbor: urgence propagee du voisin utilisee par le pipeline
            (Ur_j en montant, Ud_k en descendant).
        share: part log-survie de ce voisin (part locale + Sigma parts = 1).
    """

    neighbor_id: str
    neighbor_name: str
    coeff: float
    u_neighbor: float
    share: float


@dataclass(frozen=True)
class AdequationTrace:
    """Equation d'adequation instanciee chiffree (pas de decomposition additive).

    Attributes:
        e_under: sous-estimation [Ur - Ud]+ (risque cache).
        e_over: surestimation [Ud - Ur]+ (fausse urgence).
        penalty: penalite lambda_under-e_under^alpha + lambda_over-e_over^alpha.
        adequation: score A  dans  [0, 100] tel que rendu par
            :meth:`AdequationEngine.adequation_asym` (meme appel).
        lambda_under: penalite de sous-estimation du moteur.
        lambda_over: penalite de surestimation du moteur.
        alpha: courbure psychophysique du moteur.
    """

    e_under: float
    e_over: float
    penalty: float
    adequation: float
    lambda_under: float
    lambda_over: float
    alpha: float


@dataclass(frozen=True)
class UTimeTrace:
    """Trace lisible de la modulation planning de u_time v2.

    Attributes:
        u_base: socle probabiliste. En v1, P(L > d - t). En v2,
            P(L_restant + retard_choc > d* - t) - il AGREGE donc le cycle
            restant et le temps perdu ; ``retard_choc_h`` isole le second
            terme pour que la trace montre la meme decomposition que le
            calcul. None si v1 sans KPIs suffisants, ou retard avere.
        retard_choc_h: temps de production perdu et non rattrape
            (``time.delay_h``, heures) entre dans u_base ; 0.0 hors v2 ou sans
            choc en cours.
        p_th: avancement theorique du jalon actif M*, ou None hors v2.
        progress: avancement declare du jalon actif, ou None hors v2.
        planning_adjust: kappa_r-[r]+ - kappa_a-[-r]+ avec r = p_th - progress
            (0.0 si pas de jalon actif ou retard avere).
        final: u_time rendu par le pipeline - en v2 hors retard avere,
            final = clip01(u_base + planning_adjust).
    """

    u_base: float | None
    p_th: float | None
    progress: float | None
    planning_adjust: float
    final: float | None
    retard_choc_h: float = 0.0


# Aides log-survie


def _log_survival(u: float, omega: float) -> float:
    """Log-survie ponderee l = -omega-ln(1 - clip01(u)) d'un facteur d'urgence.

    Args:
        u: urgence du facteur (clipee sur [0, 1] comme dans ``ur_local``).
        omega: poids d'agregation omega >= 0 du facteur.

    Returns:
        l >= 0 ; ``math.inf`` si le facteur est sature (u >= 1).
    """
    survival = 1.0 - _clip01(u)
    if survival <= 0.0:
        return math.inf
    return -omega * math.log(survival)


def _local_and_edge_shares(u_local: float, terms: list[float]) -> tuple[float, list[float]]:
    """Parts log-survie (part locale, parts des arcs) d'un produit de survie.

    Cas limites, par priorite :

    - u_local >= 1 - epsilon (retard avere ou ABANDONED) -> part locale 1.0, arcs
      a 0 : la cause locale est unique, pas de calcul de parts ;
    - sinon, termes d'arc satures -> ils se partagent 1 a parts egales ;
    - Sigma l = 0 (aucune urgence nulle part) -> toutes les parts a 0.

    Args:
        u_local: urgence locale effective du noeud.
        terms: termes d'arc coeff-u_voisin, dans l'ordre des voisins.

    Returns:
        Tuple ``(part_locale, parts_par_arc)`` ; part_locale + Sigma parts = 1
        sauf dans le cas tout-nul ou tout vaut 0.
    """
    if _clip01(u_local) >= 1.0 - _EPS_SAT:
        return 1.0, [0.0] * len(terms)
    saturated = [_clip01(term) >= 1.0 - _EPS_SAT for term in terms]
    if any(saturated):
        n_sat = sum(saturated)
        return 0.0, [1.0 / n_sat if sat else 0.0 for sat in saturated]
    ell_loc = _log_survival(u_local, 1.0)
    ells = [_log_survival(term, 1.0) for term in terms]
    total = ell_loc + sum(ells)
    if total <= 0.0:
        return 0.0, [0.0] * len(ells)
    return ell_loc / total, [ell / total for ell in ells]


# Decompositions


def explain_ud(weights: np.ndarray, scores: np.ndarray) -> list[CriterionContribution]:
    """Decomposition additive exacte de Ud par critere AHP.

    Ud = Sigma_j w_j-(s_j - 1)/8 => kappa_j = w_j-(s_j - 1)/8 et Sigma kappa_j = Ud
    exactement. La validation et la renormalisation defensive des poids
    sont deleguees a :func:`supplyscore.core.ahp.compute_ud` (meme appel
    que le pipeline). Les libelles proviennent de :data:`CRITERIA`.

    Args:
        weights: poids AHP (renormalises defensivement a somme 1).
        scores: notes par critere sur l'echelle de Saaty [1, 9].

    Returns:
        Une contribution par critere, dans l'ordre des indices.

    Raises:
        ValueError: si les longueurs different ou si une note sort de
            [1, 9] (memes regles que ``compute_ud``).
    """
    compute_ud(weights, scores)  # Validation du pipeline (dimensions, bornes).
    w = np.asarray(weights, dtype=float)
    s = np.asarray(scores, dtype=float)
    w = w / w.sum()
    contributions: list[CriterionContribution] = []
    for j in range(w.shape[0]):
        label = CRITERIA[j] if j < len(CRITERIA) else f"Critère {j + 1}"
        contributions.append(
            CriterionContribution(
                index=j,
                label=label,
                weight=float(w[j]),
                score=float(s[j]),
                contribution=float(w[j]) * (float(s[j]) - 1.0) / 8.0,
            )
        )
    return contributions


def explain_ur_local(
    t: float,
    kpis: KPIBundle,
    milestones: list[Milestone] | None,
    model: UrModel,
    t0_ts: float = 0.0,
) -> list[BlockContribution]:
    """Decomposition de Ur_local par bloc KPI, en parts log-survie exactes.

    Les blocs sont calcules par :meth:`UrModel.blocks` (meme appel que le
    pipeline). Pour chaque bloc actif (u_m non-None et omega_m > 0) on pose
    l_m = -omega_m-ln(1 - u_m) ; alors Ur = 1 - exp(-Sigma l) coincide avec
    :meth:`UrModel.ur_local` a 1e-12 pres et la part exacte du bloc est
    share = l_m / Sigma l (somme 1, additive dans l'espace log-survie).

    Cas limites :

    - bloc sature (u_m >= 1 - epsilon, epsilon = 1e-9) : l = ? - les blocs satures se
      partagent share = 1 a parts egales, les autres recoivent 0 ;
    - Sigma l = 0 (tous les u actifs nuls) : toutes les parts valent 0 ;
    - bloc inactif (u_m None ou omega_m = 0) : share = 0, delta_without = 0.

    ``delta_without`` est la contribution marginale Ur - Ur_sans_m, ou
    Ur_sans_m est ``ur_local`` recalcule avec omega_m = 0 (meme appel que le
    pipeline) : intuitive (" sans ce bloc, Ur vaudrait... ") mais NON
    additive - Sigma delta_without != Ur en general.

    La decomposition vaut pour un noeud ACTIVE : les statuts DONE (Ur -> 0)
    et ABANDONED (Ur -> 1) court-circuitent ``ur_local`` en amont via
    :mod:`supplyscore.core.status_rules`, sans passer par les blocs.

    Args:
        t: date courante (heures depuis t0 projet).
        kpis: bundle KPI du noeud.
        milestones: jalons du noeud, propages au bloc ``time`` (u_time v2).
        model: modele Ur du pipeline (poids omega, gains kappa).
        t0_ts: origine du referentiel projet (epoch s).

    Returns:
        Une contribution par bloc, dans l'ordre de :data:`BLOCKS`.
    """
    blocks = model.blocks(t, kpis, milestones=milestones, t0_ts=t0_ts)
    ur_full = model.ur_local(t, kpis, milestones=milestones, t0_ts=t0_ts)
    omegas = {name: model.omega.get(name, 1.0) for name in BLOCKS}

    ells: dict[str, float] = {}
    saturated: list[str] = []
    for name in BLOCKS:
        u = blocks[name]
        if u is None or omegas[name] <= 0.0:
            continue
        ells[name] = _log_survival(u, omegas[name])
        if _clip01(u) >= 1.0 - _EPS_SAT:
            saturated.append(name)

    shares: dict[str, float] = dict.fromkeys(BLOCKS, 0.0)
    if saturated:
        for name in saturated:
            shares[name] = 1.0 / len(saturated)
    else:
        total = sum(ells.values())
        if total > 0.0:
            for name, ell in ells.items():
                shares[name] = ell / total

    contributions: list[BlockContribution] = []
    for name in BLOCKS:
        if name in ells:
            model_without = replace(model, omega={**omegas, name: 0.0})
            ur_without = model_without.ur_local(t, kpis, milestones=milestones, t0_ts=t0_ts)
            delta = ur_full - ur_without
        else:
            delta = 0.0
        contributions.append(
            BlockContribution(
                block=name,
                u=blocks[name],
                omega=omegas[name],
                share=shares[name],
                delta_without=delta,
            )
        )
    return contributions


def explain_u_time(
    t: float,
    kpis: KPIBundle,
    milestones: list[Milestone] | None,
    model: UrModel,
    t0_ts: float = 0.0,
) -> UTimeTrace:
    """Trace de u_time : socle probabiliste et modulation planning isoles.

    ``final`` est TOUJOURS le resultat de :meth:`UrModel.u_time` (meme
    appel que le pipeline). Trois regimes :

    - **v1** (pas de jalon actif) : pas de modulation - u_base = final,
      p_th = progress = None, planning_adjust = 0.0 ;
    - **v2, retard avere** (t > d*) : u_time est force a 1.0, cause
      unique - pas de decomposition (u_base = p_th = None,
      planning_adjust = 0.0) ;
    - **v2 nominal** : u_base = P(L_restant + retard_choc > d* - t) via
      :meth:`~supplyscore.core.ur_model.UrModel.u_base_jalon` - socle porte
      par le travail restant ET le temps perdu, ce dernier repris tel quel
      dans ``retard_choc_h`` pour rester lisible. Sans lead time le socle
      vaut 0.0, SAUF si le temps perdu excede a lui seul la marge, auquel
      cas il vaut 1.0. p_th est l'avancement theorique,
      planning_adjust = kappa_r-[r]+ - kappa_a-[-r]+ avec r = p_th - progress, et
      final = clip01(u_base + planning_adjust) a 1e-12 pres.

    Args:
        t: date courante (heures depuis t0 projet).
        kpis: bundle KPI du noeud (bloc ``time``).
        milestones: jalons du noeud ; None ou sans jalon ACTIVE -> v1.
        model: modele Ur du pipeline (gains kappa_retard / kappa_avance).
        t0_ts: origine du referentiel projet (epoch s).

    Returns:
        :class:`UTimeTrace` coherente avec le pipeline.
    """
    final = model.u_time(t, kpis, milestones=milestones, t0_ts=t0_ts)
    m_star = next_active_milestone(milestones) if milestones else None
    if m_star is None:
        # v1 : pas de modulation planning, le socle EST le resultat.
        return UTimeTrace(u_base=final, p_th=None, progress=None, planning_adjust=0.0, final=final)
    d_star = (m_star.deadline_ts - t0_ts) / 3600.0
    if t > d_star:
        # Retard avere : u_time force a 1.0, cause unique, pas de parts.
        return UTimeTrace(
            u_base=None, p_th=None, progress=m_star.progress, planning_adjust=0.0, final=final
        )
    tk = kpis.time
    retard = max(tk.delay_h or 0.0, 0.0)
    # Meme appel que UrModel.u_time (coherence structurelle, pas de duplication).
    u_base = model.u_base_jalon(d_star - t, tk, m_star.progress, retard)
    p_th = theoretical_progress(m_star, t0_ts + t * 3600.0)
    r = p_th - m_star.progress
    adjust = model.kappa_retard * max(r, 0.0) - model.kappa_avance * max(-r, 0.0)
    return UTimeTrace(
        u_base=u_base,
        p_th=p_th,
        progress=m_star.progress,
        planning_adjust=adjust,
        final=final,
        retard_choc_h=retard,
    )


def explain_propagation_up(
    node: SupplyNode,
    predecessors: list[SupplyNode],
    arcs_by_source: dict[str, SupplyArc],
) -> tuple[float, list[EdgeContribution]]:
    """Decomposition de Ur propage : part locale vs parts des fournisseurs.

    Le pipeline calcule Ur_i = 1 - (1 - Ur_loc)-Pi_j (1 - beta_ji-Ur_j) ; en
    log-survie l_loc = -ln(1 - Ur_loc) et l_j = -ln(1 - beta_ji-Ur_j), d'ou
    part_locale = l_loc/Sigma et part_j = l_j/Sigma (somme 1). Ur_loc est
    l'urgence locale EFFECTIVE (:func:`effective_ur_local`, memes regles
    de statut que :class:`PropagationEngine`) et Ur_j l'urgence propagee
    du fournisseur (``urgency.ur``, None compte 0.0).

    Cas limites : Ur_loc >= 1 (retard avere ou ABANDONED) -> part locale
    1.0 et parts fournisseurs a 0 (cause locale unique) ; arcs de secours
    (BACKUP) exclus, inertes comme dans le pipeline ; tout nul -> toutes
    les parts a 0.

    Args:
        node: noeud explique (client des arcs).
        predecessors: fournisseurs directs du noeud (Ur deja propage).
        arcs_by_source: arcs entrants indexes par id de fournisseur.

    Returns:
        Tuple ``(part_locale, contributions fournisseurs)``.

    Raises:
        ValueError: si un arc manque ou ne relie pas le bon couple.
    """
    ur_loc = effective_ur_local(node.status, node.urgency.ur_local)
    selected: list[tuple[SupplyNode, SupplyArc, float]] = []
    for pred in predecessors:
        arc = arcs_by_source.get(pred.id)
        if arc is None:
            raise ValueError(f"Arc fournisseur manquant pour le voisin {pred.id!r}")
        if arc.source_id != pred.id or arc.target_id != node.id:
            raise ValueError(f"Arc incohérent {arc.id!r} pour {pred.id!r} -> {node.id!r}")
        if arc.kind_arc is ArcKind.BACKUP:
            continue  # Les arcs de secours sont inertes dans la propagation.
        u_j = pred.urgency.ur if pred.urgency.ur is not None else 0.0
        selected.append((pred, arc, u_j))

    terms = [arc.beta * u_j for _, arc, u_j in selected]
    part_locale, edge_shares = _local_and_edge_shares(ur_loc, terms)
    contributions = [
        EdgeContribution(
            neighbor_id=pred.id,
            neighbor_name=pred.name,
            coeff=arc.beta,
            u_neighbor=u_j,
            share=share,
        )
        for (pred, arc, u_j), share in zip(selected, edge_shares, strict=True)
    ]
    return part_locale, contributions


def explain_propagation_down(
    node: SupplyNode,
    successors: list[SupplyNode],
    arcs_by_target: dict[str, SupplyArc],
) -> tuple[float, list[EdgeContribution]]:
    """Decomposition de Ud propage : part locale vs parts des clients.

    Symetrique de :func:`explain_propagation_up` pour la propagation
    descendante Ud_i = 1 - (1 - Ud_loc)-Pi_k (1 - gamma_ik-Ud_k) : quels
    CLIENTS tirent le besoin declare. Ud_loc est l'urgence declaree
    effective (:func:`effective_ud_local`) et Ud_k l'urgence propagee du
    client (``urgency.ud``, None compte 0.0). Memes cas limites (Ud_loc
    sature -> part locale 1.0 ; arcs BACKUP exclus ; tout nul -> parts 0).

    Args:
        node: noeud explique (fournisseur des arcs).
        successors: clients directs du noeud (Ud deja propage).
        arcs_by_target: arcs sortants indexes par id de client.

    Returns:
        Tuple ``(part_locale, contributions clients)``.

    Raises:
        ValueError: si un arc manque ou ne relie pas le bon couple.
    """
    ud_loc = effective_ud_local(node.status, node.urgency.ud_local)
    selected: list[tuple[SupplyNode, SupplyArc, float]] = []
    for succ in successors:
        arc = arcs_by_target.get(succ.id)
        if arc is None:
            raise ValueError(f"Arc client manquant pour le voisin {succ.id!r}")
        if arc.source_id != node.id or arc.target_id != succ.id:
            raise ValueError(f"Arc incohérent {arc.id!r} pour {node.id!r} -> {succ.id!r}")
        if arc.kind_arc is ArcKind.BACKUP:
            continue  # Les arcs de secours sont inertes dans la propagation.
        u_k = succ.urgency.ud if succ.urgency.ud is not None else 0.0
        selected.append((succ, arc, u_k))

    terms = [arc.gamma * u_k for _, arc, u_k in selected]
    part_locale, edge_shares = _local_and_edge_shares(ud_loc, terms)
    contributions = [
        EdgeContribution(
            neighbor_id=succ.id,
            neighbor_name=succ.name,
            coeff=arc.gamma,
            u_neighbor=u_k,
            share=share,
        )
        for (succ, arc, u_k), share in zip(selected, edge_shares, strict=True)
    ]
    return part_locale, contributions


def explain_adequation(ud: float, ur: float, engine: AdequationEngine) -> AdequationTrace:
    """Equation d'adequation instanciee chiffree pour un couple (Ud, Ur).

    e_under et e_over proviennent des MEMES appels que le pipeline
    (:meth:`AdequationEngine.hidden_risk` / :meth:`false_urgency`), le
    score de :meth:`AdequationEngine.adequation_asym` ; la penalite est
    instanciee avec les parametres du moteur :
    penalty = lambda_under-e_under^alpha + lambda_over-e_over^alpha.

    Args:
        ud: urgence declaree  dans  [0, 1].
        ur: urgence reelle (>= 0, peut depasser 1 si retard).
        engine: moteur d'adequation du pipeline (lambda, alpha).

    Returns:
        :class:`AdequationTrace` chiffree, coherente avec le moteur.
    """
    e_under = engine.hidden_risk(ud, ur)
    e_over = engine.false_urgency(ud, ur)
    penalty = (
        engine.lambda_under * e_under**engine.alpha + engine.lambda_over * e_over**engine.alpha
    )
    return AdequationTrace(
        e_under=e_under,
        e_over=e_over,
        penalty=penalty,
        adequation=engine.adequation_asym(ud, ur),
        lambda_under=engine.lambda_under,
        lambda_over=engine.lambda_over,
        alpha=engine.alpha,
    )
