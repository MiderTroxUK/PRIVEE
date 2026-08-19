"""DGP (processus generateur de donnees) versionne pour l'usine de campagnes U6.

Ce module est PUR (aucune ecriture DB, aucun import de service au chargement) :
il ne fait que definir la mecanique stochastique de la campagne. L'orchestration
(ouverture du service, boucle hebdomadaire, ecriture des fichiers) vit dans
``run_random_campaign.py``, qui importe ce module.

Sommaire :

1. **Plan QMC** (:func:`sample_regimes`) : echantillonne l'espace des regimes
   (n_ranks, a, b, p_choc, sigma) par sequence de Sobol -- une chaine = un
   point du plan, mieux reparti qu'un tirage i.i.d. sur le lot de chaines.
2. **Derive hebdomadaire des KPIs** (:func:`draw_kpi_innovations`) : marche
   AR(1) log-normale par (noeud, kpi_path), bornee via
   :func:`~supplyscore.domain.constraints.clamp_kpi_value`.
3. **Stress latent** ``s_i(t)`` : EMA de la " badness " tiree des innovations
   KPI (:func:`badness_from_innovations`) + chocs caches Bernoulli(p_choc)
   decroissants (:func:`dynamics_week_step`).
4. **Alea d'evenement** : ``h_i(t) = sigmoid(a + b-s_i(t))`` ; le type et la
   gravite sont tires PROPORTIONNELLEMENT au stress (:func:`draw_event_params`,
   :func:`gravite_bucket`).
5. **Operateur synthetique confondu** (:func:`decide_probability`) : la
   decision d'agir depend du stress LATENT (``c0 + c1-s``), jamais logge --
   c'est la confusion partielle voulue par le plan (D21/D32).
6. **Execution imparfaite** (D29) : probabilite ``1 - p_echec`` par intervention.
7. **Effet vrai + paire CRN** (D18) : :func:`replay_without_action` rejoue la
   fenetre SANS l'action sur un clone de l'etat du generateur -- meme flux de
   nombres aleatoires que la branche reelle, seule la transformation change.

CHOIX DOCUMENTE (isolation CRN) : :func:`dynamics_week_step` tire un nombre
FIXE de valeurs aleatoires, dans un ORDRE FIXE, quelle que soit l'issue
(choc cache declenche ou non, evenement declenche ou non). C'est la condition
necessaire et suffisante pour que le clone d'un etat de generateur rejoue un
flux bit-identique : si le nombre ou l'ordre des tirages dependait de l'issue,
les deux branches desynchroniseraient leur generateur des la premiere semaine
ou elles divergent.

CHOIX DOCUMENTE (pas de fuite du latent) : le stress ``s_i(t)`` n'est JAMAIS
inclus dans les structures observables (``ctx`` / ``etat_avant`` des
interventions) -- seuls ``ur_local``, ``ud_local``, ``adequation``,
``false_urgency``, ``hidden_risk`` et les KPIs bruts y figurent. Le stress ne
sert qu'en interne, pour calculer l'alea d'evenement et la probabilite de
decision de l'operateur synthetique.
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

# 1. Plan QMC sur l'espace des regimes

#: Choix discrets de n_ranks, indexes par le premier axe du plan de Sobol.
N_RANKS_CHOICES: tuple[int, ...] = (3, 4, 5, 6, 7)
A_BOUNDS: tuple[float, float] = (-5.0, -2.0)
B_BOUNDS: tuple[float, float] = (3.0, 8.0)
P_CHOC_BOUNDS: tuple[float, float] = (0.01, 0.08)
SIGMA_BOUNDS: tuple[float, float] = (0.03, 0.15)


@dataclass(frozen=True)
class Regime:
    """Regime stochastique d'une chaine (un point du plan QMC).

    Attributes:
        n_ranks: profondeur du DAG (passe tel quel a ``seed_demo``).
        a: ordonnee a l'origine de l'alea d'evenement (sigmoid).
        b: sensibilite de l'alea d'evenement au stress latent.
        p_choc: probabilite hebdomadaire d'un choc cache par noeud.
        sigma: ecart-type des innovations de la marche AR(1) log-normale.
    """

    n_ranks: int
    a: float
    b: float
    p_choc: float
    sigma: float

    @property
    def params_id(self) -> str:
        """Hash court (10 hex) des parametres arrondis -- identifiant stable du regime."""
        payload = (
            f"{round(self.a, 4)}|{round(self.b, 4)}|{round(self.p_choc, 4)}|{round(self.sigma, 4)}"
        )
        return hashlib.sha1(payload.encode()).hexdigest()[:10]


def sample_regimes(seed: int, n_chains: int) -> list[Regime]:
    """Echantillonne ``n_chains`` regimes par sequence de Sobol scramblee.

    Un plan QMC (plutot qu'un tirage i.i.d.) repartit mieux le lot de chaines
    sur l'espace des regimes -- couverture uniforme meme pour un petit nombre
    de chaines. Le premier axe du plan (dans [0, 1)) choisit ``n_ranks`` par
    seau ; les quatre autres sont mis a l'echelle des bornes documentees.

    Args:
        seed: graine du plan (deterministe -- meme seed -> meme plan).
        n_chains: nombre de chaines (donc de points du plan), >= 1.

    Returns:
        Une liste de :class:`Regime`, un par chaine, dans l'ordre du plan.
    """
    if n_chains < 1:
        raise ValueError(f"n_chains doit être >= 1, reçu {n_chains}")
    with warnings.catch_warnings():
        # Sobol avertit quand n_chains n'est pas une puissance de 2 (propriete de balance non garantie) -- sans consequence pour un plan de regimes, seule la COUVERTURE compte ici, pas la balance exacte.
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
    """Sous-graine deterministe derivee de ``parts`` (hash stable SHA256).

    Independant de ``PYTHONHASHSEED`` (contrairement a ``hash()`` sur des
    chaines) -- reproductible d'un run a l'autre et d'une machine a l'autre.
    """
    payload = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(payload.encode()).digest()
    return int.from_bytes(digest[:8], "big")


def dgp_manifest(regime: Regime, seed: int) -> dict[str, Any]:
    """Contenu de ``dgp_manifest.json`` pour une chaine (schema fige + extras documentes)."""
    return {
        "a": regime.a,
        "b": regime.b,
        "p_choc": regime.p_choc,
        "sigma": regime.sigma,
        "dgp_params_id": regime.params_id,
        "macro_series_id": None,  # reserve a un futur DGP pilote par une serie macro (hors U6)
        "n_ranks": regime.n_ranks,
        "seed": seed,
        "effet_action_segment": dict(EFFET_SEGMENT),
        "p_echec_execution_defaut": DEFAULT_P_ECHEC_EXECUTION,
        "effect_window_weeks": EFFECT_WINDOW_WEEKS,
        "rank_proche_max": RANK_PROCHE_MAX,
    }


# 2. Derive hebdomadaire des KPIs

#: Les 9 chemins de KPI pilotes par la derive (memes que ``make_briefings.FIELD_LABELS``), ordre FIXE (forme fixe des tirages CRN).
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

#: Convention de signe : +1 si une innovation POSITIVE (en log) est un signe de degradation pour ce KPI, -1 si c'est une innovation NEGATIVE, 0 si le KPI est exclu de la mesure de " badness " (niveau de stock : ni bon ni mauvais en soi, seul un depassement de borne compterait, hors perimetre).
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

#: Persistance hebdomadaire de la marche AR(1) en log (0 = bruit blanc pur, 1 = marche aleatoire pure sans retour a la moyenne).
AR1_PHI: float = 0.85

#: Lissage EMA de la composante " degradation KPI " du stress latent.
EMA_LAM_STRESS: float = 0.35

#: Amplification de la badness brute avant l'EMA ; sans elle le stress reste negligeable. A 0.5 la mediane du taux d'evenement par regime tient juste au-dessus de la cible 3-4 %/noeud/semaine (moyenne ~6 %, gonflee par Jensen sur les regimes a faible a). cf. tests/test_factory_dgp.py::test_average_event_rate_in_target_band
KAPPA_BADNESS: float = 0.5

#: Decroissance hebdomadaire de la composante " choc cache " du stress.
HIDDEN_DECAY: float = 0.55

#: Taille du tirage de "jitter" pour les parametres d'evenement -- FIXE, tire meme quand l'evenement ne se declenche pas (forme fixe CRN).
JITTER_K: int = 3


def draw_kpi_innovations(rng: np.random.Generator, sigma: float) -> dict[str, float]:
    """Tire les 9 innovations AR(1) (une par ``KPI_PATHS``, ordre fixe)."""
    return {path: float(rng.normal(0.0, sigma)) for path in KPI_PATHS}


def badness_from_innovations(innovations: dict[str, float]) -> float:
    """" Norme ponderee des mouvements defavorables " (poids egaux documentes).

    Pour chaque KPI signe (cf. :data:`_ADVERSE_SIGN`), ne retient que la part
    de l'innovation qui va dans le sens DEFAVORABLE (``max(0, signe-eps)``),
    puis moyenne sur les KPIs retenus (poids egaux -- simplification
    documentee, aucun KPI n'est juge structurellement plus grave qu'un autre
    au niveau de la derive).
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
    """Nouvelle valeur d'un KPI apres un pas AR(1) log-normal.

    ``log(new) = phi-log(old) + (1-phi)-log(baseline) + eps`` -- retour
    (partiel) vers la valeur de reference du noeud (sa valeur au tour 0),
    borne positif par construction (marche en log). L'appelant est
    responsable du clamp final via
    :func:`~supplyscore.domain.constraints.clamp_kpi_value`.

    Args:
        old: valeur courante (doit etre > 0).
        baseline: valeur de reference du noeud pour ce KPI (doit etre > 0).
        eps: innovation tiree (cf. :func:`draw_kpi_innovations`).
        phi: persistance AR(1).

    Returns:
        La nouvelle valeur (> 0).
    """
    log_new = phi * math.log(old) + (1.0 - phi) * math.log(baseline) + eps
    return math.exp(log_new)


# 3-4. Stress latent + alea d'evenement


def sigmoid(x: float) -> float:
    """Sigmoide numeriquement stable (jamais d'overflow, quel que soit le signe de x)."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def gravite_bucket(s: float) -> str:
    """Palier de gravite verite-terrain (tercile du stress) -- vocabulaire commun.

    Reutilise tel quel pour les evenements ``panne_machine``/``accident``
    (dont les choix ``EventField`` sont exactement ``mineure``/``majeure``/
    ``critique``) et mappe vers le vocabulaire ``alerte_financiere_fournisseur``
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

#: Sous-ensemble d'EVENT_CALIBRATION retenu pour le DGP idiosyncratique de cette unite : evenements NOEUD/operationnels uniquement. Exclus volontairement : hausse_tarif, hausse_energie, instabilite_politique, pic_demande -- evenements de nature MACRO/marche, reserves a un futur DGP pilote par une serie macro (cf. le champ ``macro_series_id`` du manifeste, toujours None dans cette version).
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

#: Echelle (heures) au stress=1 des champs numeriques "duree" -- intensite proportionnelle au stress avec un peu de bruit (cf. :func:`draw_event_params`).
_HOURS_SCALE: dict[str, float] = {
    "duree_arret_h": 96.0,
    "retard_h": 72.0,
    "duree_prevue_h": 72.0,
}
_HOURS_FLOOR: float = 0.5  # plancher > 0 (les champs "duree" sont strictement positifs)
_SURCOUT_SCALE: float = 3_000.0


def draw_event_params(event_type: str, s: float, jitter: np.ndarray) -> dict[str, float | str]:
    """Parametres calibres d'un evenement, intensite proportionnelle au stress ``s``.

    Fonction PURE : ne consomme aucun alea (le ``jitter`` est deja tire par
    l'appelant, cf. :func:`dynamics_week_step` -- forme fixe CRN). Chaque
    champ ``choice`` (gravite) recoit le palier :func:`gravite_bucket` ; les
    champs numeriques sont mis a l'echelle par ``s`` et bornes a la
    specification de l'evenement.
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
    """Resultat d'un pas hebdomadaire PUR de dynamique latente (cf. :func:`dynamics_week_step`)."""

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
    """Un pas hebdomadaire PUR de la dynamique latente d'un noeud (aucune IO).

    Tire, dans cet ORDRE FIXE, QUELLE QUE SOIT L'ISSUE :

    1. 9 innovations KPI (:func:`draw_kpi_innovations`) ;
    2. 1 tirage Bernoulli(choc cache) + 1 tirage de magnitude U(0.2, 0.5)
       (le second est TOUJOURS tire, meme si le choc ne se declenche pas) ;
    3. 1 tirage Bernoulli(alea d'evenement) ;
    4. 1 tirage d'index de type d'evenement + ``JITTER_K`` tirages de jitter
       (TOUJOURS tires, meme si l'evenement ne se declenche pas).

    C'est la condition NECESSAIRE de la paire CRN (D18) : rejouer cet appel
    depuis un etat de generateur CLONE consomme un flux bit-identique de
    nombres aleatoires bruts, quelle que soit la valeur de
    ``mitigation_active`` -- seule la TRANSFORMATION deterministe differe
    entre la branche reelle (mitigation_active > 0 si un effet est actif) et
    la branche contrefactuelle (:func:`replay_without_action`,
    ``mitigation_active = 0`` toujours).

    Args:
        rng: generateur du noeud (flux DYNAMIQUE -- jamais partage avec les
            decisions de l'operateur synthetique, cf. module ``run_random_campaign``).
        stress_kpi: composante " degradation KPI " du stress, avant ce pas.
        hidden: composante " choc cache " du stress, avant ce pas.
        regime: regime QMC de la chaine (a, b, p_choc, sigma).
        mitigation_active: reduction de stress actuellement en vigueur sur ce
            noeud (effet vrai d'une action executee recemment) ; 0.0 = aucun
            effet actif (branche contrefactuelle, ou noeud non traite).

    Returns:
        Le :class:`DynStepResult` (nouvel etat, stress instantane, tirage
        d'evenement -- declenche ou non).
    """
    innovations = draw_kpi_innovations(rng, regime.sigma)
    badness = badness_from_innovations(innovations)
    new_stress_kpi = (
        EMA_LAM_STRESS * (KAPPA_BADNESS * badness) + (1.0 - EMA_LAM_STRESS) * stress_kpi
    )
    new_stress_kpi = min(max(new_stress_kpi, 0.0), 1.0)

    hidden_bernoulli_u = rng.random()
    hidden_magnitude_u = rng.uniform(0.2, 0.5)  # toujours tire (forme fixe)
    hit = hidden_bernoulli_u < regime.p_choc
    new_hidden = hidden * HIDDEN_DECAY + (hidden_magnitude_u if hit else 0.0)
    new_hidden = min(max(new_hidden, 0.0), 1.0)

    s = min(max(new_stress_kpi + new_hidden - mitigation_active, 0.0), 1.0)

    hazard_u = rng.random()
    h = sigmoid(regime.a + regime.b * s)
    fires = hazard_u < h

    type_idx = int(rng.integers(0, len(EVENT_POOL)))
    jitter = rng.random(JITTER_K)  # toujours tire (forme fixe)
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
    """Rejoue la fenetre SANS l'action (bras contrefactuel de la paire CRN, D18).

    ``rng_state`` DOIT etre un etat deja CLONE (``copy.deepcopy``) du flux
    dynamique du noeud, capture a l'instant de l'execution de l'action -- le
    clone est independant de l'original : la branche reelle continue sur SON
    PROPRE generateur, non affectee par cet appel. Les ``skip_weeks``
    premiers pas sont rejoues mais IGNORES (ils correspondent aux semaines
    entre l'execution et ``date_effet`` -- identiques dans les deux branches
    puisque l'effet n'a pas encore commence, mais il FAUT quand meme les
    tirer pour garder le generateur synchronise avec la branche reelle avant
    de comparer la fenetre [date_effet, date_effet+weeks)).

    Args:
        rng_state: etat clone du generateur dynamique du noeud.
        stress_kpi0: composante " degradation KPI " du stress a l'instant du clone.
        hidden0: composante " choc cache " du stress a l'instant du clone.
        regime: regime QMC de la chaine.
        skip_weeks: nombre de pas a rejouer sans les compter dans le resultat.
        weeks: taille de la fenetre comparee (4 semaines par defaut, D18).

    Returns:
        True si au moins un evenement se serait declenche sur la fenetre
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


# 5. Operateur synthetique confondu sur le stress LATENT

#: sigmoid(c0 + c1-s) -- confusion partielle PAR CONSTRUCTION (D21/D32) : s n'est JAMAIS observable dans ctx/etat_avant, seule cette probabilite en depend.
C0_OPERATOR: float = -3.0
C1_OPERATOR: float = 4.0


def decide_probability(s: float) -> float:
    """P(decider d'agir) = sigmoid(c0 + c1-s) -- s est le stress LATENT, jamais logge."""
    return sigmoid(C0_OPERATOR + C1_OPERATOR * min(max(s, 0.0), 1.0))


# 6. Execution imparfaite (D29)

DEFAULT_P_ECHEC_EXECUTION: float = 0.15

# 7. Effet vrai heterogene par segment

#: Rang <= ce seuil : segment "proche" (client) ; au-dela : "profond" (amont).
RANK_PROCHE_MAX: int = 2

#: Fraction de reduction KPI/temps appliquee par les actions du repli, par segment.
EFFET_SEGMENT: dict[str, float] = {"proche": 0.35, "profond": 0.18}

EFFECT_WINDOW_WEEKS: int = 4

#: Amplification du delta ur_local observe vers mitigation_active, plus son plafond. Sans elle delta_u_vrai reste a 0.0 et les branches CRN ne divergent jamais. Plafond mesure : ~5-6 % d'issues a 4 semaines qui different entre branches. cf. tests/test_factory_dgp.py
K_MITIG: float = 25.0
MAX_MITIGATION: float = 0.9


def segment_of(rank: int) -> str:
    """Segment d'un noeud selon son rang -- ``"proche"`` (client) ou ``"profond"`` (amont)."""
    return "proche" if rank <= RANK_PROCHE_MAX else "profond"


# Catalogue d'actions (repli local si supplyscore.domain.actions absent)


@dataclass(frozen=True)
class Action:
    """Action du catalogue -- interface duck-typee partagee avec ``CATALOGUE_V1`` (U15).

    Attributes:
        id: identifiant stable de l'action.
        libelle: libelle francais court.
        preconditions: ``ctx (observable) -> bool`` -- eligibilite de l'action.
        apply_to_rollout: ``state -> state`` -- effet PUR sur un etat de rollout
            abstrait (identite pour le repli -- cf. note de module sur le
            decouplage volontaire du calcul de mitigation interne du DGP).
        apply_to_project: ``(service, node_id) -> None`` -- effet REEL en base.
        delai_effet_weeks: ``(min, mode, max)`` -- triangulaire, en semaines.
        cout: cout nominal de l'action.
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
    """Effet de rollout du repli : identite documentee (cf. :class:`Action`)."""
    return dict(state)


def _apply_ne_rien_faire(service: Any, node_id: str) -> None:
    """Aucun effet -- documente."""
    del service, node_id


def _apply_expedition_express(service: Any, node_id: str) -> None:
    """Reduit lead time et probabilite de defaillance, proportionnellement au segment."""
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
    """Repousse l'echeance du jalon actif, proportionnellement au segment."""
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

    Le repli expose la MEME interface duck-typee que documentee (id, libelle,
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
    """True si au moins un objectif operationnel " ur_local en baisse " est atteint."""
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


# Declarant synthetique (palier 0) et pont bipolaire/Saaty

#: Echelle de Saaty (17 points, identique a celle utilisee par ``supplyscore.data.generator`` et a celle produite par ``supplyscore.core.ahp.bipolar_to_saaty`` sur [-8, 8]) -- redefinie localement (API privee du generateur, non importee).
_SAATY_SCALE: tuple[float, ...] = tuple(
    [1.0 / k for k in range(9, 1, -1)] + [float(k) for k in range(1, 10)]
)

#: Les 6 paires de comparaison des 4 criteres AHP, dans l'ordre attendu par ``build_assessment`` (memes indices que ``supplyscore.core.ahp.CRITERIA``).
PAIRS: tuple[tuple[int, int], ...] = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))


def _bipolar_from_saaty(value: float) -> int:
    """Inverse exacte de ``bipolar_to_saaty`` sur les 17 points de l'echelle de Saaty."""
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
    """Declarant synthetique de palier 0 -- ancre sur ``ur_local`` (OBSERVABLE).

    Respecte le contrat fige ``respond(node_id, tour, features, rng) ->
    {"bipolar": [6 int -8..8], "scores_ui": [4 int 1..6]}`` utilise pour les
    paliers 1/2 (``--behavior``). ``features`` ne doit contenir QUE des
    grandeurs observables (jamais le stress latent -- cf. note de module).
    ``bias`` est le biais du noeud, tire UNE FOIS par chaine (perception
    personnelle stable du declarant simule).

    Les 4 poids-cibles (positifs) sont derives de l'urgence percue, puis les
    6 comparaisons bipolaires sont derivees des RATIOS de ces poids (comme
    ``RandomSupplyChainGenerator.generate_assessment``) -- garantit un
    ratio de coherence de Saaty quasi toujours < 0.10, contrairement a 6
    tirages bipolaires independants (generalement incoherents pour 4 criteres).

    Args:
        node_id: identifiant du noeud (non utilise par ce declarant, present
            pour respecter le contrat ``respond``).
        tour: numero du tour (non utilise par ce declarant).
        features: dictionnaire observable (``ur_local`` notamment).
        rng: generateur du noeud (flux OPERATEUR -- jamais le flux dynamique).
        bias: biais de perception du noeud, stable sur la chaine.

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
    """Convertit une reponse ``{"bipolar", "scores_ui"}`` en entrees de ``build_assessment``.

    Raises:
        ValueError: reponse malformee (mauvaise longueur des listes).
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
