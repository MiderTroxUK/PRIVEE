"""Prevision par rollouts Monte Carlo et contrefactuels apparies (HELIOS v7 - unite U9).

:class:`ForecastService` projette chaque noeud ACTIF d'un projet sur un horizon de
1 a 4 semaines a partir de son PROPRE historique hebdomadaire (etats d'urgence
persistes), puis chiffre l'effet d'une action corrective par tirages communs
apparies (CRN - contrat 12 fige du plan).

Sortie estimee - EQUIVALENCE FIGEE avec la calibration (Lot 11.1) : la
probabilite ``p_issue`` estime exactement l'" issue defavorable " de
:class:`~supplyscore.services.calibration.CalibrationService` - jalon RATE
(critere a) OU evenement non annule de gravite " critique "/" defaut "
(critere c, memes gravites - :data:`_GRAVITES_DEFAVORABLES` importee de la
calibration). Le critere (b) - noeud au statut abandonne - n'est pas simule :
seuls les noeuds ACTIFS sont projetes, l'abandon etant une issue a anticiper,
pas un etat d'entree. ``p_issue`` est ainsi l'estimateur PROSPECTIF du taux
que la calibration mesure RETROSPECTIVEMENT.

Incertitude decomposee (decision D31 du plan) : Monte Carlo IMBRIQUE -
K = 20 tirages EXTERNES des parametres (phi et sigma de l'AR(1) via leurs
erreurs-types de moindres carres, taux d'evenement via son posterior Beta,
moments du lead time par bootstrap parametrique) x ``n_draws/K`` trajectoires
INTERNES par tirage externe. La variance de ``p_issue`` est decomposee en
composante ``mc`` (intra-externe) et ``parametrique`` (inter-externes,
variance des moyennes externes) ; l'IC80 total, etiquete par sa couverture
``("mc", "param")``, combine l'erreur-type MC de l'estimateur et la dispersion
parametrique PLEINE de ``p_issue`` (l'incertitude porte sur p lui-meme).

VOCABULAIRE (decision D18' du plan) : les champs et docstrings de ce module
parlent d'" effet SELON LE MODELE " (``delta_u_sim``) - JAMAIS d'" effet
reel ". Les contrefactuels comparent deux branches SIMULEES sur les memes
aleas ; rien ici n'est une mesure d'effet causal observe.

Service en LECTURE SEULE : aucune ecriture en base, jamais.

Performance mesuree (``test_performance_chaine_20_noeuds``) : rollout S = 2000,
h = 4 puis rollout apparie complet (deux branches) sur une chaine de 20 noeuds
en ~0,3 s au total sur le poste de reference - tres largement sous la borne
de 60 s du plan.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

import numpy as np
from numpy.typing import NDArray

from supplyscore.core.clock import iso_week, project_hours
from supplyscore.core.status_rules import effective_ur_local
from supplyscore.domain.events import (
    _GRAVITE_ACCIDENT_SEVERITE,
    _GRAVITE_FINANCE_SEVERITE,
    LAMBDA_ARRET,
    N0_PSEUDO_OBSERVATIONS,
    RATTRAPAGE_HEBDO,
    WEEK_HOURS,
)
from supplyscore.domain.milestones import next_active_milestone
from supplyscore.domain.models import TaskStatus
from supplyscore.mc.lead_time import LoiLeadTime, SimulateurLeadTime, resoudre_loi, tirer_lead_times

# ``_GRAVITES_DEFAVORABLES`` est la definition CANONIQUE des gravites comptees comme issue defavorable (Lot 11.1) : reutilisee plutot que dupliquee - meme precedent que ``_lundi`` importe par calibration.py depuis weekly.py.
from supplyscore.services.calibration import _GRAVITES_DEFAVORABLES
from supplyscore.services.weekly import _lundi


def _env_float_forecast(nom: str, defaut: float, mini: float, maxi: float) -> float:
    """Lit un parametre de calibration depuis l'environnement, borne.

    Meme canal que ``supplyscore.domain.events`` : le harnais d'experience lance
    des SOUS-PROCESSUS, qu'un monkeypatch ne franchirait pas.
    """
    brut = os.environ.get(nom)
    if brut is None:
        return defaut
    try:
        return min(max(float(brut), mini), maxi)
    except ValueError:
        return defaut

if TYPE_CHECKING:
    from supplyscore.services.orchestrator import SupplyScoreService

_FloatArray = NDArray[np.float64]
_BoolArray = NDArray[np.bool_]

#: Nombre minimal de semaines d'historique hebdomadaire exige par noeud actif.
MIN_HISTORY_WEEKS: int = 4

#: Tirages externes du Monte Carlo imbrique (decision D31 du plan v7).
K_EXTERNES: int = 20

#: Borne haute du coefficient AR(1) (stationnarite stricte).
PHI_MAX: float = 0.98

#: Plancher de l'ecart-type residuel de l'AR(1).
SIGMA_MIN: float = 0.01

#: Moyenne du prior Beta du taux hebdomadaire d'evenement defavorable (documente : de l'ordre d'un evenement critique toutes les ~33 semaines a priori).
TAUX_PRIOR: float = 0.03

#: Seuil de DeltaUr au rang 0 au-dela duquel un tirage compte comme " impact client ".
SEUIL_IMPACT_CLIENT: float = 0.2

#: Decroissance geometrique hebdomadaire du surcroit d'urgence d'un evenement (demi-vie d'une semaine - choix documente : un incident critique domine l'urgence locale la semaine ou il survient puis s'estompe de moitie chaque semaine, l'effet durable passant par la revision des KPIs, pas par ce bump).
_DECROISSANCE_HEBDO: float = 0.5

#: Severites simulees d'un evenement defavorable, DERIVEES d'EVENT_CALIBRATION : les deux gravites comptees comme issue defavorable portent, dans la calibration des evenements, des severites forfaitaires de 0.9 (alerte financiere " defaut ") et 1.0 (accident " critique ") - la simulation tire uniformement entre ces deux niveaux.
_SEVERITES_ADVERSES: tuple[float, float] = (
    _GRAVITE_FINANCE_SEVERITE["defaut"],
    _GRAVITE_ACCIDENT_SEVERITE["critique"],
)

#: Taille du bootstrap parametrique des moments de lead time (convention N0 du depot : l'incertitude des moments decroit en 1/sqrt26 pseudo-observations).
_N_BOOT_MOMENTS: int = int(N0_PSEUDO_OBSERVATIONS)

#: Repliques du bootstrap par blocs internes de l'IC80 MC des deltas apparies.
_N_BOOTSTRAP: int = 200

#: Quantile 0.9 de la N(0, 1) - IC bilateral a 80 %.
_Z80: float = 1.2815515655446004

#: Variance de pente consideree nulle (serie hebdomadaire constante).
_EPS_SXX: float = 1e-12


class ActionRollout(Protocol):
    """Contrat DUCK-TYPE d'une action prescriptible (contrat 8 du plan v7).

    Le catalogue reel des actions est construit par l'unite U15 - ce module
    n'en importe rien : toute valeur exposant les deux membres ci-dessous est
    acceptee par :meth:`ForecastService.rollout_with_action`.

    Attributes:
        delai_effet_weeks: triplet ``(min, mode, max)`` en semaines de la loi
            triangulaire du delai d'effet, avec ``0 <= min <= mode <= max``.
    """

    delai_effet_weeks: tuple[float, float, float]

    def apply_to_rollout(self, state: dict[str, Any]) -> dict[str, Any]:
        """Transforme l'etat de simulation (fonction PURE, sans effet de bord).

        L'etat recu - et le dict a retourner - porte EXACTEMENT les cles
        documentees dans :meth:`ForecastService.rollout_with_action`.

        Args:
            state: etat de simulation courant (lecture seule).

        Returns:
            Un nouvel etat portant les memes cles, valeurs transformees.
        """
        ...


# Resultats publics (dataclasses figees)


@dataclass(frozen=True)
class IntervalleConfiance:
    """Intervalle de confiance etiquete par les sources d'incertitude couvertes.

    Attributes:
        bas: borne basse de l'intervalle.
        haut: borne haute de l'intervalle.
        couverture: sources couvertes - ``("mc", "param")`` pour l'IC80 total
            d'un rollout, ``("mc",)`` ou ``("param",)`` pour les IC des deltas.
    """

    bas: float
    haut: float
    couverture: tuple[str, ...]


@dataclass(frozen=True)
class DiagnosticAjustement:
    """Diagnostics d'ajustement d'un noeud (serie hebdo -> AR(1) + Beta + lead time).

    Attributes:
        node_id: identifiant du noeud ajuste.
        n_semaines: nombre de semaines d'historique hebdomadaire utilisees.
        phi: coefficient AR(1) ajuste, clipe dans [0, 0.98].
        se_phi: erreur-type de phi (moindres carres ; 0.0 si serie constante).
        sigma: ecart-type residuel ajuste, plancher 0.01.
        se_sigma: erreur-type de sigma (approximation normale sigma/sqrt(2-ddl)).
        mu: moyenne de long terme de la recurrence (moyenne de la serie -
            choix simple documente, l'intercept exact divergerait pour phi -> 1).
        ur_local_initial: dernier ur_local hebdomadaire observe (etat initial).
        n_evenements: semaines d'historique ayant connu au moins un evenement
            defavorable (non annule, gravite " critique "/" defaut ").
        taux_evenement: moyenne a posteriori du taux hebdomadaire d'evenement.
        alpha_post: parametre alpha du posterior Beta du taux.
        beta_post: parametre beta du posterior Beta du taux.
        loi_lead_time: loi de lead time resolue (:func:`resoudre_loi`).
        deadline_h: echeance du prochain jalon ACTIF en heures-projet (sinon
            ``kpis.time.deadline_h``), None si le noeud n'a aucune echeance.
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
    """Prevision d'un noeud a un horizon donne (semaine k du rollout).

    Attributes:
        p_issue: probabilite estimee d'issue defavorable d'ici la semaine k
            (meme composite que CalibrationService : jalon rate OU evenement
            critique/defaut).
        se_mc: erreur-type Monte Carlo pure de l'estimateur, sqrt(var_mc/n).
        var_mc: variance INTRA-externe moyenne de l'indicatrice (composante MC).
        var_param: variance INTER-externes des moyennes par tirage externe
            (composante parametrique, ddof=1).
        ic80: IC80 total etiquete ``("mc", "param")`` - p +/- z?_0-sqrt(var_param +
            var_mc/n), borne dans [0, 1].
        spread: largeur de l'IC80 (``haut - bas``).
        p_jalon_rate: probabilite que le jalon (echeance) soit rate d'ici k.
        p_impact_client: P(DeltaUr au rang 0 > 0.2) - propagation factuelle contre
            propagation ou CE noeud est remplace par son chemin sans evenement
            (contrefactuel apparie par noeud, memes aleas).
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
    """Resultat fige d'un rollout Monte Carlo (partie A - prevision seule).

    Attributes:
        project_id: projet simule.
        horizon_weeks: horizon simule, en semaines.
        n_draws: nombre EFFECTIF de trajectoires simulees (K-floor(n_draws/K)).
        n_outer: nombre de tirages externes K du Monte Carlo imbrique.
        seed: graine du rollout (deterministe : meme graine, memes resultats).
        previsions: par noeud simule puis par horizon k  dans  1..h, la
            :class:`PrevisionNoeud`.
        diagnostics: par noeud simule, le :class:`DiagnosticAjustement`.
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
    """Comparaison appariee SANS/AVEC action d'un noeud a un horizon donne.

    Tous les effets sont des effets SELON LE MODELE (decision D18') : deux
    branches simulees sur des aleas identiques, jamais un effet reel mesure.

    Attributes:
        p0: probabilite d'issue defavorable SANS action.
        p1: probabilite d'issue defavorable AVEC action.
        delta_u_sim: effet SELON LE MODELE - moyenne sur les tirages apparies
            de (issue sans action - issue avec action).
        ic80_delta_mc: IC80 de ``delta_u_sim`` par bootstrap par blocs internes
            (repliques intra-externes), couverture ``("mc",)``.
        ic80_delta_param: IC80 parametrique - quantiles 10/90 des moyennes
            appariees par tirage externe, couverture ``("param",)``.
        p_delta_positif: fraction des tirages externes dont la moyenne appariee
            est strictement positive.
        p_impact_client_0: P(DeltaUr au rang 0 > 0.2) dans la branche SANS action.
        p_impact_client_1: P(DeltaUr au rang 0 > 0.2) dans la branche AVEC action.
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
    """Resultat fige d'un rollout contrefactuel apparie (partie B - contrat 12).

    Attributes:
        project_id: projet simule.
        horizon_weeks: horizon simule, en semaines.
        n_draws: nombre EFFECTIF de trajectoires par branche (K-floor(n_draws/K)).
        n_outer: nombre de tirages externes K du Monte Carlo imbrique.
        seed: graine du rollout (deterministe : meme graine, memes resultats).
        delai_effet_weeks: triplet (min, mode, max) valide du delai d'effet.
        previsions: par noeud simule puis par horizon k  dans  1..h, la
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
    """Bloc " forecast " du snapshot hebdomadaire (contrat 7 FIGE du plan v7).

    Args:
        result: resultat d'un :meth:`ForecastService.rollout`.

    Returns:
        ``{node_id: {"forecast": {"1"..."4": {"p_issue", "se_mc", "spread",
        "p_jalon_rate", "p_impact_client"}}}}`` - les cles d'horizon sont les
        semaines simulees converties en chaines.
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


# Structures internes


#: Ecart-type sur l'avancement declare d'un jalon, en points, elargi par noeud a proportion de son hidden_risk. A 0, P(jalon rate) sort binaire dans 85 % des cas sur le journal gele (102/120) ; a 0.10 la binarite tombe a 71.7 % et la zone exploitable passe de 14 a 17 previsions. Le gain se concentre sur les horizons COURTS : a 8 semaines les valeurs 0 / 0.10 / 0.20 sont indiscernables (+0.180 / +0.174 / +0.174), donc ce parametre compensait un horizon trop court et ne fait PAS le resultat. Garde pour l'argument physique : un avancement declare n'est pas une certitude. Env SUPPLYSCORE_SIGMA_AVANCEMENT.
SIGMA_AVANCEMENT: float = _env_float_forecast("SUPPLYSCORE_SIGMA_AVANCEMENT", 0.10, 0.0, 0.5)

#: Part d'une semaine qu'un evenement simule immobilise, avant severite et LAMBDA_ARRET ; sans ce terme les chocs tires n'atteignaient jamais P(jalon rate). Non calibre. A 1.0 : AUC en hausse sur 3 horizons/4, pire decile 5.9x -> 3.0x, binarite accrue. 0.0 restaure l'ancien comportement. Env SUPPLYSCORE_COUT_CHOC_SEMAINE.
COUT_CHOC_SEMAINE: float = _env_float_forecast("SUPPLYSCORE_COUT_CHOC_SEMAINE", 1.0, 0.0, 4.0)

#: Amortissement de l'extrapolation de TENDANCE du lead time, dans [0, 1]. A 0.0 la tendance est DESACTIVEE : le lead time reste fige sur sa valeur du jour, comportement historique. Dans (0, 1] la pente observee est extrapolee en s'amortissant d'un facteur g par semaine — g = 1 prolonge la rampe telle quelle, g = 0.8 l'aplatit. POURQUOI : resoudre_loi lit un instantane et completion_base est fige avant la boucle hebdomadaire, donc un fournisseur dont le cycle s'allonge regulierement etait projete comme stable. Le modele voyait le niveau du KPI et jamais sa derivee, alors qu'une degradation progressive est precisement le seul type de degradation qu'on puisse voir venir. Env SUPPLYSCORE_TENDANCE_LEAD_TIME.
TENDANCE_LEAD_TIME: float = _env_float_forecast("SUPPLYSCORE_TENDANCE_LEAD_TIME", 0.0, 0.0, 1.0)

#: Points d'historique KPI utilises pour estimer la pente. Trop court, la pente est du bruit ; trop long, elle rate un changement de regime. Six semaines couvrent l'espacement typique de deux jalons.
N_POINTS_TENDANCE: int = 6

#: L'extrapolation ne peut pas depasser ce multiple du lead time courant. Garde-fou contre une pente aberrante estimee sur peu de points : sans lui, une valeur isolee suffirait a projeter un cycle de plusieurs annees.
PLAFOND_TENDANCE: float = 2.0


@dataclass

class _Contexte:
    """Contexte fige d'un rollout : ajustements, graphe et temps du projet."""

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
    #: Part de travail RESTANTE du jalon actif de chaque noeud, dans [0, 1] (1.0 sans jalon actif). Le lead time tire vaut un cycle COMPLET : c'est cette part qu'il reste reellement a parcourir. Cf. ``_simuler_branche``.
    reste: _FloatArray
    #: Optimisme de declaration de chaque noeud, dans [0, 1] : le ``hidden_risk`` courant, c'est-a-dire [Ur - Ud]+. Il elargit l'incertitude d'avancement d'un declarant dont les chiffres se sont reveles optimistes (cf. :data:`SIGMA_AVANCEMENT`).
    optimisme: _FloatArray

    #: Pente hebdomadaire du lead time par noeud, en heures par semaine,
    #: estimee par moindres carres sur l'historique KPI. Positive = le
    #: fournisseur s'enlise. Nulle si la tendance est desactivee, ou si
    #: l'historique est trop court pour distinguer une pente d'un alea.
    pente_lead: _FloatArray
    #: Temps de production perdu et non rattrape (``time.delay_h``, en heures) de chaque noeud. ADDITIF a l'achevement, jamais mis a l'echelle de l'avancement : un arret coute sa duree quel que soit l'avancement.
    retard: _FloatArray
    diagnostics: dict[str, DiagnosticAjustement]


@dataclass
class _ParametresExternes:
    """Parametres d'UN tirage externe (incertitude parametrique, D31)."""

    phi: _FloatArray
    sigma: _FloatArray
    taux: _FloatArray
    lois: list[LoiLeadTime]


@dataclass
class _Tirages:
    """Aleas pre-tires d'un tirage externe - consommes a l'identique par les deux branches (CRN)."""

    z: _FloatArray
    u_evt: _FloatArray
    u_sev: _FloatArray
    lead_times: _FloatArray
    #: Part de travail restante TIREE par replicat (S, N) : l'avancement declare est bruite par :data:`SIGMA_AVANCEMENT` avant d'etre converti en reste.
    reste: _FloatArray | None = None
    delais: _FloatArray | None = None


@dataclass
class _EtatBranche:
    """Etat mutable d'une branche de simulation (matrices par tirage interne)."""

    x_ar: _FloatArray
    bump: _FloatArray
    hazard: _FloatArray
    deadlines: _FloatArray
    taux_base: _FloatArray
    betas: dict[tuple[str, str], float | _FloatArray]
    preds: dict[str, tuple[str, ...]]


@dataclass
class _SortieBranche:
    """Indicatrices (S, N, h) d'une branche : issue, jalon rate, impact client."""

    issue: _BoolArray
    jalon: _BoolArray
    impact: _BoolArray


@dataclass
class _Empile:
    """Sorties empilees (K, S, N, h) des K tirages externes d'une branche."""

    issue: _BoolArray
    jalon: _BoolArray
    impact: _BoolArray


# Aides pures


def _ajuster_ar1(valeurs: _FloatArray) -> tuple[float, float, float, float, float]:
    """Ajuste un AR(1) par moindres carres sur une serie hebdomadaire.

    Modele simule ensuite : ``x_{k} = mu + phi-(x_{k-1} - mu) + sigma-epsilon``. La
    pente OLS de ``x_{t+1}`` sur ``x_t`` fournit phi (clipe dans [0, 0.98]) et
    l'ecart-type residuel sigma (plancher 0.01, applique AVANT les erreurs-types -
    choix conservateur). ``mu`` est la moyenne de la serie. Serie (quasi)
    constante : phi = 0 avec se(phi) = 0, residus autour de la moyenne.

    Args:
        valeurs: serie hebdomadaire des ur_local (taille >= MIN_HISTORY_WEEKS).

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


def _pente_hebdo(valeurs: _FloatArray) -> float:
    """Pente d'une serie hebdomadaire par moindres carres, en unite par semaine.

    Args:
        valeurs: serie chronologique, du plus ancien au plus recent.

    Returns:
        La pente estimee ; 0.0 en dessous de trois points, car deux points
        definissent une droite mais ne distinguent pas une tendance d'un alea.
    """
    n = int(valeurs.size)
    if n < 3:
        return 0.0
    t = np.arange(n, dtype=np.float64)
    t_bar = float(t.mean())
    stt = float(np.sum((t - t_bar) ** 2))
    if stt <= _EPS_SXX:
        return 0.0
    return float(np.sum((t - t_bar) * (valeurs - float(valeurs.mean()))) / stt)


def _facteur_tendance(k: int, amortissement: float) -> float:
    """Somme geometrique ``1 + g + ... + g^(k-1)`` : cumul de la pente sur k semaines.

    Args:
        k: nombre de semaines projetees, >= 1.
        amortissement: ``g`` dans [0, 1].

    Returns:
        Le facteur multiplicatif a appliquer a la pente hebdomadaire.
    """
    if amortissement >= 1.0:
        return float(k)
    return float((1.0 - amortissement**k) / (1.0 - amortissement))


def _loi_externe(loi: LoiLeadTime, rng: np.random.Generator) -> LoiLeadTime:
    """Tirage externe de la loi de lead time : bootstrap parametrique des moments.

    Familles lognormale/normale : :data:`_N_BOOT_MOMENTS` (26) tirages de la
    loi de base fournissent des moments empiriques (m*, s*) - l'incertitude
    des moments decroit en 1/sqrt26, coherente avec la convention de
    pseudo-observations du depot. Familles triangulaire/deterministe :
    conservees telles quelles (bornes de cahier des charges, aucune
    incertitude parametrique estimable).

    Args:
        loi: loi de base resolue par :func:`resoudre_loi`.
        rng: generateur commun de la simulation.

    Returns:
        La loi perturbee du tirage externe.
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
    """Tire les delais d'effet (semaines) - triangulaire, un delai par tirage.

    Args:
        bornes: triplet valide (min, mode, max), support eventuellement degenere.
        rng: generateur dedie aux aleas d'action.
        n: nombre de tirages internes.

    Returns:
        Tableau ``(n,)`` de delais en semaines.
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
    """Propagation montante Ur par lots - meme recurrence que ``PropagationEngine._compute_ur``.

    OU-bruite en ordre topologique (fournisseurs profonds d'abord) sur des
    vecteurs ``(n_lignes,)`` : ``Ur_i = clip01(1 - (1 - Ur_loc_i) -
    Pi_j (1 - beta_ji - Ur_j))``. Les beta acceptent un scalaire ou un vecteur par
    ligne (actions actives sur une partie des tirages seulement).

    TODO : remplacer par ``PropagationEngine.compute_ur_batch`` (U3) apres fusion.

    Args:
        ordre: ordre topologique complet du depot.
        ur_local: urgence locale par noeud - scalaire (noeud statique) ou
            vecteur ``(n_lignes,)`` (noeud simule, variantes empilees).
        predecesseurs: fournisseurs directs par noeud (arcs nominaux + promus).
        betas: coefficient beta par arc, scalaire ou vecteur ``(n_lignes,)``.
        n_lignes: nombre de lignes simulees (tirages x variantes).

    Returns:
        Ur propage par noeud, vecteurs ``(n_lignes,)``.
    """
    ur: dict[str, _FloatArray] = {}
    for node_id in ordre:
        attenuation = np.ones(n_lignes, dtype=np.float64)
        for src in predecesseurs.get(node_id, ()):
            attenuation *= 1.0 - betas[(src, node_id)] * ur[src]
        loc = ur_local.get(node_id, 0.0)
        ur[node_id] = np.clip(1.0 - (1.0 - loc) * attenuation, 0.0, 1.0)
    return ur


# Service


class ForecastService:
    """Rollouts Monte Carlo prospectifs et contrefactuels apparies d'un projet.

    S'appuie sur la facade :class:`SupplyScoreService` : le registre fournit
    projets et jalons, ``clock_for`` l'horloge effective du projet, le depot
    de graphe la topologie et les bases CLIENT l'historique d'urgence
    (``urgency_series``) et le journal d'evenements (``list_events``).
    Service en LECTURE SEULE : rien n'est jamais ecrit.

    Attributes:
        MIN_HISTORY_WEEKS: nombre minimal de semaines d'historique hebdomadaire
            exige par noeud actif (alias de classe de la constante du module).
    """

    MIN_HISTORY_WEEKS: ClassVar[int] = MIN_HISTORY_WEEKS

    def __init__(self, service: SupplyScoreService) -> None:
        """Initialise le service de prevision au-dessus de la facade.

        Args:
            service: facade applicative (registre, bases client, horloges).
        """
        self._service = service

    # API publique

    def rollout(
        self, project_id: str, horizon_weeks: int = 4, n_draws: int = 2000, seed: int = 0
    ) -> ForecastResult:
        """Rollout Monte Carlo du projet sur 1..``horizon_weeks`` semaines.

        Ajuste chaque noeud ACTIF sur son propre historique hebdomadaire
        (AR(1) sur ur_local, posterior Beta du taux d'evenement defavorable,
        loi de lead time :func:`resoudre_loi`), puis simule K = 20 tirages
        externes de parametres x ``n_draws/K`` trajectoires internes
        (decision D31). L'issue estimee est l'" issue defavorable " de
        CalibrationService : jalon rate d'ici k OU evenement critique/defaut
        d'ici k - cf. la docstring du module pour l'equivalence figee.

        Args:
            project_id: projet a projeter.
            horizon_weeks: horizon en semaines (defaut 4).
            n_draws: budget total de trajectoires (arrondi a K-floor(n/K)).
            seed: graine du rollout - meme graine, resultats identiques.

        Returns:
            Le :class:`ForecastResult` (previsions par noeud x horizon,
            diagnostics d'ajustement).

        Raises:
            ValueError: horizon < 1, ``n_draws`` < K, projet inconnu, aucun
                noeud actif, ou historique hebdomadaire insuffisant
                (< :data:`MIN_HISTORY_WEEKS` semaines) sur un noeud actif -
                messages en francais.
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
        """Rollout contrefactuel apparie SANS/AVEC action (contrat 12 fige).

        TIRAGES COMMUNS (CRN) : les deux branches consomment EXACTEMENT les
        memes aleas pre-tires (bruits AR, occurrences et severites
        d'evenements, lead times) - la branche AVEC applique l'action a
        partir de sa semaine d'effet, tiree UNE fois par tirage interne dans
        la triangulaire ``action.delai_effet_weeks`` (un delai de d semaines
        laisse floor(d) semaine(s) pleine(s) sans effet ; l'action agit a partir
        de la semaine floor(d)+1). Les delais sont tires sur un flux aleatoire
        SEPARE : la branche SANS action reproduit bit a bit
        :meth:`rollout` a graine egale.

        ETAT DE SIMULATION passe a ``action.apply_to_rollout(state)`` - appelee
        une fois par semaine comptant des tirages nouvellement actifs, sur des
        valeurs de BASE (jamais encore transformees pour ces tirages) :

        - ``"ur_local"`` : tableau ``(S, N)`` - urgence locale observable
          (evenements inclus) par tirage interne x noeud simule ;
        - ``"hazard"`` : tableau ``(N,)`` - taux hebdomadaire d'evenement
          defavorable par noeud (le retour peut etre ``(N,)`` ou ``(S, N)``) ;
        - ``"deadlines_h"`` : ``dict[node_id, float]`` - echeance en
          heures-projet des noeuds qui en ont une ;
        - ``"arc_beta"`` : ``dict[(source_id, target_id), float]`` - beta des
          arcs nominaux de propagation ;
        - ``"node_ids"`` : tuple des ids des noeuds simules - ORDRE DES
          COLONNES des tableaux ci-dessus (cle de lecture, a ne pas modifier).

        Le dict retourne doit porter les quatre premieres cles ; leurs effets,
        pour les tirages nouvellement actifs, du debut de leur semaine d'effet
        jusqu'a la fin de l'horizon :

        - reduire ``ur_local`` : l'ecart (retour - etat) est applique au coeur
          AR porte - il persiste ensuite via la recurrence ;
        - reduire ``hazard`` : le taux transforme pilote les occurrences ;
        - decaler une echeance : la valeur transformee pilote le test de
          jalon rate (cle ABSENTE du dict retourne = echeance neutralisee) ;
        - promouvoir un arc : cle AJOUTEE a ``arc_beta`` (source avant cible
          dans l'ordre topologique, sinon ignoree) ; cle ABSENTE = arc
          neutralise (beta = 0) ; beta bornes dans [0, 1].

        Tous les champs de sortie sont des effets SELON LE MODELE (decision
        D18') : jamais un " effet reel ".

        Args:
            project_id: projet a projeter.
            action: action duck-typee (cf. :class:`ActionRollout`).
            horizon_weeks: horizon en semaines (defaut 4).
            n_draws: budget total de trajectoires PAR BRANCHE.
            seed: graine du rollout - meme graine, resultats identiques.

        Returns:
            Le :class:`PairedForecast` (p0, p1, delta_u_sim et IC associes).

        Raises:
            ValueError: memes cas que :meth:`rollout`, plus un
                ``delai_effet_weeks`` invalide ou un etat retourne par
                l'action sans les cles attendues (messages en francais).
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

    # Ajustement sur l'historique du projet

    def _serie_hebdo(self, node_id: str) -> tuple[list[str], _FloatArray]:
        """Serie hebdomadaire des DERNIERS ur_local persistes du noeud.

        Meme motif que ``CalibrationService.outcomes`` : le dernier etat de
        chaque semaine ISO ecrase les precedents ; les etats sans ur_local
        (None) sont ignores. Les semaines sont triees chronologiquement.

        Args:
            node_id: noeud dont on lit l'historique d'urgence.

        Returns:
            ``(semaines, valeurs)`` - libelles " AAAA-Sxx " et ur_local alignes.
        """
        derniers: dict[str, float] = {}
        for state in self._service.client_db(node_id).urgency_series(node_id):
            if state.ur_local is None:
                continue
            derniers[iso_week(state.timestamp)] = float(state.ur_local)
        semaines = sorted(derniers, key=_lundi)
        valeurs = np.asarray([derniers[s] for s in semaines], dtype=np.float64)
        return semaines, valeurs

    def _pente_lead_time(self, node_id: str) -> float:
        """Pente hebdomadaire du lead time du noeud, en heures par semaine.

        Rend 0.0 des que :data:`TENDANCE_LEAD_TIME` vaut 0, sans lire la base :
        la tendance desactivee doit etre un vrai no-op, sinon deux mesures
        " avec " et " sans " ne sont pas comparables.

        Le regroupement hebdomadaire reprend celui de :meth:`_serie_hebdo` — le
        dernier snapshot de chaque semaine ISO fait foi — pour que la pente soit
        homogene a l'AR(1) ajuste juste a cote, et non a une cadence d'ecriture
        qui varie d'un noeud a l'autre.

        Args:
            node_id: noeud dont on estime la tendance.

        Returns:
            La pente, positive si le cycle s'allonge.
        """
        if TENDANCE_LEAD_TIME <= 0.0:
            return 0.0
        derniers: dict[str, float] = {}
        for ts, kpis in self._service.client_db(node_id).kpi_series(node_id, limite=64):
            lead = kpis.time.lead_time_h
            if lead is not None and lead > 0.0:
                derniers[iso_week(ts)] = float(lead)
        if len(derniers) < 3:
            return 0.0
        semaines = sorted(derniers, key=_lundi)[-N_POINTS_TENDANCE:]
        return _pente_hebdo(np.asarray([derniers[s] for s in semaines], dtype=np.float64))

    def _posterior_evenements(self, node_id: str, semaines: list[str]) -> tuple[float, float, int]:
        """Posterior Beta-Bernoulli du taux hebdomadaire d'evenement defavorable.

        Prior de moyenne :data:`TAUX_PRIOR` (0.03) et de force N0 = 26
        pseudo-observations (convention du depot,
        :data:`~supplyscore.domain.events.N0_PSEUDO_OBSERVATIONS`). Chaque
        semaine d'historique est un essai de Bernoulli - succes si au moins un
        evenement NON annule de gravite " critique "/" defaut " y est
        journalise (memes gravites que CalibrationService).

        Args:
            node_id: noeud observe.
            semaines: semaines d'historique (libelles " AAAA-Sxx ").

        Returns:
            ``(alpha_post, beta_post, k_obs)`` - parametres du posterior et
            nombre de semaines avec evenement defavorable.
        """
        client = self._service.client_db(node_id)
        k_obs = 0
        for semaine in semaines:
            for row in client.list_events(node_id, semaine):
                if row["reverted_at"] is not None:
                    continue  # evenement annule : declare par erreur
                gravite = json.loads(row["params_json"]).get("gravite")
                if gravite in _GRAVITES_DEFAVORABLES:
                    k_obs += 1
                    break
        n = len(semaines)
        alpha0 = TAUX_PRIOR * N0_PSEUDO_OBSERVATIONS
        beta0 = (1.0 - TAUX_PRIOR) * N0_PSEUDO_OBSERVATIONS
        return alpha0 + k_obs, beta0 + (n - k_obs), k_obs

    def _preparer(self, project_id: str, horizon_weeks: int, n_draws: int) -> _Contexte:
        """Valide les entrees et ajuste le contexte complet du rollout.

        Args:
            project_id: projet a projeter.
            horizon_weeks: horizon en semaines.
            n_draws: budget total de trajectoires.

        Returns:
            Le :class:`_Contexte` pret a simuler.

        Raises:
            ValueError: entrees invalides, projet inconnu, aucun noeud actif ou
                historique insuffisant (messages en francais).
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
        reste: list[float] = []
        retard: list[float] = []
        optimisme: list[float] = []
        pente_lead: list[float] = []
        deadlines: dict[str, float] = {}
        diagnostics: dict[str, DiagnosticAjustement] = {}
        for nid in sim_ids:
            semaines, valeurs = self._serie_hebdo(nid)
            if valeurs.size < MIN_HISTORY_WEEKS:
                insuffisants.append(f"{nid} ({valeurs.size} semaine(s))")
                continue
            node = service.repo.get_node(nid)
            assert node is not None  # id issu de nodes_by_project sur le meme depot
            phi, se_p, sigma, se_s, moyenne = _ajuster_ar1(valeurs)
            a_post, b_post, k_obs = self._posterior_evenements(nid, semaines)
            loi = resoudre_loi(node)
            # Reutilise le calcul canonique des echeances du simulateur E13 (prochain jalon ACTIF en heures-projet, sinon kpis.time.deadline_h).
            jalons = service.registry.list_milestones(nid)
            echeance = SimulateurLeadTime._deadline_h(node, jalons, t0)
            m_star = next_active_milestone(jalons)
            # Part du cycle qu'il reste a parcourir : le lead time tire est un cycle COMPLET, or un jalon deja avance n'a plus a le refaire.
            reste.append(1.0 if m_star is None else min(max(1.0 - m_star.progress, 0.0), 1.0))
            retard.append(max(node.kpis.time.delay_h or 0.0, 0.0))
            # " Ce fournisseur s'enlise-t-il ? " — la pente du lead time repond,
            # la valeur du jour non. Sans elle, une rampe est projetee comme un
            # plateau et la degradation n'est vue qu'une fois arrivee.
            pente_lead.append(self._pente_lead_time(nid))
            # " Ce noeud a-t-il l'habitude de sous-declarer ? " - la reponse est deja calculee par le moteur d'adequation.
            urg = node.urgency
            optimisme.append(
                min(max(getattr(urg, "hidden_risk", 0.0) or 0.0, 0.0), 1.0)
                if urg is not None
                else 0.0
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
                assert node is not None  # id issu de topological_order() du meme depot
                effectif = effective_ur_local(node.status, node.urgency.ur_local)
                static_ur[nid] = min(max(effectif, 0.0), 1.0)
            preds = service.repo.predecessors(nid)
            preds_base[nid] = tuple(pred.id for pred in preds)
            for pred in preds:
                arc = service.repo.get_arc(pred.id, nid)
                assert arc is not None  # pred est un predecesseur : l'arc existe
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
            reste=np.asarray(reste, dtype=np.float64),
            retard=np.asarray(retard, dtype=np.float64),
            optimisme=np.asarray(optimisme, dtype=np.float64),
            pente_lead=np.asarray(pente_lead, dtype=np.float64),
            diagnostics=diagnostics,
        )

    # Boucle Monte Carlo imbriquee

    def _valider_delai(self, action: ActionRollout) -> tuple[float, float, float]:
        """Valide le triplet ``delai_effet_weeks`` de l'action.

        Args:
            action: action duck-typee a valider.

        Returns:
            Le triplet ``(min, mode, max)`` converti en floats.

        Raises:
            ValueError: triplet mal forme ou bornes incoherentes (francais).
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
        """Tire UN jeu de parametres externes (incertitude parametrique, D31).

        phi ~ N(phi, se(phi)) clipe [0, 0.98] ; sigma ~ N(sigma, se(sigma)) plancher 0.01 ;
        taux ~ Beta(posterior) ; lois de lead time par bootstrap des moments.

        Args:
            ctx: contexte ajuste du rollout.
            rng: generateur commun de la simulation.

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
        """Pre-tire TOUS les aleas d'un tirage externe (base des CRN).

        Les deux branches d'un rollout apparie consomment ces tableaux a
        l'identique - aucun tirage supplementaire n'a lieu pendant la
        simulation elle-meme.

        Args:
            ctx: contexte ajuste du rollout.
            params: parametres du tirage externe (lois de lead time perturbees).
            rng: generateur commun de la simulation.
            s: nombre de tirages internes.

        Returns:
            Les :class:`_Tirages` pre-tires (delais d'action non inclus).
        """
        n = len(ctx.sim_ids)
        z = rng.standard_normal((ctx.horizon, s, n))
        u_evt = rng.random((ctx.horizon, s, n))
        u_sev = rng.random((ctx.horizon, s, n))
        lead = np.column_stack([tirer_lead_times(loi, rng, s) for loi in params.lois])
        # L'avancement declare est bruite par replicat : c'est une declaration, pas une mesure (cf. SIGMA_AVANCEMENT). Sans cet alea, le seul terme stochastique de P(jalon rate) est le lead time, et l'indicatrice bascule en bloc - d'ou les 0/1 quasi exclusifs. sigma = 0 doit etre un VRAI no-op : ne pas tirer du tout, sinon le generateur est consomme et tous les tirages suivants se decalent. Une option neutralisee qui change quand meme le resultat rend toute comparaison avant/apres trompeuse - constate en balayant ce parametre.
        if SIGMA_AVANCEMENT <= 0.0:
            return _Tirages(z=z, u_evt=u_evt, u_sev=u_sev, lead_times=lead)
        # sigma elargi pour les declarants optimistes : un noeud dont l'urgence reelle depasse l'urgence declaree a montre que ses chiffres sont au-dessous de la realite - son avancement merite plus de doute que celui d'un declarant fiable. L'information existe deja (hidden_risk), elle n'etait simplement pas utilisee par la prevision.
        sigma_noeud = SIGMA_AVANCEMENT * (1.0 + ctx.optimisme)[None, :]
        avancement = np.clip(
            (1.0 - ctx.reste)[None, :] + sigma_noeud * rng.standard_normal((s, n)),
            0.0,
            1.0,
        )
        return _Tirages(
            z=z, u_evt=u_evt, u_sev=u_sev, lead_times=lead, reste=1.0 - avancement
        )

    def _executer(
        self, ctx: _Contexte, n_draws: int, seed: int, action: ActionRollout | None
    ) -> tuple[_Empile, _Empile | None, np.random.Generator]:
        """Boucle externe du MC imbrique : K tirages de parametres x S trajectoires.

        Trois flux aleatoires independants derives de la graine : simulation,
        bootstrap (IC des deltas) et delais d'action - la branche SANS action
        d'un rollout apparie reproduit ainsi bit a bit :meth:`rollout`.

        Args:
            ctx: contexte ajuste du rollout.
            n_draws: budget total de trajectoires (arrondi a K-floor(n/K)).
            seed: graine du rollout.
            action: action a apparier, ou None (rollout simple).

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

    # Simulation d'une branche

    def _simuler_branche(
        self,
        ctx: _Contexte,
        params: _ParametresExternes,
        tirages: _Tirages,
        action: ActionRollout | None,
    ) -> _SortieBranche:
        """Simule une branche (SANS ou AVEC action) sur les aleas pre-tires.

        Semaine k = 1..h : application de l'action aux tirages nouvellement
        actifs (branche AVEC), pas AR(1) du coeur sans evenement, occurrences
        d'evenements defavorables (Bernoulli du hazard courant) avec bump de
        severite a decroissance geometrique, test de jalon rate (etats
        ABSORBANTS : une issue survenue le reste), puis propagation Ur par
        lots pour l'impact client.

        Args:
            ctx: contexte ajuste du rollout.
            params: parametres du tirage externe courant.
            tirages: aleas pre-tires (CRN - identiques pour les deux branches).
            action: action appliquee, ou None (branche SANS).

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
        # Achevement = maintenant + travail restant + temps perdu. ``lead_times`` tire un cycle entier, donc on le met a l'echelle du reste a faire (sinon 99,6 % annonce sur un jalon livre a l'heure) ; le temps perdu par un choc s'ajoute sans mise a l'echelle et vit pendant le rollout.
        reste_tire = ctx.reste if tirages.reste is None else tirages.reste
        # Part de l'achevement qui ne depend pas du retard NI de la tendance.
        completion_base = ctx.t_h + tirages.lead_times * reste_tire
        # TENDANCE : un cycle demarre dans k semaines chez un fournisseur qui
        # s'enlise dure plus longtemps qu'un cycle demarre aujourd'hui. Sans ce
        # terme, ``completion_base`` reste fige sur la valeur du jour et la
        # degradation progressive n'est vue qu'une fois arrivee. L'extrapolation
        # est plafonnee pour qu'une pente aberrante ne projette pas un cycle
        # absurde (cf. :data:`PLAFOND_TENDANCE`).
        tendance_active = TENDANCE_LEAD_TIME > 0.0 and bool(np.any(ctx.pente_lead != 0.0))
        if tendance_active:
            plafond_lead = PLAFOND_TENDANCE * tirages.lead_times
        # Un jalon dont le travail est ACHEVE (reste = 0) ne peut plus etre repousse : meme garde-fou que ``UrModel.u_base_jalon``, sans quoi le temps perdu declarerait en retard un jalon qui n'a plus rien a faire.
        porte_retard = (reste_tire > 0.0).astype(np.float64)
        retard = np.broadcast_to(ctx.retard, (s, n)).astype(np.float64).copy()
        completion = completion_base + retard * porte_retard
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
            # TEMPS DE PRODUCTION PERDU par l'evenement de la semaine, avec la MEME semantique que ``domain.events._arret_impact`` : un choc de severite ``sev`` immobilise cette fraction de la semaine, dont la part ``LAMBDA_ARRET`` s'inscrit au retard. Aucun parametre nouveau n'est introduit - ``sev`` sort deja d'EVENT_CALIBRATION, et les deux taux sont ceux que le balayage a cales sur la campagne gelee. La decroissance applique ``RATTRAPAGE_HEBDO`` avant l'ajout, comme ``weekly_decay`` le fait pour une semaine ecoulee : la projection suit donc la dynamique qu'elle projette, y compris si ce taux est un jour calibre non nul.
            retard *= 1.0 - RATTRAPAGE_HEBDO
            retard += LAMBDA_ARRET * sev * COUT_CHOC_SEMAINE * WEEK_HOURS * evt
            if tendance_active:
                derive = ctx.pente_lead[None, :] * _facteur_tendance(k, TENDANCE_LEAD_TIME)
                lead_k = np.minimum(tirages.lead_times + derive, plafond_lead)
                completion_base = ctx.t_h + np.maximum(lead_k, 0.0) * reste_tire
            completion = completion_base + retard * porte_retard
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

        Construit l'etat contractuel (valeurs de BASE - les tirages
        nouvellement actifs n'ont jamais ete transformes), appelle
        ``apply_to_rollout`` puis repercute les ecarts : coeur AR (ur_local),
        hazard, echeances et beta d'arcs - beta promus/neutralises compris.

        Args:
            ctx: contexte ajuste du rollout.
            action: action duck-typee a appliquer.
            etat: etat mutable de la branche (modifie en place).
            nouveaux: masque (S,) des tirages entrant en vigueur cette semaine.

        Raises:
            ValueError: etat retourne sans les cles contractuelles (francais).
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
                continue  # identite : conserve le scalaire (appariement CRN exact)
            src, dst = arc
            if arc not in ctx.beta_base and (
                src not in ctx.position
                or dst not in ctx.position
                or ctx.position[src] >= ctx.position[dst]
            ):
                continue  # promotion invalide topologiquement : ignoree (documente)
            courant = etat.betas.get(arc, base)
            vecteur = np.full(s, courant) if isinstance(courant, float) else courant
            vecteur[nouveaux] = cible
            etat.betas[arc] = vecteur
            if src not in etat.preds.get(dst, ()):
                etat.preds[dst] = (*etat.preds.get(dst, ()), src)

    def _impact_client(
        self, ctx: _Contexte, x_evt: _FloatArray, x_base: _FloatArray, etat: _EtatBranche
    ) -> _BoolArray:
        """Impact client par noeud : P(DeltaUr au rang 0 > 0.2) - variantes empilees.

        Pour chaque noeud simule, la propagation factuelle (tous evenements)
        est comparee a la propagation ou SA colonne est remplacee par son
        chemin sans evenement (memes aleas) ; DeltaUr est lu sur le(s) noeud(s) de
        rang 0 du projet (max s'il y en a plusieurs). Toutes les variantes
        sont empilees en une seule passe de propagation par lots.

        Args:
            ctx: contexte ajuste du rollout.
            x_evt: matrice (S, N) des ur_local factuels (evenements inclus).
            x_base: matrice (S, N) du chemin sans evenement (coeur AR).
            etat: etat de la branche (beta et predecesseurs courants).

        Returns:
            Indicatrices (S, N) - DeltaUr au rang 0 strictement superieur au seuil.
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

    # Agregations

    def _agreger(self, ctx: _Contexte, brut: _Empile) -> dict[str, dict[int, PrevisionNoeud]]:
        """Agrege un rollout simple : decomposition de variance et IC80 etiquete.

        Args:
            ctx: contexte ajuste du rollout.
            brut: sorties empilees (K, S, N, h) de la branche simulee.

        Returns:
            Les :class:`PrevisionNoeud` par noeud puis par horizon.
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
        # Moyennes de moyennes (interne puis externe) partout : le meme ordre de sommation que ``p`` - la branche SANS action d'un rollout apparie reproduit ainsi ``rollout()`` bit a bit.
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
        """Agrege les deux branches appariees : deltas, IC80 mc/param, p_delta.

        ``ic80_delta_mc`` : bootstrap PAR BLOCS INTERNES - dans chaque tirage
        externe, les differences appariees sont reechantillonnees avec remise
        (:data:`_N_BOOTSTRAP` repliques partagees entre noeuds et horizons),
        la structure externe restant figee ; quantiles 10/90 des moyennes.
        ``ic80_delta_param`` : quantiles 10/90 des moyennes appariees par
        tirage externe (dispersion parametrique pleine).

        Args:
            ctx: contexte ajuste du rollout.
            brut0: branche SANS action (K, S, N, h).
            brut1: branche AVEC action (K, S, N, h).
            rng_boot: generateur dedie au bootstrap (flux separe, deterministe).

        Returns:
            Les :class:`PrevisionAppariee` par noeud puis par horizon.
        """
        k_ext, s, n, h = brut0.issue.shape
        d = brut0.issue.astype(np.int8) - brut1.issue.astype(np.int8)
        moyennes_ext = d.mean(axis=1)  # (K, N, h)
        delta = moyennes_ext.mean(axis=0)
        # Meme ordre de sommation que ``_agreger`` (interne puis externe) : p0 est bit a bit identique au p_issue de ``rollout()`` a graine egale.
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
