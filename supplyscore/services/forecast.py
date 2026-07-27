"""Prévision par rollouts Monte Carlo et contrefactuels appariés (HÉLIOS v7 — unité U9).

:class:`ForecastService` projette chaque nœud ACTIF d'un projet sur un horizon de
1 à 4 semaines à partir de son PROPRE historique hebdomadaire (états d'urgence
persistés), puis chiffre l'effet d'une action corrective par tirages communs
appariés (CRN — contrat 12 figé du plan).

Sortie estimée — ÉQUIVALENCE FIGÉE avec la calibration (Lot 11.1) : la
probabilité ``p_issue`` estime exactement l'« issue défavorable » de
:class:`~supplyscore.services.calibration.CalibrationService` — jalon RATÉ
(critère a) OU événement non annulé de gravité « critique »/« defaut »
(critère c, mêmes gravités — :data:`_GRAVITES_DEFAVORABLES` importée de la
calibration). Le critère (b) — nœud au statut abandonné — n'est pas simulé :
seuls les nœuds ACTIFS sont projetés, l'abandon étant une issue à anticiper,
pas un état d'entrée. ``p_issue`` est ainsi l'estimateur PROSPECTIF du taux
que la calibration mesure RÉTROSPECTIVEMENT.

Incertitude décomposée (décision D31 du plan) : Monte Carlo IMBRIQUÉ —
K = 20 tirages EXTERNES des paramètres (φ et σ de l'AR(1) via leurs
erreurs-types de moindres carrés, taux d'événement via son posterior Beta,
moments du lead time par bootstrap paramétrique) × ``n_draws/K`` trajectoires
INTERNES par tirage externe. La variance de ``p_issue`` est décomposée en
composante ``mc`` (intra-externe) et ``parametrique`` (inter-externes,
variance des moyennes externes) ; l'IC80 total, étiqueté par sa couverture
``("mc", "param")``, combine l'erreur-type MC de l'estimateur et la dispersion
paramétrique PLEINE de ``p_issue`` (l'incertitude porte sur p lui-même).

VOCABULAIRE (décision D18’ du plan) : les champs et docstrings de ce module
parlent d'« effet SELON LE MODÈLE » (``delta_u_sim``) — JAMAIS d'« effet
réel ». Les contrefactuels comparent deux branches SIMULÉES sur les mêmes
aléas ; rien ici n'est une mesure d'effet causal observé.

Service en LECTURE SEULE : aucune écriture en base, jamais.

Performance mesurée (``test_performance_chaine_20_noeuds``) : rollout S = 2000,
h = 4 puis rollout apparié complet (deux branches) sur une chaîne de 20 nœuds
en ~0,3 s au total sur le poste de référence — très largement sous la borne
de 60 s du plan.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

import numpy as np
from numpy.typing import NDArray

from supplyscore.core.clock import iso_week, project_hours
from supplyscore.core.status_rules import effective_ur_local
from supplyscore.domain.events import (
    _GRAVITE_ACCIDENT_SEVERITE,
    _GRAVITE_FINANCE_SEVERITE,
    N0_PSEUDO_OBSERVATIONS,
    WEEK_HOURS,
)
from supplyscore.domain.models import TaskStatus
from supplyscore.mc.lead_time import LoiLeadTime, SimulateurLeadTime, resoudre_loi, tirer_lead_times

# ``_GRAVITES_DEFAVORABLES`` est la définition CANONIQUE des gravités comptées
# comme issue défavorable (Lot 11.1) : réutilisée plutôt que dupliquée — même
# précédent que ``_lundi`` importé par calibration.py depuis weekly.py.
from supplyscore.services.calibration import _GRAVITES_DEFAVORABLES
from supplyscore.services.weekly import _lundi

if TYPE_CHECKING:
    from supplyscore.services.orchestrator import SupplyScoreService

_FloatArray = NDArray[np.float64]
_BoolArray = NDArray[np.bool_]

#: Nombre minimal de semaines d'historique hebdomadaire exigé par nœud actif.
MIN_HISTORY_WEEKS: int = 4

#: Tirages externes du Monte Carlo imbriqué (décision D31 du plan v7).
K_EXTERNES: int = 20

#: Borne haute du coefficient AR(1) (stationnarité stricte).
PHI_MAX: float = 0.98

#: Plancher de l'écart-type résiduel de l'AR(1).
SIGMA_MIN: float = 0.01

#: Moyenne du prior Beta du taux hebdomadaire d'événement défavorable (documenté :
#: de l'ordre d'un événement critique toutes les ~33 semaines a priori).
TAUX_PRIOR: float = 0.03

#: Seuil de ΔUr au rang 0 au-delà duquel un tirage compte comme « impact client ».
SEUIL_IMPACT_CLIENT: float = 0.2

#: Décroissance géométrique hebdomadaire du surcroît d'urgence d'un événement
#: (demi-vie d'une semaine — choix documenté : un incident critique domine
#: l'urgence locale la semaine où il survient puis s'estompe de moitié chaque
#: semaine, l'effet durable passant par la révision des KPIs, pas par ce bump).
_DECROISSANCE_HEBDO: float = 0.5

#: Sévérités simulées d'un événement défavorable, DÉRIVÉES d'EVENT_CALIBRATION :
#: les deux gravités comptées comme issue défavorable portent, dans la
#: calibration des événements, des sévérités forfaitaires de 0.9 (alerte
#: financière « defaut ») et 1.0 (accident « critique ») — la simulation tire
#: uniformément entre ces deux niveaux.
_SEVERITES_ADVERSES: tuple[float, float] = (
    _GRAVITE_FINANCE_SEVERITE["defaut"],
    _GRAVITE_ACCIDENT_SEVERITE["critique"],
)

#: Taille du bootstrap paramétrique des moments de lead time (convention N0 du
#: dépôt : l'incertitude des moments décroît en 1/√26 pseudo-observations).
_N_BOOT_MOMENTS: int = int(N0_PSEUDO_OBSERVATIONS)

#: Répliques du bootstrap par blocs internes de l'IC80 MC des deltas appariés.
_N_BOOTSTRAP: int = 200

#: Quantile 0.9 de la N(0, 1) — IC bilatéral à 80 %.
_Z80: float = 1.2815515655446004

#: Variance de pente considérée nulle (série hebdomadaire constante).
_EPS_SXX: float = 1e-12


class ActionRollout(Protocol):
    """Contrat DUCK-TYPÉ d'une action prescriptible (contrat 8 du plan v7).

    Le catalogue réel des actions est construit par l'unité U15 — ce module
    n'en importe rien : toute valeur exposant les deux membres ci-dessous est
    acceptée par :meth:`ForecastService.rollout_with_action`.

    Attributes:
        delai_effet_weeks: triplet ``(min, mode, max)`` en semaines de la loi
            triangulaire du délai d'effet, avec ``0 <= min <= mode <= max``.
    """

    delai_effet_weeks: tuple[float, float, float]

    def apply_to_rollout(self, state: dict[str, Any]) -> dict[str, Any]:
        """Transforme l'état de simulation (fonction PURE, sans effet de bord).

        L'état reçu — et le dict à retourner — porte EXACTEMENT les clés
        documentées dans :meth:`ForecastService.rollout_with_action`.

        Args:
            state: état de simulation courant (lecture seule).

        Returns:
            Un nouvel état portant les mêmes clés, valeurs transformées.
        """
        ...


# --- Résultats publics (dataclasses figées) -----------------------------------------


@dataclass(frozen=True)
class IntervalleConfiance:
    """Intervalle de confiance étiqueté par les sources d'incertitude couvertes.

    Attributes:
        bas: borne basse de l'intervalle.
        haut: borne haute de l'intervalle.
        couverture: sources couvertes — ``("mc", "param")`` pour l'IC80 total
            d'un rollout, ``("mc",)`` ou ``("param",)`` pour les IC des deltas.
    """

    bas: float
    haut: float
    couverture: tuple[str, ...]


@dataclass(frozen=True)
class DiagnosticAjustement:
    """Diagnostics d'ajustement d'un nœud (série hebdo → AR(1) + Beta + lead time).

    Attributes:
        node_id: identifiant du nœud ajusté.
        n_semaines: nombre de semaines d'historique hebdomadaire utilisées.
        phi: coefficient AR(1) ajusté, clipé dans [0, 0.98].
        se_phi: erreur-type de φ (moindres carrés ; 0.0 si série constante).
        sigma: écart-type résiduel ajusté, plancher 0.01.
        se_sigma: erreur-type de σ (approximation normale σ/√(2·ddl)).
        mu: moyenne de long terme de la récurrence (moyenne de la série —
            choix simple documenté, l'intercept exact divergerait pour φ → 1).
        ur_local_initial: dernier ur_local hebdomadaire observé (état initial).
        n_evenements: semaines d'historique ayant connu au moins un événement
            défavorable (non annulé, gravité « critique »/« defaut »).
        taux_evenement: moyenne a posteriori du taux hebdomadaire d'événement.
        alpha_post: paramètre α du posterior Beta du taux.
        beta_post: paramètre β du posterior Beta du taux.
        loi_lead_time: loi de lead time résolue (:func:`resoudre_loi`).
        deadline_h: échéance du prochain jalon ACTIF en heures-projet (sinon
            ``kpis.time.deadline_h``), None si le nœud n'a aucune échéance.
    """

    node_id: str
    n_semaines: int
    phi: float
    se_phi: float
    sigma: float
    se_sigma: float
    mu: float
    ur_local_initial: float
    n_evenements: int
    taux_evenement: float
    alpha_post: float
    beta_post: float
    loi_lead_time: LoiLeadTime
    deadline_h: float | None


@dataclass(frozen=True)
class PrevisionNoeud:
    """Prévision d'un nœud à un horizon donné (semaine k du rollout).

    Attributes:
        p_issue: probabilité estimée d'issue défavorable d'ici la semaine k
            (même composite que CalibrationService : jalon raté OU événement
            critique/défaut).
        se_mc: erreur-type Monte Carlo pure de l'estimateur, √(var_mc/n).
        var_mc: variance INTRA-externe moyenne de l'indicatrice (composante MC).
        var_param: variance INTER-externes des moyennes par tirage externe
            (composante paramétrique, ddof=1).
        ic80: IC80 total étiqueté ``("mc", "param")`` — p ± z₈₀·√(var_param +
            var_mc/n), borné dans [0, 1].
        spread: largeur de l'IC80 (``haut − bas``).
        p_jalon_rate: probabilité que le jalon (échéance) soit raté d'ici k.
        p_impact_client: P(ΔUr au rang 0 > 0.2) — propagation factuelle contre
            propagation où CE nœud est remplacé par son chemin sans événement
            (contrefactuel apparié par nœud, mêmes aléas).
    """

    p_issue: float
    se_mc: float
    var_mc: float
    var_param: float
    ic80: IntervalleConfiance
    spread: float
    p_jalon_rate: float
    p_impact_client: float


@dataclass(frozen=True)
class ForecastResult:
    """Résultat figé d'un rollout Monte Carlo (partie A — prévision seule).

    Attributes:
        project_id: projet simulé.
        horizon_weeks: horizon simulé, en semaines.
        n_draws: nombre EFFECTIF de trajectoires simulées (K·⌊n_draws/K⌋).
        n_outer: nombre de tirages externes K du Monte Carlo imbriqué.
        seed: graine du rollout (déterministe : même graine, mêmes résultats).
        previsions: par nœud simulé puis par horizon k ∈ 1..h, la
            :class:`PrevisionNoeud`.
        diagnostics: par nœud simulé, le :class:`DiagnosticAjustement`.
    """

    project_id: str
    horizon_weeks: int
    n_draws: int
    n_outer: int
    seed: int
    previsions: dict[str, dict[int, PrevisionNoeud]]
    diagnostics: dict[str, DiagnosticAjustement]


@dataclass(frozen=True)
class PrevisionAppariee:
    """Comparaison appariée SANS/AVEC action d'un nœud à un horizon donné.

    Tous les effets sont des effets SELON LE MODÈLE (décision D18’) : deux
    branches simulées sur des aléas identiques, jamais un effet réel mesuré.

    Attributes:
        p0: probabilité d'issue défavorable SANS action.
        p1: probabilité d'issue défavorable AVEC action.
        delta_u_sim: effet SELON LE MODÈLE — moyenne sur les tirages appariés
            de (issue sans action − issue avec action).
        ic80_delta_mc: IC80 de ``delta_u_sim`` par bootstrap par blocs internes
            (répliques intra-externes), couverture ``("mc",)``.
        ic80_delta_param: IC80 paramétrique — quantiles 10/90 des moyennes
            appariées par tirage externe, couverture ``("param",)``.
        p_delta_positif: fraction des tirages externes dont la moyenne appariée
            est strictement positive.
        p_impact_client_0: P(ΔUr au rang 0 > 0.2) dans la branche SANS action.
        p_impact_client_1: P(ΔUr au rang 0 > 0.2) dans la branche AVEC action.
    """

    p0: float
    p1: float
    delta_u_sim: float
    ic80_delta_mc: IntervalleConfiance
    ic80_delta_param: IntervalleConfiance
    p_delta_positif: float
    p_impact_client_0: float
    p_impact_client_1: float


@dataclass(frozen=True)
class PairedForecast:
    """Résultat figé d'un rollout contrefactuel apparié (partie B — contrat 12).

    Attributes:
        project_id: projet simulé.
        horizon_weeks: horizon simulé, en semaines.
        n_draws: nombre EFFECTIF de trajectoires par branche (K·⌊n_draws/K⌋).
        n_outer: nombre de tirages externes K du Monte Carlo imbriqué.
        seed: graine du rollout (déterministe : même graine, mêmes résultats).
        delai_effet_weeks: triplet (min, mode, max) validé du délai d'effet.
        previsions: par nœud simulé puis par horizon k ∈ 1..h, la
            :class:`PrevisionAppariee`.
    """

    project_id: str
    horizon_weeks: int
    n_draws: int
    n_outer: int
    seed: int
    delai_effet_weeks: tuple[float, float, float]
    previsions: dict[str, dict[int, PrevisionAppariee]]


def to_snapshot_block(result: ForecastResult) -> dict[str, dict[str, dict[str, dict[str, float]]]]:
    """Bloc « forecast » du snapshot hebdomadaire (contrat 7 FIGÉ du plan v7).

    Args:
        result: résultat d'un :meth:`ForecastService.rollout`.

    Returns:
        ``{node_id: {"forecast": {"1"…"4": {"p_issue", "se_mc", "spread",
        "p_jalon_rate", "p_impact_client"}}}}`` — les clés d'horizon sont les
        semaines simulées converties en chaînes.
    """
    bloc: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for node_id, par_horizon in result.previsions.items():
        bloc[node_id] = {
            "forecast": {
                str(k): {
                    "p_issue": prevision.p_issue,
                    "se_mc": prevision.se_mc,
                    "spread": prevision.spread,
                    "p_jalon_rate": prevision.p_jalon_rate,
                    "p_impact_client": prevision.p_impact_client,
                }
                for k, prevision in sorted(par_horizon.items())
            }
        }
    return bloc


# --- Structures internes ------------------------------------------------------------


@dataclass
class _Contexte:
    """Contexte figé d'un rollout : ajustements, graphe et temps du projet."""

    project_id: str
    horizon: int
    t_h: float
    ordre_all: list[str]
    position: dict[str, int]
    sim_ids: list[str]
    sim_index: dict[str, int]
    static_ur: dict[str, float]
    beta_base: dict[tuple[str, str], float]
    preds_base: dict[str, tuple[str, ...]]
    rank0_ids: list[str]
    deadlines: dict[str, float]
    x0: _FloatArray
    mu: _FloatArray
    phi_hat: _FloatArray
    se_phi: _FloatArray
    sigma_hat: _FloatArray
    se_sigma: _FloatArray
    alpha_post: _FloatArray
    beta_post: _FloatArray
    lois: list[LoiLeadTime]
    d0: _FloatArray
    diagnostics: dict[str, DiagnosticAjustement]


@dataclass
class _ParametresExternes:
    """Paramètres d'UN tirage externe (incertitude paramétrique, D31)."""

    phi: _FloatArray
    sigma: _FloatArray
    taux: _FloatArray
    lois: list[LoiLeadTime]


@dataclass
class _Tirages:
    """Aléas pré-tirés d'un tirage externe — consommés à l'identique par les deux branches (CRN)."""

    z: _FloatArray
    u_evt: _FloatArray
    u_sev: _FloatArray
    lead_times: _FloatArray
    delais: _FloatArray | None = None


@dataclass
class _EtatBranche:
    """État mutable d'une branche de simulation (matrices par tirage interne)."""

    x_ar: _FloatArray
    bump: _FloatArray
    hazard: _FloatArray
    deadlines: _FloatArray
    taux_base: _FloatArray
    betas: dict[tuple[str, str], float | _FloatArray]
    preds: dict[str, tuple[str, ...]]


@dataclass
class _SortieBranche:
    """Indicatrices (S, N, h) d'une branche : issue, jalon raté, impact client."""

    issue: _BoolArray
    jalon: _BoolArray
    impact: _BoolArray


@dataclass
class _Empile:
    """Sorties empilées (K, S, N, h) des K tirages externes d'une branche."""

    issue: _BoolArray
    jalon: _BoolArray
    impact: _BoolArray


# --- Aides pures --------------------------------------------------------------------


def _ajuster_ar1(valeurs: _FloatArray) -> tuple[float, float, float, float, float]:
    """Ajuste un AR(1) par moindres carrés sur une série hebdomadaire.

    Modèle simulé ensuite : ``x_{k} = mu + phi·(x_{k-1} − mu) + sigma·ε``. La
    pente OLS de ``x_{t+1}`` sur ``x_t`` fournit φ (clipé dans [0, 0.98]) et
    l'écart-type résiduel σ (plancher 0.01, appliqué AVANT les erreurs-types —
    choix conservateur). ``mu`` est la moyenne de la série. Série (quasi)
    constante : φ = 0 avec se(φ) = 0, résidus autour de la moyenne.

    Args:
        valeurs: série hebdomadaire des ur_local (taille >= MIN_HISTORY_WEEKS).

    Returns:
        Le quintuplet ``(phi, se_phi, sigma, se_sigma, mu)``.
    """
    x = valeurs[:-1]
    z = valeurs[1:]
    n = int(x.size)
    x_bar = float(x.mean())
    z_bar = float(z.mean())
    sxx = float(np.sum((x - x_bar) ** 2))
    mu = float(valeurs.mean())
    if sxx <= _EPS_SXX:
        residus = z - z_bar
        ddl = max(n - 1, 1)
        sigma = max(math.sqrt(float(np.sum(residus**2)) / ddl), SIGMA_MIN)
        return 0.0, 0.0, sigma, sigma / math.sqrt(2.0 * ddl), mu
    pente = float(np.sum((x - x_bar) * (z - z_bar))) / sxx
    intercept = z_bar - pente * x_bar
    residus = z - (intercept + pente * x)
    ddl = max(n - 2, 1)
    sigma = max(math.sqrt(float(np.sum(residus**2)) / ddl), SIGMA_MIN)
    se_phi = sigma / math.sqrt(sxx)
    se_sigma = sigma / math.sqrt(2.0 * ddl)
    phi = min(max(pente, 0.0), PHI_MAX)
    return phi, se_phi, sigma, se_sigma, mu


def _loi_externe(loi: LoiLeadTime, rng: np.random.Generator) -> LoiLeadTime:
    """Tirage externe de la loi de lead time : bootstrap paramétrique des moments.

    Familles lognormale/normale : :data:`_N_BOOT_MOMENTS` (26) tirages de la
    loi de base fournissent des moments empiriques (m*, s*) — l'incertitude
    des moments décroît en 1/√26, cohérente avec la convention de
    pseudo-observations du dépôt. Familles triangulaire/déterministe :
    conservées telles quelles (bornes de cahier des charges, aucune
    incertitude paramétrique estimable).

    Args:
        loi: loi de base résolue par :func:`resoudre_loi`.
        rng: générateur commun de la simulation.

    Returns:
        La loi perturbée du tirage externe.
    """
    if loi.famille not in ("lognormale", "normale"):
        return loi
    echantillon = tirer_lead_times(loi, rng, _N_BOOT_MOMENTS)
    m = float(echantillon.mean())
    s = float(echantillon.std(ddof=1))
    if m <= 0.0 or s <= 0.0:
        return LoiLeadTime("deterministe", m=max(m, 0.0))
    return LoiLeadTime(loi.famille, m=m, s=s)


def _tirer_delais(
    bornes: tuple[float, float, float], rng: np.random.Generator, n: int
) -> _FloatArray:
    """Tire les délais d'effet (semaines) — triangulaire, un délai par tirage.

    Args:
        bornes: triplet validé (min, mode, max), support éventuellement dégénéré.
        rng: générateur dédié aux aléas d'action.
        n: nombre de tirages internes.

    Returns:
        Tableau ``(n,)`` de délais en semaines.
    """
    minimum, mode, maximum = bornes
    if maximum == minimum:
        return np.full(n, mode, dtype=np.float64)
    return np.asarray(rng.triangular(minimum, mode, maximum, size=n), dtype=np.float64)


def _propager_ur_batch(
    ordre: list[str],
    ur_local: dict[str, float | _FloatArray],
    predecesseurs: dict[str, tuple[str, ...]],
    betas: dict[tuple[str, str], float | _FloatArray],
    n_lignes: int,
) -> dict[str, _FloatArray]:
    """Propagation montante Ur par lots — même récurrence que ``PropagationEngine._compute_ur``.

    OU-bruité en ordre topologique (fournisseurs profonds d'abord) sur des
    vecteurs ``(n_lignes,)`` : ``Ur_i = clip01(1 − (1 − Ur_loc_i) ·
    Π_j (1 − β_ji · Ur_j))``. Les β acceptent un scalaire ou un vecteur par
    ligne (actions actives sur une partie des tirages seulement).

    TODO : remplacer par ``PropagationEngine.compute_ur_batch`` (U3) après fusion.

    Args:
        ordre: ordre topologique complet du dépôt.
        ur_local: urgence locale par nœud — scalaire (nœud statique) ou
            vecteur ``(n_lignes,)`` (nœud simulé, variantes empilées).
        predecesseurs: fournisseurs directs par nœud (arcs nominaux + promus).
        betas: coefficient β par arc, scalaire ou vecteur ``(n_lignes,)``.
        n_lignes: nombre de lignes simulées (tirages × variantes).

    Returns:
        Ur propagé par nœud, vecteurs ``(n_lignes,)``.
    """
    ur: dict[str, _FloatArray] = {}
    for node_id in ordre:
        attenuation = np.ones(n_lignes, dtype=np.float64)
        for src in predecesseurs.get(node_id, ()):
            attenuation *= 1.0 - betas[(src, node_id)] * ur[src]
        loc = ur_local.get(node_id, 0.0)
        ur[node_id] = np.clip(1.0 - (1.0 - loc) * attenuation, 0.0, 1.0)
    return ur


# --- Service ------------------------------------------------------------------------


class ForecastService:
    """Rollouts Monte Carlo prospectifs et contrefactuels appariés d'un projet.

    S'appuie sur la façade :class:`SupplyScoreService` : le registre fournit
    projets et jalons, ``clock_for`` l'horloge effective du projet, le dépôt
    de graphe la topologie et les bases CLIENT l'historique d'urgence
    (``urgency_series``) et le journal d'événements (``list_events``).
    Service en LECTURE SEULE : rien n'est jamais écrit.

    Attributes:
        MIN_HISTORY_WEEKS: nombre minimal de semaines d'historique hebdomadaire
            exigé par nœud actif (alias de classe de la constante du module).
    """

    MIN_HISTORY_WEEKS: ClassVar[int] = MIN_HISTORY_WEEKS

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service de prévision au-dessus de la façade.

        Args:
            service: façade applicative (registre, bases client, horloges).
        """
        self._service = service

    # -- API publique -----------------------------------------------------------

    def rollout(
        self, project_id: str, horizon_weeks: int = 4, n_draws: int = 2000, seed: int = 0
    ) -> ForecastResult:
        """Rollout Monte Carlo du projet sur 1..``horizon_weeks`` semaines.

        Ajuste chaque nœud ACTIF sur son propre historique hebdomadaire
        (AR(1) sur ur_local, posterior Beta du taux d'événement défavorable,
        loi de lead time :func:`resoudre_loi`), puis simule K = 20 tirages
        externes de paramètres × ``n_draws/K`` trajectoires internes
        (décision D31). L'issue estimée est l'« issue défavorable » de
        CalibrationService : jalon raté d'ici k OU événement critique/défaut
        d'ici k — cf. la docstring du module pour l'équivalence figée.

        Args:
            project_id: projet à projeter.
            horizon_weeks: horizon en semaines (défaut 4).
            n_draws: budget total de trajectoires (arrondi à K·⌊n/K⌋).
            seed: graine du rollout — même graine, résultats identiques.

        Returns:
            Le :class:`ForecastResult` (prévisions par nœud × horizon,
            diagnostics d'ajustement).

        Raises:
            ValueError: horizon < 1, ``n_draws`` < K, projet inconnu, aucun
                nœud actif, ou historique hebdomadaire insuffisant
                (< :data:`MIN_HISTORY_WEEKS` semaines) sur un nœud actif —
                messages en français.
        """
        ctx = self._preparer(project_id, horizon_weeks, n_draws)
        brut0, _, _ = self._executer(ctx, n_draws, seed, action=None)
        previsions = self._agreger(ctx, brut0)
        return ForecastResult(
            project_id=project_id,
            horizon_weeks=ctx.horizon,
            n_draws=int(brut0.issue.shape[0] * brut0.issue.shape[1]),
            n_outer=K_EXTERNES,
            seed=seed,
            previsions=previsions,
            diagnostics=ctx.diagnostics,
        )

    def rollout_with_action(
        self,
        project_id: str,
        action: ActionRollout,
        horizon_weeks: int = 4,
        n_draws: int = 2000,
        seed: int = 0,
    ) -> PairedForecast:
        """Rollout contrefactuel apparié SANS/AVEC action (contrat 12 figé).

        TIRAGES COMMUNS (CRN) : les deux branches consomment EXACTEMENT les
        mêmes aléas pré-tirés (bruits AR, occurrences et sévérités
        d'événements, lead times) — la branche AVEC applique l'action à
        partir de sa semaine d'effet, tirée UNE fois par tirage interne dans
        la triangulaire ``action.delai_effet_weeks`` (un délai de d semaines
        laisse ⌊d⌋ semaine(s) pleine(s) sans effet ; l'action agit à partir
        de la semaine ⌊d⌋+1). Les délais sont tirés sur un flux aléatoire
        SÉPARÉ : la branche SANS action reproduit bit à bit
        :meth:`rollout` à graine égale.

        ÉTAT DE SIMULATION passé à ``action.apply_to_rollout(state)`` — appelée
        une fois par semaine comptant des tirages nouvellement actifs, sur des
        valeurs de BASE (jamais encore transformées pour ces tirages) :

        - ``"ur_local"`` : tableau ``(S, N)`` — urgence locale observable
          (événements inclus) par tirage interne × nœud simulé ;
        - ``"hazard"`` : tableau ``(N,)`` — taux hebdomadaire d'événement
          défavorable par nœud (le retour peut être ``(N,)`` ou ``(S, N)``) ;
        - ``"deadlines_h"`` : ``dict[node_id, float]`` — échéance en
          heures-projet des nœuds qui en ont une ;
        - ``"arc_beta"`` : ``dict[(source_id, target_id), float]`` — β des
          arcs nominaux de propagation ;
        - ``"node_ids"`` : tuple des ids des nœuds simulés — ORDRE DES
          COLONNES des tableaux ci-dessus (clé de lecture, à ne pas modifier).

        Le dict retourné doit porter les quatre premières clés ; leurs effets,
        pour les tirages nouvellement actifs, du début de leur semaine d'effet
        jusqu'à la fin de l'horizon :

        - réduire ``ur_local`` : l'écart (retour − état) est appliqué au cœur
          AR porté — il persiste ensuite via la récurrence ;
        - réduire ``hazard`` : le taux transformé pilote les occurrences ;
        - décaler une échéance : la valeur transformée pilote le test de
          jalon raté (clé ABSENTE du dict retourné = échéance neutralisée) ;
        - promouvoir un arc : clé AJOUTÉE à ``arc_beta`` (source avant cible
          dans l'ordre topologique, sinon ignorée) ; clé ABSENTE = arc
          neutralisé (β = 0) ; β bornés dans [0, 1].

        Tous les champs de sortie sont des effets SELON LE MODÈLE (décision
        D18’) : jamais un « effet réel ».

        Args:
            project_id: projet à projeter.
            action: action duck-typée (cf. :class:`ActionRollout`).
            horizon_weeks: horizon en semaines (défaut 4).
            n_draws: budget total de trajectoires PAR BRANCHE.
            seed: graine du rollout — même graine, résultats identiques.

        Returns:
            Le :class:`PairedForecast` (p0, p1, delta_u_sim et IC associés).

        Raises:
            ValueError: mêmes cas que :meth:`rollout`, plus un
                ``delai_effet_weeks`` invalide ou un état retourné par
                l'action sans les clés attendues (messages en français).
        """
        bornes = self._valider_delai(action)
        ctx = self._preparer(project_id, horizon_weeks, n_draws)
        brut0, brut1, rng_boot = self._executer(ctx, n_draws, seed, action=action)
        assert brut1 is not None  # action fournie : la branche AVEC existe
        previsions = self._agreger_apparie(ctx, brut0, brut1, rng_boot)
        return PairedForecast(
            project_id=project_id,
            horizon_weeks=ctx.horizon,
            n_draws=int(brut0.issue.shape[0] * brut0.issue.shape[1]),
            n_outer=K_EXTERNES,
            seed=seed,
            delai_effet_weeks=bornes,
            previsions=previsions,
        )

    # -- Ajustement sur l'historique du projet ----------------------------------

    def _serie_hebdo(self, node_id: str) -> tuple[list[str], _FloatArray]:
        """Série hebdomadaire des DERNIERS ur_local persistés du nœud.

        Même motif que ``CalibrationService.outcomes`` : le dernier état de
        chaque semaine ISO écrase les précédents ; les états sans ur_local
        (None) sont ignorés. Les semaines sont triées chronologiquement.

        Args:
            node_id: nœud dont on lit l'historique d'urgence.

        Returns:
            ``(semaines, valeurs)`` — libellés « AAAA-Sxx » et ur_local alignés.
        """
        derniers: dict[str, float] = {}
        for state in self._service.client_db(node_id).urgency_series(node_id):
            if state.ur_local is None:
                continue
            derniers[iso_week(state.timestamp)] = float(state.ur_local)
        semaines = sorted(derniers, key=_lundi)
        valeurs = np.asarray([derniers[s] for s in semaines], dtype=np.float64)
        return semaines, valeurs

    def _posterior_evenements(self, node_id: str, semaines: list[str]) -> tuple[float, float, int]:
        """Posterior Beta-Bernoulli du taux hebdomadaire d'événement défavorable.

        Prior de moyenne :data:`TAUX_PRIOR` (0.03) et de force N0 = 26
        pseudo-observations (convention du dépôt,
        :data:`~supplyscore.domain.events.N0_PSEUDO_OBSERVATIONS`). Chaque
        semaine d'historique est un essai de Bernoulli — succès si au moins un
        événement NON annulé de gravité « critique »/« defaut » y est
        journalisé (mêmes gravités que CalibrationService).

        Args:
            node_id: nœud observé.
            semaines: semaines d'historique (libellés « AAAA-Sxx »).

        Returns:
            ``(alpha_post, beta_post, k_obs)`` — paramètres du posterior et
            nombre de semaines avec événement défavorable.
        """
        client = self._service.client_db(node_id)
        k_obs = 0
        for semaine in semaines:
            for row in client.list_events(node_id, semaine):
                if row["reverted_at"] is not None:
                    continue  # événement annulé : déclaré par erreur
                gravite = json.loads(row["params_json"]).get("gravite")
                if gravite in _GRAVITES_DEFAVORABLES:
                    k_obs += 1
                    break
        n = len(semaines)
        alpha0 = TAUX_PRIOR * N0_PSEUDO_OBSERVATIONS
        beta0 = (1.0 - TAUX_PRIOR) * N0_PSEUDO_OBSERVATIONS
        return alpha0 + k_obs, beta0 + (n - k_obs), k_obs

    def _preparer(self, project_id: str, horizon_weeks: int, n_draws: int) -> _Contexte:
        """Valide les entrées et ajuste le contexte complet du rollout.

        Args:
            project_id: projet à projeter.
            horizon_weeks: horizon en semaines.
            n_draws: budget total de trajectoires.

        Returns:
            Le :class:`_Contexte` prêt à simuler.

        Raises:
            ValueError: entrées invalides, projet inconnu, aucun nœud actif ou
                historique insuffisant (messages en français).
        """
        if horizon_weeks < 1:
            raise ValueError(f"horizon_weeks doit être >= 1, reçu {horizon_weeks}")
        if n_draws < K_EXTERNES:
            raise ValueError(
                f"n_draws doit être >= {K_EXTERNES} (au moins un tirage interne par"
                f" tirage externe du MC imbriqué), reçu {n_draws}"
            )
        service = self._service
        project = service.registry.get_project(project_id)
        if project is None:
            raise ValueError(f"Projet inconnu : {project_id!r}")
        noeuds_projet = service.repo.nodes_by_project(project_id)
        simules = [
            node
            for node in noeuds_projet
            if node.status is TaskStatus.ACTIVE and node.onboarding_state != "draft"
        ]
        if not simules:
            raise ValueError(
                f"Prévision impossible pour le projet {project_id!r} : aucun nœud"
                " actif (onboarding terminé) à simuler."
            )
        t0 = project.origin_ts
        t_h = project_hours(service.clock_for(project_id).now(), t0)
        ordre_all = service.repo.topological_order()
        position = {nid: i for i, nid in enumerate(ordre_all)}
        ids_simules = {node.id for node in simules}
        sim_ids = [nid for nid in ordre_all if nid in ids_simules]
        sim_index = {nid: i for i, nid in enumerate(sim_ids)}

        insuffisants: list[str] = []
        x0: list[float] = []
        mu: list[float] = []
        phi_hat: list[float] = []
        se_phi: list[float] = []
        sigma_hat: list[float] = []
        se_sigma: list[float] = []
        alpha_post: list[float] = []
        beta_post: list[float] = []
        lois: list[LoiLeadTime] = []
        d0: list[float] = []
        deadlines: dict[str, float] = {}
        diagnostics: dict[str, DiagnosticAjustement] = {}
        for nid in sim_ids:
            semaines, valeurs = self._serie_hebdo(nid)
            if valeurs.size < MIN_HISTORY_WEEKS:
                insuffisants.append(f"{nid} ({valeurs.size} semaine(s))")
                continue
            node = service.repo.get_node(nid)
            assert node is not None  # id issu de nodes_by_project sur le même dépôt
            phi, se_p, sigma, se_s, moyenne = _ajuster_ar1(valeurs)
            a_post, b_post, k_obs = self._posterior_evenements(nid, semaines)
            loi = resoudre_loi(node)
            # Réutilise le calcul canonique des échéances du simulateur E13
            # (prochain jalon ACTIF en heures-projet, sinon kpis.time.deadline_h).
            echeance = SimulateurLeadTime._deadline_h(
                node, service.registry.list_milestones(nid), t0
            )
            x0.append(float(valeurs[-1]))
            mu.append(moyenne)
            phi_hat.append(phi)
            se_phi.append(se_p)
            sigma_hat.append(sigma)
            se_sigma.append(se_s)
            alpha_post.append(a_post)
            beta_post.append(b_post)
            lois.append(loi)
            d0.append(echeance if echeance is not None else math.inf)
            if echeance is not None:
                deadlines[nid] = float(echeance)
            diagnostics[nid] = DiagnosticAjustement(
                node_id=nid,
                n_semaines=int(valeurs.size),
                phi=phi,
                se_phi=se_p,
                sigma=sigma,
                se_sigma=se_s,
                mu=moyenne,
                ur_local_initial=float(valeurs[-1]),
                n_evenements=k_obs,
                taux_evenement=a_post / (a_post + b_post),
                alpha_post=a_post,
                beta_post=b_post,
                loi_lead_time=loi,
                deadline_h=echeance,
            )
        if insuffisants:
            raise ValueError(
                "Prévision impossible : historique hebdomadaire insuffisant (moins de"
                f" {MIN_HISTORY_WEEKS} semaines d'états d'urgence persistés) pour le(s)"
                f" nœud(s) actif(s) : {', '.join(insuffisants)}."
            )

        static_ur: dict[str, float] = {}
        beta_base: dict[tuple[str, str], float] = {}
        preds_base: dict[str, tuple[str, ...]] = {}
        for nid in ordre_all:
            if nid not in sim_index:
                node = service.repo.get_node(nid)
                assert node is not None  # id issu de topological_order() du même dépôt
                effectif = effective_ur_local(node.status, node.urgency.ur_local)
                static_ur[nid] = min(max(effectif, 0.0), 1.0)
            preds = service.repo.predecessors(nid)
            preds_base[nid] = tuple(pred.id for pred in preds)
            for pred in preds:
                arc = service.repo.get_arc(pred.id, nid)
                assert arc is not None  # pred est un prédécesseur : l'arc existe
                beta_base[(pred.id, nid)] = float(arc.beta)
        rank0_ids = [node.id for node in noeuds_projet if node.rank == 0]

        return _Contexte(
            project_id=project_id,
            horizon=int(horizon_weeks),
            t_h=float(t_h),
            ordre_all=ordre_all,
            position=position,
            sim_ids=sim_ids,
            sim_index=sim_index,
            static_ur=static_ur,
            beta_base=beta_base,
            preds_base=preds_base,
            rank0_ids=rank0_ids,
            deadlines=deadlines,
            x0=np.asarray(x0, dtype=np.float64),
            mu=np.asarray(mu, dtype=np.float64),
            phi_hat=np.asarray(phi_hat, dtype=np.float64),
            se_phi=np.asarray(se_phi, dtype=np.float64),
            sigma_hat=np.asarray(sigma_hat, dtype=np.float64),
            se_sigma=np.asarray(se_sigma, dtype=np.float64),
            alpha_post=np.asarray(alpha_post, dtype=np.float64),
            beta_post=np.asarray(beta_post, dtype=np.float64),
            lois=lois,
            d0=np.asarray(d0, dtype=np.float64),
            diagnostics=diagnostics,
        )

    # -- Boucle Monte Carlo imbriquée -------------------------------------------

    def _valider_delai(self, action: ActionRollout) -> tuple[float, float, float]:
        """Valide le triplet ``delai_effet_weeks`` de l'action.

        Args:
            action: action duck-typée à valider.

        Returns:
            Le triplet ``(min, mode, max)`` converti en floats.

        Raises:
            ValueError: triplet mal formé ou bornes incohérentes (français).
        """
        try:
            minimum, mode, maximum = (float(v) for v in action.delai_effet_weeks)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "delai_effet_weeks doit être un triplet (min, mode, max) de réels,"
                f" reçu {action.delai_effet_weeks!r}"
            ) from exc
        if not 0.0 <= minimum <= mode <= maximum:
            raise ValueError(
                f"delai_effet_weeks incohérent : min={minimum:g}, mode={mode:g},"
                f" max={maximum:g} (attendu 0 <= min <= mode <= max)"
            )
        return minimum, mode, maximum

    def _tirer_parametres(self, ctx: _Contexte, rng: np.random.Generator) -> _ParametresExternes:
        """Tire UN jeu de paramètres externes (incertitude paramétrique, D31).

        φ ~ N(φ̂, se(φ)) clipé [0, 0.98] ; σ ~ N(σ̂, se(σ)) plancher 0.01 ;
        taux ~ Beta(posterior) ; lois de lead time par bootstrap des moments.

        Args:
            ctx: contexte ajusté du rollout.
            rng: générateur commun de la simulation.

        Returns:
            Les :class:`_ParametresExternes` du tirage externe.
        """
        phi = np.clip(rng.normal(ctx.phi_hat, ctx.se_phi), 0.0, PHI_MAX)
        sigma = np.maximum(rng.normal(ctx.sigma_hat, ctx.se_sigma), SIGMA_MIN)
        taux = np.asarray(rng.beta(ctx.alpha_post, ctx.beta_post), dtype=np.float64)
        lois = [_loi_externe(loi, rng) for loi in ctx.lois]
        return _ParametresExternes(phi=phi, sigma=sigma, taux=taux, lois=lois)

    def _tirer_aleas(
        self, ctx: _Contexte, params: _ParametresExternes, rng: np.random.Generator, s: int
    ) -> _Tirages:
        """Pré-tire TOUS les aléas d'un tirage externe (base des CRN).

        Les deux branches d'un rollout apparié consomment ces tableaux à
        l'identique — aucun tirage supplémentaire n'a lieu pendant la
        simulation elle-même.

        Args:
            ctx: contexte ajusté du rollout.
            params: paramètres du tirage externe (lois de lead time perturbées).
            rng: générateur commun de la simulation.
            s: nombre de tirages internes.

        Returns:
            Les :class:`_Tirages` pré-tirés (délais d'action non inclus).
        """
        n = len(ctx.sim_ids)
        z = rng.standard_normal((ctx.horizon, s, n))
        u_evt = rng.random((ctx.horizon, s, n))
        u_sev = rng.random((ctx.horizon, s, n))
        lead = np.column_stack([tirer_lead_times(loi, rng, s) for loi in params.lois])
        return _Tirages(z=z, u_evt=u_evt, u_sev=u_sev, lead_times=lead)

    def _executer(
        self, ctx: _Contexte, n_draws: int, seed: int, action: ActionRollout | None
    ) -> tuple[_Empile, _Empile | None, np.random.Generator]:
        """Boucle externe du MC imbriqué : K tirages de paramètres × S trajectoires.

        Trois flux aléatoires indépendants dérivés de la graine : simulation,
        bootstrap (IC des deltas) et délais d'action — la branche SANS action
        d'un rollout apparié reproduit ainsi bit à bit :meth:`rollout`.

        Args:
            ctx: contexte ajusté du rollout.
            n_draws: budget total de trajectoires (arrondi à K·⌊n/K⌋).
            seed: graine du rollout.
            action: action à apparier, ou None (rollout simple).

        Returns:
            ``(branche_sans, branche_avec | None, rng_bootstrap)``.
        """
        s = n_draws // K_EXTERNES
        graines = np.random.SeedSequence(seed).spawn(3)
        rng_sim = np.random.default_rng(graines[0])
        rng_boot = np.random.default_rng(graines[1])
        rng_action = np.random.default_rng(graines[2])
        bornes = self._valider_delai(action) if action is not None else None
        n = len(ctx.sim_ids)
        h = ctx.horizon
        brut0 = _Empile(
            issue=np.zeros((K_EXTERNES, s, n, h), dtype=bool),
            jalon=np.zeros((K_EXTERNES, s, n, h), dtype=bool),
            impact=np.zeros((K_EXTERNES, s, n, h), dtype=bool),
        )
        brut1 = None
        if action is not None:
            brut1 = _Empile(
                issue=np.zeros((K_EXTERNES, s, n, h), dtype=bool),
                jalon=np.zeros((K_EXTERNES, s, n, h), dtype=bool),
                impact=np.zeros((K_EXTERNES, s, n, h), dtype=bool),
            )
        for j in range(K_EXTERNES):
            params = self._tirer_parametres(ctx, rng_sim)
            tirages = self._tirer_aleas(ctx, params, rng_sim, s)
            if bornes is not None:
                tirages.delais = _tirer_delais(bornes, rng_action, s)
            sortie0 = self._simuler_branche(ctx, params, tirages, None)
            brut0.issue[j] = sortie0.issue
            brut0.jalon[j] = sortie0.jalon
            brut0.impact[j] = sortie0.impact
            if action is not None and brut1 is not None:
                sortie1 = self._simuler_branche(ctx, params, tirages, action)
                brut1.issue[j] = sortie1.issue
                brut1.jalon[j] = sortie1.jalon
                brut1.impact[j] = sortie1.impact
        return brut0, brut1, rng_boot

    # -- Simulation d'une branche ------------------------------------------------

    def _simuler_branche(
        self,
        ctx: _Contexte,
        params: _ParametresExternes,
        tirages: _Tirages,
        action: ActionRollout | None,
    ) -> _SortieBranche:
        """Simule une branche (SANS ou AVEC action) sur les aléas pré-tirés.

        Semaine k = 1..h : application de l'action aux tirages nouvellement
        actifs (branche AVEC), pas AR(1) du cœur sans événement, occurrences
        d'événements défavorables (Bernoulli du hazard courant) avec bump de
        sévérité à décroissance géométrique, test de jalon raté (états
        ABSORBANTS : une issue survenue le reste), puis propagation Ur par
        lots pour l'impact client.

        Args:
            ctx: contexte ajusté du rollout.
            params: paramètres du tirage externe courant.
            tirages: aléas pré-tirés (CRN — identiques pour les deux branches).
            action: action appliquée, ou None (branche SANS).

        Returns:
            La :class:`_SortieBranche` (indicatrices (S, N, h)).
        """
        h = ctx.horizon
        s = int(tirages.z.shape[1])
        n = len(ctx.sim_ids)
        etat = _EtatBranche(
            x_ar=np.tile(ctx.x0, (s, 1)),
            bump=np.zeros((s, n)),
            hazard=np.tile(params.taux, (s, 1)),
            deadlines=np.tile(ctx.d0, (s, 1)),
            taux_base=params.taux,
            betas=dict(ctx.beta_base),
            preds=dict(ctx.preds_base),
        )
        evenement_cum = np.zeros((s, n), dtype=bool)
        jalon_cum = np.zeros((s, n), dtype=bool)
        completion = ctx.t_h + tirages.lead_times
        actifs_prec = np.zeros(s, dtype=bool)
        issue = np.zeros((s, n, h), dtype=bool)
        jalon = np.zeros((s, n, h), dtype=bool)
        impact = np.zeros((s, n, h), dtype=bool)
        for k in range(1, h + 1):
            if action is not None and tirages.delais is not None:
                actifs = np.floor(tirages.delais) < k
                nouveaux = actifs & ~actifs_prec
                if bool(nouveaux.any()):
                    self._appliquer_action(ctx, action, etat, nouveaux)
                actifs_prec = actifs
            etat.x_ar = np.clip(
                ctx.mu + params.phi * (etat.x_ar - ctx.mu) + params.sigma * tirages.z[k - 1],
                0.0,
                1.0,
            )
            evt = tirages.u_evt[k - 1] < etat.hazard
            sev = np.where(
                tirages.u_sev[k - 1] < 0.5, _SEVERITES_ADVERSES[0], _SEVERITES_ADVERSES[1]
            )
            etat.bump = _DECROISSANCE_HEBDO * etat.bump + sev * evt
            evenement_cum |= evt
            x_evt = np.clip(etat.x_ar + etat.bump, 0.0, 1.0)
            t_k = ctx.t_h + k * WEEK_HOURS
            jalon_cum |= (etat.deadlines <= t_k) & (
                (completion > etat.deadlines) | (etat.deadlines <= ctx.t_h)
            )
            jalon[:, :, k - 1] = jalon_cum
            issue[:, :, k - 1] = jalon_cum | evenement_cum
            impact[:, :, k - 1] = self._impact_client(ctx, x_evt, etat.x_ar, etat)
        return _SortieBranche(issue=issue, jalon=jalon, impact=impact)

    def _appliquer_action(
        self, ctx: _Contexte, action: ActionRollout, etat: _EtatBranche, nouveaux: _BoolArray
    ) -> None:
        """Applique l'action aux tirages nouvellement actifs (une fois par tirage).

        Construit l'état contractuel (valeurs de BASE — les tirages
        nouvellement actifs n'ont jamais été transformés), appelle
        ``apply_to_rollout`` puis répercute les écarts : cœur AR (ur_local),
        hazard, échéances et β d'arcs — β promus/neutralisés compris.

        Args:
            ctx: contexte ajusté du rollout.
            action: action duck-typée à appliquer.
            etat: état mutable de la branche (modifié en place).
            nouveaux: masque (S,) des tirages entrant en vigueur cette semaine.

        Raises:
            ValueError: état retourné sans les clés contractuelles (français).
        """
        s = int(etat.x_ar.shape[0])
        observable = np.clip(etat.x_ar + etat.bump, 0.0, 1.0)
        requete: dict[str, Any] = {
            "ur_local": observable,
            "hazard": etat.taux_base.copy(),
            "deadlines_h": dict(ctx.deadlines),
            "arc_beta": dict(ctx.beta_base),
            "node_ids": tuple(ctx.sim_ids),
        }
        reponse = action.apply_to_rollout(requete)
        manquantes = {"ur_local", "hazard", "deadlines_h", "arc_beta"} - set(reponse)
        if manquantes:
            raise ValueError(
                "apply_to_rollout doit retourner un état complet — clé(s)"
                f" manquante(s) : {sorted(manquantes)}"
            )
        delta = np.asarray(reponse["ur_local"], dtype=np.float64) - observable
        etat.x_ar[nouveaux] = np.clip(etat.x_ar[nouveaux] + delta[nouveaux], 0.0, 1.0)
        hz = np.clip(
            np.broadcast_to(np.asarray(reponse["hazard"], dtype=np.float64), observable.shape),
            0.0,
            1.0,
        )
        etat.hazard[nouveaux] = hz[nouveaux]
        echeances = reponse["deadlines_h"]
        d1 = np.asarray(
            [float(echeances.get(nid, math.inf)) for nid in ctx.sim_ids], dtype=np.float64
        )
        etat.deadlines[nouveaux] = d1
        arcs1 = {(str(src), str(dst)): float(v) for (src, dst), v in reponse["arc_beta"].items()}
        for arc in set(ctx.beta_base) | set(arcs1):
            base = ctx.beta_base.get(arc, 0.0)
            cible = min(max(arcs1.get(arc, 0.0), 0.0), 1.0)
            if cible == base:
                continue  # identité : conserve le scalaire (appariement CRN exact)
            src, dst = arc
            if arc not in ctx.beta_base and (
                src not in ctx.position
                or dst not in ctx.position
                or ctx.position[src] >= ctx.position[dst]
            ):
                continue  # promotion invalide topologiquement : ignorée (documenté)
            courant = etat.betas.get(arc, base)
            vecteur = np.full(s, courant) if isinstance(courant, float) else courant
            vecteur[nouveaux] = cible
            etat.betas[arc] = vecteur
            if src not in etat.preds.get(dst, ()):
                etat.preds[dst] = (*etat.preds.get(dst, ()), src)

    def _impact_client(
        self, ctx: _Contexte, x_evt: _FloatArray, x_base: _FloatArray, etat: _EtatBranche
    ) -> _BoolArray:
        """Impact client par nœud : P(ΔUr au rang 0 > 0.2) — variantes empilées.

        Pour chaque nœud simulé, la propagation factuelle (tous événements)
        est comparée à la propagation où SA colonne est remplacée par son
        chemin sans événement (mêmes aléas) ; ΔUr est lu sur le(s) nœud(s) de
        rang 0 du projet (max s'il y en a plusieurs). Toutes les variantes
        sont empilées en une seule passe de propagation par lots.

        Args:
            ctx: contexte ajusté du rollout.
            x_evt: matrice (S, N) des ur_local factuels (événements inclus).
            x_base: matrice (S, N) du chemin sans événement (cœur AR).
            etat: état de la branche (β et prédécesseurs courants).

        Returns:
            Indicatrices (S, N) — ΔUr au rang 0 strictement supérieur au seuil.
        """
        s, n = x_evt.shape
        if not ctx.rank0_ids:
            return np.zeros((s, n), dtype=bool)
        variantes = n + 1
        r = s * variantes
        ur_local: dict[str, float | _FloatArray] = dict(ctx.static_ur)
        for idx, node_id in enumerate(ctx.sim_ids):
            colonne = np.tile(x_evt[:, idx], variantes)
            debut = (idx + 1) * s
            colonne[debut : debut + s] = x_base[:, idx]
            ur_local[node_id] = colonne
        betas_r: dict[tuple[str, str], float | _FloatArray] = {
            arc: (valeur if isinstance(valeur, float) else np.tile(valeur, variantes))
            for arc, valeur in etat.betas.items()
        }
        ur = _propager_ur_batch(ctx.ordre_all, ur_local, etat.preds, betas_r, r)
        ur0 = ur[ctx.rank0_ids[0]]
        for cible in ctx.rank0_ids[1:]:
            ur0 = np.maximum(ur0, ur[cible])
        matrice = ur0.reshape(variantes, s)
        delta = matrice[0][None, :] - matrice[1:]
        resultat: _BoolArray = (delta > SEUIL_IMPACT_CLIENT).T
        return resultat

    # -- Agrégations --------------------------------------------------------------

    def _agreger(self, ctx: _Contexte, brut: _Empile) -> dict[str, dict[int, PrevisionNoeud]]:
        """Agrège un rollout simple : décomposition de variance et IC80 étiqueté.

        Args:
            ctx: contexte ajusté du rollout.
            brut: sorties empilées (K, S, N, h) de la branche simulée.

        Returns:
            Les :class:`PrevisionNoeud` par nœud puis par horizon.
        """
        k_ext, s, _, h = brut.issue.shape
        n_total = k_ext * s
        p_ext = brut.issue.mean(axis=1)  # (K, N, h) moyennes par tirage externe
        p = p_ext.mean(axis=0)
        var_mc = (p_ext * (1.0 - p_ext)).mean(axis=0)
        var_param = p_ext.var(axis=0, ddof=1)
        se_mc = np.sqrt(var_mc / n_total)
        se_total = np.sqrt(var_param + var_mc / n_total)
        bas = np.clip(p - _Z80 * se_total, 0.0, 1.0)
        haut = np.clip(p + _Z80 * se_total, 0.0, 1.0)
        # Moyennes de moyennes (interne puis externe) partout : le même ordre de
        # sommation que ``p`` — la branche SANS action d'un rollout apparié
        # reproduit ainsi ``rollout()`` bit à bit.
        p_jalon = brut.jalon.mean(axis=1).mean(axis=0)
        p_impact = brut.impact.mean(axis=1).mean(axis=0)
        previsions: dict[str, dict[int, PrevisionNoeud]] = {}
        for i, node_id in enumerate(ctx.sim_ids):
            par_h: dict[int, PrevisionNoeud] = {}
            for k in range(1, h + 1):
                ic80 = IntervalleConfiance(
                    bas=float(bas[i, k - 1]),
                    haut=float(haut[i, k - 1]),
                    couverture=("mc", "param"),
                )
                par_h[k] = PrevisionNoeud(
                    p_issue=float(p[i, k - 1]),
                    se_mc=float(se_mc[i, k - 1]),
                    var_mc=float(var_mc[i, k - 1]),
                    var_param=float(var_param[i, k - 1]),
                    ic80=ic80,
                    spread=float(haut[i, k - 1] - bas[i, k - 1]),
                    p_jalon_rate=float(p_jalon[i, k - 1]),
                    p_impact_client=float(p_impact[i, k - 1]),
                )
            previsions[node_id] = par_h
        return previsions

    def _agreger_apparie(
        self, ctx: _Contexte, brut0: _Empile, brut1: _Empile, rng_boot: np.random.Generator
    ) -> dict[str, dict[int, PrevisionAppariee]]:
        """Agrège les deux branches appariées : deltas, IC80 mc/param, p_delta.

        ``ic80_delta_mc`` : bootstrap PAR BLOCS INTERNES — dans chaque tirage
        externe, les différences appariées sont rééchantillonnées avec remise
        (:data:`_N_BOOTSTRAP` répliques partagées entre nœuds et horizons),
        la structure externe restant figée ; quantiles 10/90 des moyennes.
        ``ic80_delta_param`` : quantiles 10/90 des moyennes appariées par
        tirage externe (dispersion paramétrique pleine).

        Args:
            ctx: contexte ajusté du rollout.
            brut0: branche SANS action (K, S, N, h).
            brut1: branche AVEC action (K, S, N, h).
            rng_boot: générateur dédié au bootstrap (flux séparé, déterministe).

        Returns:
            Les :class:`PrevisionAppariee` par nœud puis par horizon.
        """
        k_ext, s, n, h = brut0.issue.shape
        d = brut0.issue.astype(np.int8) - brut1.issue.astype(np.int8)
        moyennes_ext = d.mean(axis=1)  # (K, N, h)
        delta = moyennes_ext.mean(axis=0)
        # Même ordre de sommation que ``_agreger`` (interne puis externe) :
        # p0 est bit à bit identique au p_issue de ``rollout()`` à graine égale.
        p0 = brut0.issue.mean(axis=1).mean(axis=0)
        p1 = brut1.issue.mean(axis=1).mean(axis=0)
        p_pos = (moyennes_ext > 0.0).mean(axis=0)
        q_param = np.quantile(moyennes_ext, (0.10, 0.90), axis=0)
        somme = np.zeros((_N_BOOTSTRAP, n, h))
        for j in range(k_ext):
            indices = rng_boot.integers(0, s, size=(_N_BOOTSTRAP, s))
            somme += d[j][indices].mean(axis=1)
        repliques = somme / k_ext
        q_mc = np.quantile(repliques, (0.10, 0.90), axis=0)
        impact0 = brut0.impact.mean(axis=1).mean(axis=0)
        impact1 = brut1.impact.mean(axis=1).mean(axis=0)
        previsions: dict[str, dict[int, PrevisionAppariee]] = {}
        for i, node_id in enumerate(ctx.sim_ids):
            par_h: dict[int, PrevisionAppariee] = {}
            for k in range(1, h + 1):
                par_h[k] = PrevisionAppariee(
                    p0=float(p0[i, k - 1]),
                    p1=float(p1[i, k - 1]),
                    delta_u_sim=float(delta[i, k - 1]),
                    ic80_delta_mc=IntervalleConfiance(
                        bas=float(q_mc[0, i, k - 1]),
                        haut=float(q_mc[1, i, k - 1]),
                        couverture=("mc",),
                    ),
                    ic80_delta_param=IntervalleConfiance(
                        bas=float(q_param[0, i, k - 1]),
                        haut=float(q_param[1, i, k - 1]),
                        couverture=("param",),
                    ),
                    p_delta_positif=float(p_pos[i, k - 1]),
                    p_impact_client_0=float(impact0[i, k - 1]),
                    p_impact_client_1=float(impact1[i, k - 1]),
                )
            previsions[node_id] = par_h
        return previsions
