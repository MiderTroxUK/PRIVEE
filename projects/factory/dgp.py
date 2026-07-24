"""DGP (processus générateur de données) versionné pour l'usine de campagnes U6.

Ce module est PUR (aucune écriture DB, aucun import de service au chargement) :
il ne fait que définir la mécanique stochastique de la campagne. L'orchestration
(ouverture du service, boucle hebdomadaire, écriture des fichiers) vit dans
``run_random_campaign.py``, qui importe ce module.

Sommaire :

1. **Plan QMC** (:func:`sample_regimes`) : échantillonne l'espace des régimes
   (n_ranks, a, b, p_choc, sigma) par séquence de Sobol -- une chaîne = un
   point du plan, mieux réparti qu'un tirage i.i.d. sur le lot de chaînes.
2. **Dérive hebdomadaire des KPIs** (:func:`draw_kpi_innovations`) : marche
   AR(1) log-normale par (nœud, kpi_path), bornée via
   :func:`~supplyscore.domain.constraints.clamp_kpi_value`.
3. **Stress latent** ``s_i(t)`` : EMA de la « badness » tirée des innovations
   KPI (:func:`badness_from_innovations`) + chocs cachés Bernoulli(p_choc)
   décroissants (:func:`dynamics_week_step`).
4. **Aléa d'évènement** : ``h_i(t) = sigmoid(a + b·s_i(t))`` ; le type et la
   gravité sont tirés PROPORTIONNELLEMENT au stress (:func:`draw_event_params`,
   :func:`gravite_bucket`).
5. **Opérateur synthétique confondu** (:func:`decide_probability`) : la
   décision d'agir dépend du stress LATENT (``c0 + c1·s``), jamais loggé --
   c'est la confusion partielle voulue par le plan (D21/D32).
6. **Exécution imparfaite** (D29) : probabilité ``1 - p_echec`` par intervention.
7. **Effet vrai + paire CRN** (D18) : :func:`replay_without_action` rejoue la
   fenêtre SANS l'action sur un clone de l'état du générateur -- même flux de
   nombres aléatoires que la branche réelle, seule la transformation change.

CHOIX DOCUMENTÉ (isolation CRN) : :func:`dynamics_week_step` tire un nombre
FIXE de valeurs aléatoires, dans un ORDRE FIXE, quelle que soit l'issue
(choc caché déclenché ou non, évènement déclenché ou non). C'est la condition
nécessaire et suffisante pour que le clone d'un état de générateur rejoue un
flux bit-identique : si le nombre ou l'ordre des tirages dépendait de l'issue,
les deux branches désynchroniseraient leur générateur dès la première semaine
où elles divergent.

CHOIX DOCUMENTÉ (pas de fuite du latent) : le stress ``s_i(t)`` n'est JAMAIS
inclus dans les structures observables (``ctx`` / ``etat_avant`` des
interventions) -- seuls ``ur_local``, ``ud_local``, ``adequation``,
``false_urgency``, ``hidden_risk`` et les KPIs bruts y figurent. Le stress ne
sert qu'en interne, pour calculer l'aléa d'évènement et la probabilité de
décision de l'opérateur synthétique.
"""

from __future__ import annotations

import copy
import hashlib
import math
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import qmc

from supplyscore.domain.events import EVENT_CALIBRATION

# --- 1. Plan QMC sur l'espace des régimes ------------------------------------------

#: Choix discrets de n_ranks, indexés par le premier axe du plan de Sobol.
N_RANKS_CHOICES: tuple[int, ...] = (3, 4, 5, 6, 7)
A_BOUNDS: tuple[float, float] = (-5.0, -2.0)
B_BOUNDS: tuple[float, float] = (3.0, 8.0)
P_CHOC_BOUNDS: tuple[float, float] = (0.01, 0.08)
SIGMA_BOUNDS: tuple[float, float] = (0.03, 0.15)


@dataclass(frozen=True)
class Regime:
    """Régime stochastique d'une chaîne (un point du plan QMC).

    Attributes:
        n_ranks: profondeur du DAG (passé tel quel à ``seed_demo``).
        a: ordonnée à l'origine de l'aléa d'évènement (sigmoid).
        b: sensibilité de l'aléa d'évènement au stress latent.
        p_choc: probabilité hebdomadaire d'un choc caché par nœud.
        sigma: écart-type des innovations de la marche AR(1) log-normale.
    """

    n_ranks: int
    a: float
    b: float
    p_choc: float
    sigma: float

    @property
    def params_id(self) -> str:
        """Hash court (10 hex) des paramètres arrondis -- identifiant stable du régime."""
        payload = (
            f"{round(self.a, 4)}|{round(self.b, 4)}|{round(self.p_choc, 4)}|{round(self.sigma, 4)}"
        )
        return hashlib.sha1(payload.encode()).hexdigest()[:10]


def sample_regimes(seed: int, n_chains: int) -> list[Regime]:
    """Échantillonne ``n_chains`` régimes par séquence de Sobol scramblée.

    Un plan QMC (plutôt qu'un tirage i.i.d.) répartit mieux le lot de chaînes
    sur l'espace des régimes -- couverture uniforme même pour un petit nombre
    de chaînes. Le premier axe du plan (dans [0, 1)) choisit ``n_ranks`` par
    seau ; les quatre autres sont mis à l'échelle des bornes documentées.

    Args:
        seed: graine du plan (déterministe -- même seed -> même plan).
        n_chains: nombre de chaînes (donc de points du plan), >= 1.

    Returns:
        Une liste de :class:`Regime`, un par chaîne, dans l'ordre du plan.
    """
    if n_chains < 1:
        raise ValueError(f"n_chains doit être >= 1, reçu {n_chains}")
    with warnings.catch_warnings():
        # Sobol avertit quand n_chains n'est pas une puissance de 2 (propriété
        # de balance non garantie) -- sans conséquence pour un plan de régimes,
        # seule la COUVERTURE compte ici, pas la balance exacte.
        warnings.simplefilter("ignore", category=UserWarning)
        sampler = qmc.Sobol(d=5, scramble=True, seed=seed)
        raw = sampler.random(n_chains)
    l_bounds = [A_BOUNDS[0], B_BOUNDS[0], P_CHOC_BOUNDS[0], SIGMA_BOUNDS[0]]
    u_bounds = [A_BOUNDS[1], B_BOUNDS[1], P_CHOC_BOUNDS[1], SIGMA_BOUNDS[1]]
    scaled = qmc.scale(raw[:, 1:], l_bounds, u_bounds)
    regimes: list[Regime] = []
    for i in range(n_chains):
        idx = min(int(raw[i, 0] * len(N_RANKS_CHOICES)), len(N_RANKS_CHOICES) - 1)
        a, b, p_choc, sigma = (float(v) for v in scaled[i])
        regimes.append(Regime(n_ranks=N_RANKS_CHOICES[idx], a=a, b=b, p_choc=p_choc, sigma=sigma))
    return regimes


def derive_seed(*parts: object) -> int:
    """Sous-graine déterministe dérivée de ``parts`` (hash stable SHA256).

    Indépendant de ``PYTHONHASHSEED`` (contrairement à ``hash()`` sur des
    chaînes) -- reproductible d'un run à l'autre et d'une machine à l'autre.
    """
    payload = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(payload.encode()).digest()
    return int.from_bytes(digest[:8], "big")


def dgp_manifest(regime: Regime, seed: int) -> dict[str, Any]:
    """Contenu de ``dgp_manifest.json`` pour une chaîne (schéma figé + extras documentés)."""
    return {
        "a": regime.a,
        "b": regime.b,
        "p_choc": regime.p_choc,
        "sigma": regime.sigma,
        "dgp_params_id": regime.params_id,
        "macro_series_id": None,  # réservé à un futur DGP piloté par une série macro (hors U6)
        "n_ranks": regime.n_ranks,
        "seed": seed,
        "effet_action_segment": dict(EFFET_SEGMENT),
        "p_echec_execution_defaut": DEFAULT_P_ECHEC_EXECUTION,
        "effect_window_weeks": EFFECT_WINDOW_WEEKS,
        "rank_proche_max": RANK_PROCHE_MAX,
    }


# --- 2. Dérive hebdomadaire des KPIs -------------------------------------------------

#: Les 9 chemins de KPI pilotés par la dérive (mêmes que
#: ``make_briefings.FIELD_LABELS``), ordre FIXE (forme fixe des tirages CRN).
KPI_PATHS: tuple[str, ...] = (
    "network.demand",
    "inventory.flow_rate",
    "time.lead_time_h",
    "cost.op_cost",
    "risk.cost_volatility",
    "risk.failure_probability",
    "oee.performance",
    "oee.availability",
    "inventory.current_volume_m3",
)

#: Convention de signe : +1 si une innovation POSITIVE (en log) est un signe
#: de dégradation pour ce KPI, -1 si c'est une innovation NÉGATIVE, 0 si le
#: KPI est exclu de la mesure de « badness » (niveau de stock : ni bon ni
#: mauvais en soi, seul un dépassement de borne compterait, hors périmètre).
_ADVERSE_SIGN: dict[str, int] = {
    "network.demand": -1,
    "inventory.flow_rate": -1,
    "time.lead_time_h": +1,
    "cost.op_cost": +1,
    "risk.cost_volatility": +1,
    "risk.failure_probability": +1,
    "oee.performance": -1,
    "oee.availability": -1,
    "inventory.current_volume_m3": 0,
}

#: Persistance hebdomadaire de la marche AR(1) en log (0 = bruit blanc pur,
#: 1 = marche aléatoire pure sans retour à la moyenne).
AR1_PHI: float = 0.85

#: Lissage EMA de la composante « dégradation KPI » du stress latent.
EMA_LAM_STRESS: float = 0.35

#: Amplification de la « badness » brute (moyenne de petites déviations,
#: sigma in [0.03, 0.15]) avant son entrée dans l'EMA -- sans ce facteur le
#: stress resterait numériquement négligeable. CALIBRATION DOCUMENTÉE (cf.
#: tests/test_factory_dgp.py::test_average_event_rate_in_target_band) :
#: cette valeur place la MÉDIANE du taux d'évènement par régime, sur
#: l'ensemble du plan QMC (a, b, p_choc, sigma), légèrement au-dessus de la
#: cible de 3-4 %/nœud/semaine. La MOYENNE arithmétique reste plus haute
#: (~6 %) -- irréductible par ce seul paramètre : ``a`` peut atteindre -2 (a
#: est fourni par le plan, hors périmètre U6), ce qui à lui seul donne déjà
#: sigmoid(-2) ≈ 12 % de risque hebdomadaire à stress nul sur CE régime, et
#: la convexité de la sigmoïde gonfle la moyenne (Jensen) sur la queue des
#: régimes (a, b) les plus réactifs. Descendre encore ``kappa`` rapporte de
#: moins en moins (la composante « choc caché », elle aussi non réglable ici
#: -- magnitude U(0.2, 0.5) et p_choc fournis par le plan --, domine alors le
#: résidu) au prix de rendre quasi inerte le canal « dégradation KPI » voulu
#: par le point 3 du DGP.
KAPPA_BADNESS: float = 0.5

#: Décroissance hebdomadaire de la composante « choc caché » du stress.
HIDDEN_DECAY: float = 0.55

#: Taille du tirage de "jitter" pour les paramètres d'évènement -- FIXE,
#: tiré même quand l'évènement ne se déclenche pas (forme fixe CRN).
JITTER_K: int = 3


def draw_kpi_innovations(rng: np.random.Generator, sigma: float) -> dict[str, float]:
    """Tire les 9 innovations AR(1) (une par ``KPI_PATHS``, ordre fixe)."""
    return {path: float(rng.normal(0.0, sigma)) for path in KPI_PATHS}


def badness_from_innovations(innovations: dict[str, float]) -> float:
    """« Norme pondérée des mouvements défavorables » (poids égaux documentés).

    Pour chaque KPI signé (cf. :data:`_ADVERSE_SIGN`), ne retient que la part
    de l'innovation qui va dans le sens DÉFAVORABLE (``max(0, signe·eps)``),
    puis moyenne sur les KPIs retenus (poids égaux -- simplification
    documentée, aucun KPI n'est jugé structurellement plus grave qu'un autre
    au niveau de la dérive).
    """
    contributions = [
        max(0.0, _ADVERSE_SIGN[path] * eps)
        for path, eps in innovations.items()
        if _ADVERSE_SIGN[path] != 0
    ]
    if not contributions:
        return 0.0
    return sum(contributions) / len(contributions)


def ar1_new_value(old: float, baseline: float, eps: float, phi: float = AR1_PHI) -> float:
    """Nouvelle valeur d'un KPI après un pas AR(1) log-normal.

    ``log(new) = phi·log(old) + (1-phi)·log(baseline) + eps`` -- retour
    (partiel) vers la valeur de référence du nœud (sa valeur au tour 0),
    borné positif par construction (marche en log). L'appelant est
    responsable du clamp final via
    :func:`~supplyscore.domain.constraints.clamp_kpi_value`.

    Args:
        old: valeur courante (doit être > 0).
        baseline: valeur de référence du nœud pour ce KPI (doit être > 0).
        eps: innovation tirée (cf. :func:`draw_kpi_innovations`).
        phi: persistance AR(1).

    Returns:
        La nouvelle valeur (> 0).
    """
    log_new = phi * math.log(old) + (1.0 - phi) * math.log(baseline) + eps
    return math.exp(log_new)


# --- 3-4. Stress latent + aléa d'évènement -------------------------------------------


def sigmoid(x: float) -> float:
    """Sigmoïde numériquement stable (jamais d'overflow, quel que soit le signe de x)."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def gravite_bucket(s: float) -> str:
    """Palier de gravité vérité-terrain (tercile du stress) -- vocabulaire commun.

    Réutilisé tel quel pour les évènements ``panne_machine``/``accident``
    (dont les choix ``EventField`` sont exactement ``mineure``/``majeure``/
    ``critique``) et mappé vers le vocabulaire ``alerte_financiere_fournisseur``
    via :data:`_GRAVITE_TO_FINANCE`.
    """
    if s < 1.0 / 3.0:
        return "mineure"
    if s < 2.0 / 3.0:
        return "majeure"
    return "critique"


_GRAVITE_TO_FINANCE: dict[str, str] = {
    "mineure": "surveillee",
    "majeure": "procedure",
    "critique": "defaut",
}

#: Sous-ensemble d'EVENT_CALIBRATION retenu pour le DGP idiosyncratique de
#: cette unité : évènements NŒUD/opérationnels uniquement. Exclus
#: volontairement : hausse_tarif, hausse_energie, instabilite_politique,
#: pic_demande -- évènements de nature MACRO/marché, réservés à un futur DGP
#: piloté par une série macro (cf. le champ ``macro_series_id`` du manifeste,
#: toujours None dans cette version).
EVENT_POOL: tuple[str, ...] = (
    "panne_machine",
    "retard_fournisseur",
    "greve",
    "rupture_matiere",
    "accident",
    "non_conformite_qualite",
    "perturbation_transport",
    "cyber_incident",
    "alerte_financiere_fournisseur",
    "perte_capacite",
)

#: Échelle (heures) au stress=1 des champs numériques "durée" -- intensité
#: proportionnelle au stress avec un peu de bruit (cf. :func:`draw_event_params`).
_HOURS_SCALE: dict[str, float] = {
    "duree_arret_h": 96.0,
    "retard_h": 72.0,
    "duree_prevue_h": 72.0,
}
_HOURS_FLOOR: float = 0.5  # plancher > 0 (les champs "durée" sont strictement positifs)
_SURCOUT_SCALE: float = 3_000.0


def draw_event_params(event_type: str, s: float, jitter: np.ndarray) -> dict[str, float | str]:
    """Paramètres calibrés d'un évènement, intensité proportionnelle au stress ``s``.

    Fonction PURE : ne consomme aucun aléa (le ``jitter`` est déjà tiré par
    l'appelant, cf. :func:`dynamics_week_step` -- forme fixe CRN). Chaque
    champ ``choice`` (gravité) reçoit le palier :func:`gravite_bucket` ; les
    champs numériques sont mis à l'échelle par ``s`` et bornés à la
    spécification de l'évènement.
    """
    spec = EVENT_CALIBRATION[event_type]
    bucket = gravite_bucket(s)
    params: dict[str, float | str] = {}
    for i, f in enumerate(spec.fields):
        j = float(jitter[i % len(jitter)])
        if f.kind == "choice":
            params[f.name] = (
                _GRAVITE_TO_FINANCE[bucket]
                if event_type == "alerte_financiere_fournisseur"
                else bucket
            )
        elif f.name in _HOURS_SCALE:
            base = _HOURS_SCALE[f.name]
            params[f.name] = max(_HOURS_FLOOR, base * s * (0.5 + j))
        elif f.name == "surcout":
            params[f.name] = max(0.0, _SURCOUT_SCALE * s * (0.5 + j))
        else:  # champs ratio : part_effectif, criticite, taux_rebut_obs, pct_volume_perdu
            lo = f.minimum if f.minimum is not None else 0.0
            hi = f.maximum if f.maximum is not None else 1.0
            val = lo + (hi - lo) * min(max(s * (0.6 + 0.5 * j), 0.0), 1.0)
            params[f.name] = val
    return params


@dataclass(frozen=True)
class DynStepResult:
    """Résultat d'un pas hebdomadaire PUR de dynamique latente (cf. :func:`dynamics_week_step`)."""

    stress_kpi: float
    hidden: float
    s: float
    innovations: dict[str, float]
    fires: bool
    event_type: str
    event_params: dict[str, float | str]
    gravite: str


def dynamics_week_step(
    rng: np.random.Generator,
    stress_kpi: float,
    hidden: float,
    regime: Regime,
    mitigation_active: float = 0.0,
) -> DynStepResult:
    """Un pas hebdomadaire PUR de la dynamique latente d'un nœud (aucune IO).

    Tire, dans cet ORDRE FIXE, QUELLE QUE SOIT L'ISSUE :

    1. 9 innovations KPI (:func:`draw_kpi_innovations`) ;
    2. 1 tirage Bernoulli(choc caché) + 1 tirage de magnitude U(0.2, 0.5)
       (le second est TOUJOURS tiré, même si le choc ne se déclenche pas) ;
    3. 1 tirage Bernoulli(aléa d'évènement) ;
    4. 1 tirage d'index de type d'évènement + ``JITTER_K`` tirages de jitter
       (TOUJOURS tirés, même si l'évènement ne se déclenche pas).

    C'est la condition NÉCESSAIRE de la paire CRN (D18) : rejouer cet appel
    depuis un état de générateur CLÔNÉ consomme un flux bit-identique de
    nombres aléatoires bruts, quelle que soit la valeur de
    ``mitigation_active`` -- seule la TRANSFORMATION déterministe diffère
    entre la branche réelle (mitigation_active > 0 si un effet est actif) et
    la branche contrefactuelle (:func:`replay_without_action`,
    ``mitigation_active = 0`` toujours).

    Args:
        rng: générateur du nœud (flux DYNAMIQUE -- jamais partagé avec les
            décisions de l'opérateur synthétique, cf. module ``run_random_campaign``).
        stress_kpi: composante « dégradation KPI » du stress, avant ce pas.
        hidden: composante « choc caché » du stress, avant ce pas.
        regime: régime QMC de la chaîne (a, b, p_choc, sigma).
        mitigation_active: réduction de stress actuellement en vigueur sur ce
            nœud (effet vrai d'une action exécutée récemment) ; 0.0 = aucun
            effet actif (branche contrefactuelle, ou nœud non traité).

    Returns:
        Le :class:`DynStepResult` (nouvel état, stress instantané, tirage
        d'évènement -- déclenché ou non).
    """
    innovations = draw_kpi_innovations(rng, regime.sigma)
    badness = badness_from_innovations(innovations)
    new_stress_kpi = (
        EMA_LAM_STRESS * (KAPPA_BADNESS * badness) + (1.0 - EMA_LAM_STRESS) * stress_kpi
    )
    new_stress_kpi = min(max(new_stress_kpi, 0.0), 1.0)

    hidden_bernoulli_u = rng.random()
    hidden_magnitude_u = rng.uniform(0.2, 0.5)  # toujours tiré (forme fixe)
    hit = hidden_bernoulli_u < regime.p_choc
    new_hidden = hidden * HIDDEN_DECAY + (hidden_magnitude_u if hit else 0.0)
    new_hidden = min(max(new_hidden, 0.0), 1.0)

    s = min(max(new_stress_kpi + new_hidden - mitigation_active, 0.0), 1.0)

    hazard_u = rng.random()
    h = sigmoid(regime.a + regime.b * s)
    fires = hazard_u < h

    type_idx = int(rng.integers(0, len(EVENT_POOL)))
    jitter = rng.random(JITTER_K)  # toujours tiré (forme fixe)
    event_type = EVENT_POOL[type_idx]
    bucket = gravite_bucket(s)
    params = draw_event_params(event_type, s, jitter)

    return DynStepResult(
        stress_kpi=new_stress_kpi,
        hidden=new_hidden,
        s=s,
        innovations=innovations,
        fires=fires,
        event_type=event_type,
        event_params=params,
        gravite=bucket,
    )


def replay_without_action(
    rng_state: Any,
    stress_kpi0: float,
    hidden0: float,
    regime: Regime,
    skip_weeks: int = 0,
    weeks: int = 4,
) -> bool:
    """Rejoue la fenêtre SANS l'action (bras contrefactuel de la paire CRN, D18).

    ``rng_state`` DOIT être un état déjà CLÔNÉ (``copy.deepcopy``) du flux
    dynamique du nœud, capturé à l'instant de l'exécution de l'action -- le
    clone est indépendant de l'original : la branche réelle continue sur SON
    PROPRE générateur, non affectée par cet appel. Les ``skip_weeks``
    premiers pas sont rejoués mais IGNORÉS (ils correspondent aux semaines
    entre l'exécution et ``date_effet`` -- identiques dans les deux branches
    puisque l'effet n'a pas encore commencé, mais il FAUT quand même les
    tirer pour garder le générateur synchronisé avec la branche réelle avant
    de comparer la fenêtre [date_effet, date_effet+weeks)).

    Args:
        rng_state: état clôné du générateur dynamique du nœud.
        stress_kpi0: composante « dégradation KPI » du stress à l'instant du clone.
        hidden0: composante « choc caché » du stress à l'instant du clone.
        regime: régime QMC de la chaîne.
        skip_weeks: nombre de pas à rejouer sans les compter dans le résultat.
        weeks: taille de la fenêtre comparée (4 semaines par défaut, D18).

    Returns:
        True si au moins un évènement se serait déclenché sur la fenêtre
        SANS l'action.
    """
    shadow = np.random.default_rng()
    shadow.bit_generator.state = copy.deepcopy(rng_state)
    stress_kpi, hidden = stress_kpi0, hidden0
    for _ in range(max(0, skip_weeks)):
        result = dynamics_week_step(shadow, stress_kpi, hidden, regime, mitigation_active=0.0)
        stress_kpi, hidden = result.stress_kpi, result.hidden
    issue = False
    for _ in range(weeks):
        result = dynamics_week_step(shadow, stress_kpi, hidden, regime, mitigation_active=0.0)
        stress_kpi, hidden = result.stress_kpi, result.hidden
        issue = issue or result.fires
    return issue


# --- 5. Opérateur synthétique confondu sur le stress LATENT --------------------------

#: sigmoid(c0 + c1·s) -- confusion partielle PAR CONSTRUCTION (D21/D32) :
#: s n'est JAMAIS observable dans ctx/etat_avant, seule cette probabilité en dépend.
C0_OPERATOR: float = -3.0
C1_OPERATOR: float = 4.0


def decide_probability(s: float) -> float:
    """P(décider d'agir) = sigmoid(c0 + c1·s) -- s est le stress LATENT, jamais loggé."""
    return sigmoid(C0_OPERATOR + C1_OPERATOR * min(max(s, 0.0), 1.0))


# --- 6. Exécution imparfaite (D29) ---------------------------------------------------

DEFAULT_P_ECHEC_EXECUTION: float = 0.15

# --- 7. Effet vrai heterogene par segment ---------------------------------------------

#: Rang <= ce seuil : segment "proche" (client) ; au-delà : "profond" (amont).
RANK_PROCHE_MAX: int = 2

#: Fraction de réduction KPI/temps appliquée par les actions du repli, par segment.
EFFET_SEGMENT: dict[str, float] = {"proche": 0.35, "profond": 0.18}

EFFECT_WINDOW_WEEKS: int = 4

#: Facteur de conversion "réduction observée de ur_local" -> "mitigation_active"
#: et plafond de sécurité.
#:
#: CALIBRATION DOCUMENTÉE (mesurée par simulation, cf.
#: tests/test_factory_dgp.py) : ur_local agrège plusieurs blocs par une
#: combine log-survie (OU probabiliste) -- une action qui améliore un seul
#: bloc (ex. lead_time/failure_probability pour ``expedition_express``) ne
#: déplace souvent ur_local QUE de quelques millièmes quand un autre bloc
#: (ex. jalon en retard) domine déjà l'agrégat. Sans amplification,
#: ``mitigation_active`` resterait quasi nul et la paire CRN ne ferait
#: JAMAIS diverger les deux branches -- ``delta_u_vrai`` resterait TOUJOURS à
#: 0.0, ce qui viderait le jeu de vérité contrefactuelle de tout signal
#: causal exploitable (c'est ce signal que U17 exploite en aval).
#:
#: K_MITIG=25 amplifie donc le delta OBSERVÉ à un ordre de grandeur
#: comparable au stress latent typique. PLAFOND THÉORIQUE mesuré par
#: simulation directe (geler ``mitigation_active`` à une valeur FIXE et
#: comparer les branches avec/sans sur de nombreux tirages, indépendamment de
#: K_MITIG) : même avec une mitigation totale (s ramené à 0), le taux
#: d'interventions dont l'issue à 4 semaines DIFFÈRE entre les deux branches
#: plafonne à ~5-6 % avec le taux d'évènement calibré ici (~3-4 %/semaine,
#: cf. KAPPA_BADNESS) -- borne mathématique du problème (on ne peut pas «
#: annuler » un évènement qui n'avait de toute façon qu'une faible chance de
#: se produire dans la fenêtre), PAS un artefact de K_MITIG. À K_MITIG=25,
#: les interventions dont l'effet observé est substantiel (grosso modo
#: mitigation_active >= 0.2-0.3) approchent déjà ce plafond ; celles à effet
#: quasi nul restent, à raison, quasi sans influence sur l'issue -- un
#: résultat RÉALISTE (comme en inférence causale sur évènements rares : la
#: majorité des unités traitées ne voient pas leur issue s'inverser, seule
#: une fraction minoritaire mais non nulle en bénéficie) plutôt qu'un
#: mécanisme « l'action réussit toujours ». MAX_MITIGATION plafonne le
#: résultat par sécurité (jamais de stress négatif).
K_MITIG: float = 25.0
MAX_MITIGATION: float = 0.9


def segment_of(rank: int) -> str:
    """Segment d'un nœud selon son rang -- ``"proche"`` (client) ou ``"profond"`` (amont)."""
    return "proche" if rank <= RANK_PROCHE_MAX else "profond"


# --- Catalogue d'actions (repli local si supplyscore.domain.actions absent) ----------


@dataclass(frozen=True)
class Action:
    """Action du catalogue -- interface duck-typée partagée avec ``CATALOGUE_V1`` (U15).

    Attributes:
        id: identifiant stable de l'action.
        libelle: libellé français court.
        preconditions: ``ctx (observable) -> bool`` -- éligibilité de l'action.
        apply_to_rollout: ``state -> state`` -- effet PUR sur un état de rollout
            abstrait (identité pour le repli -- cf. note de module sur le
            découplage volontaire du calcul de mitigation interne du DGP).
        apply_to_project: ``(service, node_id) -> None`` -- effet RÉEL en base.
        delai_effet_weeks: ``(min, mode, max)`` -- triangulaire, en semaines.
        cout: coût nominal de l'action.
        risque_secondaire: risque secondaire dans [0, 1].
        incompatibles: ids d'actions incompatibles.
        objectifs_operationnels: liste de ``{"kpi", "direction", "seuil"}``.
    """

    id: str
    libelle: str
    preconditions: Callable[[dict[str, Any]], bool]
    apply_to_rollout: Callable[[dict[str, Any]], dict[str, Any]]
    apply_to_project: Callable[[Any, str], None]
    delai_effet_weeks: tuple[float, float, float]
    cout: float
    risque_secondaire: float
    incompatibles: tuple[str, ...]
    objectifs_operationnels: tuple[dict[str, Any], ...]


def _rollout_identity(state: dict[str, Any]) -> dict[str, Any]:
    """Effet de rollout du repli : identité documentée (cf. :class:`Action`)."""
    return dict(state)


def _apply_ne_rien_faire(service: Any, node_id: str) -> None:
    """Aucun effet -- documenté."""
    del service, node_id


def _apply_expedition_express(service: Any, node_id: str) -> None:
    """Réduit lead time et probabilité de défaillance, proportionnellement au segment."""
    node = service.registry.get_node(node_id)
    if node is None:
        return
    factor = EFFET_SEGMENT[segment_of(node.rank)]
    changes: dict[str, float | None] = {}
    lead_time = node.kpis.time.lead_time_h
    if lead_time is not None:
        changes["time.lead_time_h"] = max(1.0, lead_time * (1.0 - factor))
    failure_p = node.kpis.risk.failure_probability
    if failure_p is not None:
        changes["risk.failure_probability"] = max(1e-4, failure_p * (1.0 - factor))
    if changes:
        service.mutations.update_kpis(
            node_id, changes, source="dgp:action:expedition_express", operator_id="dgp"
        )


def _apply_replanifier_jalon(service: Any, node_id: str) -> None:
    """Repousse l'échéance du jalon actif, proportionnellement au segment."""
    from supplyscore.domain.milestones import next_active_milestone

    milestones = service.registry.list_milestones(node_id)
    actif = next_active_milestone(milestones)
    if actif is None:
        return
    node = service.registry.get_node(node_id)
    factor = EFFET_SEGMENT[segment_of(node.rank)] if node is not None else EFFET_SEGMENT["profond"]
    extension_s = max(0.0, actif.deadline_ts - actif.start_ts) * factor
    service.mutations.update_milestone(
        actif.id,
        {"deadline_ts": actif.deadline_ts + extension_s},
        source="dgp:action:replanifier_jalon",
        operator_id="dgp",
    )


FALLBACK_CATALOGUE: dict[str, Action] = {
    "ne_rien_faire": Action(
        id="ne_rien_faire",
        libelle="Ne rien faire",
        preconditions=lambda ctx: True,
        apply_to_rollout=_rollout_identity,
        apply_to_project=_apply_ne_rien_faire,
        delai_effet_weeks=(0.0, 0.0, 0.0),
        cout=0.0,
        risque_secondaire=0.0,
        incompatibles=(),
        objectifs_operationnels=(),
    ),
    "expedition_express": Action(
        id="expedition_express",
        libelle="Expédition express",
        preconditions=lambda ctx: (ctx.get("ur_local") or 0.0) > 0.25,
        apply_to_rollout=_rollout_identity,
        apply_to_project=_apply_expedition_express,
        delai_effet_weeks=(0.0, 1.0, 2.0),
        cout=500.0,
        risque_secondaire=0.10,
        incompatibles=(),
        objectifs_operationnels=({"kpi": "ur_local", "direction": "decrease", "seuil": 0.15},),
    ),
    "replanifier_jalon": Action(
        id="replanifier_jalon",
        libelle="Replanifier le jalon",
        preconditions=lambda ctx: bool(ctx.get("has_active_milestone")),
        apply_to_rollout=_rollout_identity,
        apply_to_project=_apply_replanifier_jalon,
        delai_effet_weeks=(1.0, 2.0, 4.0),
        cout=100.0,
        risque_secondaire=0.05,
        incompatibles=(),
        objectifs_operationnels=({"kpi": "ur_local", "direction": "decrease", "seuil": 0.10},),
    ),
}


def load_action_catalogue() -> dict[str, Any]:
    """Catalogue d'actions : ``CATALOGUE_V1`` (U15) si disponible, sinon repli local.

    Le repli expose la MÊME interface duck-typée que documentée (id, libelle,
    preconditions(ctx)->bool, apply_to_rollout(state)->state,
    apply_to_project(service, node_id), delai_effet_weeks, cout,
    risque_secondaire, incompatibles, objectifs_operationnels) et couvre au
    moins ``expedition_express``, ``replanifier_jalon``, ``ne_rien_faire``.
    """
    try:
        from supplyscore.domain.actions import CATALOGUE_V1  # type: ignore[import-not-found]
    except ImportError:
        return dict(FALLBACK_CATALOGUE)
    return dict(CATALOGUE_V1)


def objectif_atteint(
    action: Any, ur_local_avant: float | None, ur_local_apres: float | None
) -> bool:
    """True si au moins un objectif opérationnel « ur_local en baisse » est atteint."""
    if ur_local_avant is None or ur_local_apres is None:
        return False
    objectifs = getattr(action, "objectifs_operationnels", None) or ()
    for obj in objectifs:
        if (
            obj.get("kpi") == "ur_local"
            and obj.get("direction") == "decrease"
            and (ur_local_avant - ur_local_apres) >= obj.get("seuil", 1.0)
        ):
            return True
    return False


# --- Déclarant synthétique (palier 0) et pont bipolaire/Saaty ------------------------

#: Échelle de Saaty (17 points, identique à celle utilisée par
#: ``supplyscore.data.generator`` et à celle produite par
#: ``supplyscore.core.ahp.bipolar_to_saaty`` sur [-8, 8]) -- redéfinie
#: localement (API privée du générateur, non importée).
_SAATY_SCALE: tuple[float, ...] = tuple(
    [1.0 / k for k in range(9, 1, -1)] + [float(k) for k in range(1, 10)]
)

#: Les 6 paires de comparaison des 4 critères AHP, dans l'ordre attendu par
#: ``build_assessment`` (mêmes indices que ``supplyscore.core.ahp.CRITERIA``).
PAIRS: tuple[tuple[int, int], ...] = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))


def _bipolar_from_saaty(value: float) -> int:
    """Inverse exacte de ``bipolar_to_saaty`` sur les 17 points de l'échelle de Saaty."""
    if value >= 1.0:
        return round(value - 1.0)
    return round(1.0 - 1.0 / value)


def synthetic_respond(
    node_id: str,
    tour: int,
    features: dict[str, Any],
    rng: np.random.Generator,
    bias: float = 0.0,
) -> dict[str, list[int]]:
    """Déclarant synthétique de palier 0 -- ancré sur ``ur_local`` (OBSERVABLE).

    Respecte le contrat figé ``respond(node_id, tour, features, rng) ->
    {"bipolar": [6 int -8..8], "scores_ui": [4 int 1..6]}`` utilisé pour les
    paliers 1/2 (``--behavior``). ``features`` ne doit contenir QUE des
    grandeurs observables (jamais le stress latent -- cf. note de module).
    ``bias`` est le biais du nœud, tiré UNE FOIS par chaîne (perception
    personnelle stable du déclarant simulé).

    Les 4 poids-cibles (positifs) sont dérivés de l'urgence perçue, puis les
    6 comparaisons bipolaires sont dérivées des RATIOS de ces poids (comme
    ``RandomSupplyChainGenerator.generate_assessment``) -- garantit un
    ratio de cohérence de Saaty quasi toujours < 0.10, contrairement à 6
    tirages bipolaires indépendants (généralement incohérents pour 4 critères).

    Args:
        node_id: identifiant du nœud (non utilisé par ce déclarant, présent
            pour respecter le contrat ``respond``).
        tour: numéro du tour (non utilisé par ce déclarant).
        features: dictionnaire observable (``ur_local`` notamment).
        rng: générateur du nœud (flux OPÉRATEUR -- jamais le flux dynamique).
        bias: biais de perception du nœud, stable sur la chaîne.

    Returns:
        ``{"bipolar": [...6 int...], "scores_ui": [...4 int...]}``.
    """
    del node_id, tour
    ur_local = features.get("ur_local")
    perceived = min(max((ur_local or 0.0) + bias + rng.normal(0.0, 0.08), 0.0), 1.0)
    target = [max(0.05, 1.0 + perceived * 3.0 + rng.normal(0.0, 0.4)) for _ in range(4)]
    bipolar: list[int] = []
    for i, j in PAIRS:
        ratio = target[i] / target[j]
        snapped = min(_SAATY_SCALE, key=lambda s: abs(s - ratio))
        bipolar.append(max(-8, min(8, _bipolar_from_saaty(snapped))))
    scores_ui = [
        round(min(max(1.0 + perceived * 5.0 + rng.normal(0.0, 0.6), 1.0), 6.0)) for _ in range(4)
    ]
    return {"bipolar": bipolar, "scores_ui": scores_ui}


def response_to_ahp_inputs(
    response: dict[str, list[int]],
) -> tuple[dict[tuple[int, int], float], list[float]]:
    """Convertit une réponse ``{"bipolar", "scores_ui"}`` en entrées de ``build_assessment``.

    Raises:
        ValueError: réponse malformée (mauvaise longueur des listes).
    """
    from supplyscore.core.ahp import bipolar_to_saaty, score_6_to_9

    bipolar = response["bipolar"]
    scores_ui = response["scores_ui"]
    if len(bipolar) != 6 or len(scores_ui) != 4:
        raise ValueError(
            f"Réponse déclarant malformée : bipolar={bipolar!r} scores_ui={scores_ui!r}"
        )
    comparisons = {pair: bipolar_to_saaty(v) for pair, v in zip(PAIRS, bipolar, strict=True)}
    criteria_scores = [score_6_to_9(v) for v in scores_ui]
    return comparisons, criteria_scores
