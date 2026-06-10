"""Typologie des événements supply chain à impact calibré (phase E2, Lot 2.2).

Chaque type d'événement déclaré dans :data:`EVENT_CALIBRATION` décrit :

- ses champs de saisie (:class:`EventField`, pilotera l'UI plus tard) ;
- ses impacts sur les KPIs d'un :class:`~supplyscore.domain.models.KPIBundle`,
  calculés par :func:`compute_impacts` sous forme de :class:`KpiImpact` auditables.

Trois opérateurs de calibration sont utilisés :

- **BAYES** (:func:`bayes_update`) : révision Beta-Bernoulli de la probabilité de
  défaillance — « cet événement équivaut à observer k défaillances sur n essais » ;
- **EMA** (:func:`ema_update`) : lissage exponentiel d'une observation continue ;
- **DIRECT** : la valeur observée remplace l'ancienne (faits signés, ex. nouveau tarif).

Certains impacts en « cliquet » (max de l'ancien et du nouveau niveau) modélisent
des expositions qui ne redescendent pas spontanément (risque politique, sévérité).

Module PUR : aucune IO, aucune écriture — les impacts sont calculés et retournés,
jamais appliqués. Chaque valeur ``new`` est bornée par
:func:`supplyscore.domain.constraints.clamp_kpi_value`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from supplyscore.domain.constraints import clamp_kpi_value
from supplyscore.domain.models import KPIBundle

# --- Opérateurs de calibration ------------------------------------------------------

#: Poids du prior en pseudo-observations : ~6 mois d'observations hebdomadaires.
#: Un événement isolé déplace donc la probabilité sans l'écraser (mémoire courte
#: mais pas amnésique), et la décroissance hebdomadaire reste douce.
N0_PSEUDO_OBSERVATIONS: float = 26.0

#: Prior par défaut de ``risk.failure_probability`` quand le KPI n'est pas renseigné :
#: ordre de grandeur d'une défaillance toutes les ~50 semaines, point de départ
#: prudent et documenté pour la révision bayésienne.
DEFAULT_FAILURE_PRIOR: float = 0.02

#: Bornes de :func:`bayes_update` — jamais 0 ni 1 : une probabilité certaine
#: rendrait toute révision future impossible (verrou bayésien).
_BAYES_MIN: float = 1e-4
_BAYES_MAX: float = 0.99

#: Heures dans une semaine — normalise les durées d'arrêt en perte de
#: disponibilité hebdomadaire (168 h d'arrêt = semaine entièrement perdue).
WEEK_HOURS: float = 168.0


def bayes_update(p: float, k: float, n: float, n0: float = N0_PSEUDO_OBSERVATIONS) -> float:
    """Révision Beta-Bernoulli d'une probabilité de défaillance.

    Formule : ``(p·n0 + k) / (n0 + n)``, bornée dans [1e-4, 0.99].

    Sémantique auditable : « cet événement équivaut à observer k défaillances
    sur n essais », le prior pesant ``n0`` pseudo-observations (~6 mois
    d'observations hebdomadaires). Si ``k/n == p``, la probabilité est un point
    fixe : l'événement confirme le prior sans le déplacer.

    Args:
        p: probabilité a priori (typiquement ``risk.failure_probability``).
        k: nombre (éventuellement fractionnaire) de défaillances équivalentes.
        n: nombre d'essais équivalents.
        n0: poids du prior en pseudo-observations.

    Returns:
        La probabilité révisée, bornée dans [1e-4, 0.99].
    """
    posterior = (p * n0 + k) / (n0 + n)
    return min(max(posterior, _BAYES_MIN), _BAYES_MAX)


def ema_update(old: float | None, obs: float, lam: float) -> float:
    """Lissage exponentiel (EMA) d'une observation continue.

    Formule : ``(1−lam)·old + lam·obs`` ; si ``old`` est None, l'observation
    initialise directement la valeur. ``lam`` règle la réactivité : 0.3–0.5
    selon que le KPI doit réagir lentement ou vite aux événements.

    Args:
        old: ancienne valeur du KPI (None si jamais renseignée).
        obs: observation apportée par l'événement.
        lam: poids de l'observation, dans [0, 1].

    Returns:
        La valeur lissée.
    """
    if old is None:
        return obs
    return (1.0 - lam) * old + lam * obs


# --- Structure déclarative ----------------------------------------------------------


@dataclass(frozen=True)
class EventField:
    """Champ de saisie d'un événement (pilotera l'UI plus tard).

    Attributes:
        name: identifiant du paramètre (clé attendue dans ``params``).
        label_fr: libellé d'affichage en français.
        kind: nature du champ — ``"number"``, ``"ratio"`` ou ``"choice"``.
        minimum: borne inférieure inclusive (None = pas de borne).
        maximum: borne supérieure inclusive (None = pas de borne).
        unit: unité d'affichage (chaîne vide si sans unité).
        choices: valeurs admises pour un champ ``"choice"``.
    """

    name: str
    label_fr: str
    kind: str  # "number" | "ratio" | "choice"
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventSpec:
    """Spécification déclarative d'un type d'événement supply chain.

    Attributes:
        event_type: identifiant du type (clé de :data:`EVENT_CALIBRATION`).
        label_fr: libellé court en français.
        description_fr: description de l'événement et de sa calibration.
        fields: champs de saisie attendus.
    """

    event_type: str
    label_fr: str
    description_fr: str
    fields: tuple[EventField, ...]


@dataclass(frozen=True)
class KpiImpact:
    """Impact calibré d'un événement sur un KPI (calculé, jamais appliqué ici).

    Attributes:
        kpi_path: chemin qualifié du KPI, ex. ``"risk.failure_probability"``.
        old: ancienne valeur du KPI (None si jamais renseignée).
        new: nouvelle valeur, déjà bornée par ``clamp_kpi_value``.
        rule: description française de la règle appliquée, avec les
            paramètres effectifs — ex. ``"BAYES(p=0.02, k=1, n=1) : ..."``.
    """

    kpi_path: str
    old: float | None
    new: float
    rule: str


# --- Paramètres de gravité ----------------------------------------------------------

#: Équivalence bayésienne (k, n) d'une panne ou d'un accident selon la gravité :
#: mineure = « une demi-défaillance », majeure = une défaillance franche,
#: critique = deux défaillances sur deux essais (signal fort, prior plus dilué).
_GRAVITE_PANNE_BAYES: dict[str, tuple[float, float]] = {
    "mineure": (0.5, 1.0),
    "majeure": (1.0, 1.0),
    "critique": (2.0, 2.0),
}

#: Équivalence bayésienne (k, n) d'une alerte financière fournisseur :
#: un défaut avéré pèse trois défaillances sur trois essais.
_GRAVITE_FINANCE_BAYES: dict[str, tuple[float, float]] = {
    "surveillee": (0.5, 1.0),
    "procedure": (1.0, 1.0),
    "defaut": (3.0, 3.0),
}

#: Sévérité forfaitaire (cliquet sur ``risk.severity``) d'un accident.
_GRAVITE_ACCIDENT_SEVERITE: dict[str, float] = {"mineure": 0.4, "majeure": 0.7, "critique": 1.0}

#: Sévérité forfaitaire (cliquet sur ``risk.severity``) d'une alerte financière.
_GRAVITE_FINANCE_SEVERITE: dict[str, float] = {"surveillee": 0.3, "procedure": 0.6, "defaut": 0.9}

#: Champs numériques strictement positifs (la borne ``minimum=0`` est exclusive :
#: une durée ou une demande nulle n'est pas un événement).
_STRICTLY_POSITIVE_FIELDS: frozenset[str] = frozenset(
    {"duree_arret_h", "retard_h", "duree_prevue_h", "nouvelle_demande"}
)

# --- Champs réutilisés --------------------------------------------------------------

_FIELD_DUREE_ARRET = EventField(
    name="duree_arret_h",
    label_fr="Durée d'arrêt",
    kind="number",
    minimum=0.0,
    unit="h",
)
_FIELD_GRAVITE_PANNE = EventField(
    name="gravite",
    label_fr="Gravité",
    kind="choice",
    choices=("mineure", "majeure", "critique"),
)


#: Typologie calibrée des 14 types d'événements supply chain.
EVENT_CALIBRATION: dict[str, EventSpec] = {
    "panne_machine": EventSpec(
        event_type="panne_machine",
        label_fr="Panne machine",
        description_fr=(
            "Arrêt non planifié d'un équipement : révision bayésienne de la probabilité "
            "de défaillance selon la gravité, lissage du temps de récupération et de la "
            "disponibilité hebdomadaire."
        ),
        fields=(_FIELD_DUREE_ARRET, _FIELD_GRAVITE_PANNE),
    ),
    "retard_fournisseur": EventSpec(
        event_type="retard_fournisseur",
        label_fr="Retard fournisseur",
        description_fr=(
            "Livraison en retard : le lead time et sa dispersion sont lissés vers les "
            "valeurs observées."
        ),
        fields=(
            EventField(
                name="retard_h", label_fr="Retard constaté", kind="number", minimum=0.0, unit="h"
            ),
        ),
    ),
    "greve": EventSpec(
        event_type="greve",
        label_fr="Grève",
        description_fr=(
            "Mouvement social : la disponibilité est réduite au prorata de l'effectif et "
            "de la durée, la sévérité monte en cliquet au niveau de la part en grève."
        ),
        fields=(
            EventField(
                name="duree_prevue_h",
                label_fr="Durée prévue",
                kind="number",
                minimum=0.0,
                unit="h",
            ),
            EventField(
                name="part_effectif",
                label_fr="Part de l'effectif en grève",
                kind="ratio",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
    ),
    "hausse_tarif": EventSpec(
        event_type="hausse_tarif",
        label_fr="Hausse de tarif",
        description_fr=(
            "Variation tarifaire signée (fait signé, mise à jour directe du multiplicateur) ; "
            "la volatilité des coûts est lissée vers l'amplitude observée."
        ),
        fields=(
            EventField(
                name="pct",
                label_fr="Variation du tarif",
                kind="number",
                minimum=-100.0,
                maximum=500.0,
                unit="%",
            ),
        ),
    ),
    "rupture_matiere": EventSpec(
        event_type="rupture_matiere",
        label_fr="Rupture de matière",
        description_fr=(
            "Pénurie d'approvisionnement : le débit chute au prorata de la criticité, la "
            "probabilité de défaillance est révisée (k = criticité) et la sévérité monte "
            "en cliquet."
        ),
        fields=(
            EventField(
                name="duree_prevue_h",
                label_fr="Durée prévue",
                kind="number",
                minimum=0.0,
                unit="h",
            ),
            EventField(
                name="criticite",
                label_fr="Criticité de la matière",
                kind="ratio",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
    ),
    "accident": EventSpec(
        event_type="accident",
        label_fr="Accident",
        description_fr=(
            "Accident industriel : révision bayésienne selon la gravité, lissage réactif "
            "du temps de récupération (λ=0.5) et sévérité forfaitaire en cliquet."
        ),
        fields=(_FIELD_DUREE_ARRET, _FIELD_GRAVITE_PANNE),
    ),
    "non_conformite_qualite": EventSpec(
        event_type="non_conformite_qualite",
        label_fr="Non-conformité qualité",
        description_fr=(
            "Taux de rebut observé : la qualité OEE est lissée vers 1 − taux de rebut."
        ),
        fields=(
            EventField(
                name="taux_rebut_obs",
                label_fr="Taux de rebut observé",
                kind="ratio",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
    ),
    "perturbation_transport": EventSpec(
        event_type="perturbation_transport",
        label_fr="Perturbation transport",
        description_fr=(
            "Aléa logistique : le lead time est lissé vers la valeur retardée et le "
            "surcoût s'ajoute directement au coût opérationnel (fait signé)."
        ),
        fields=(
            EventField(
                name="retard_h", label_fr="Retard constaté", kind="number", minimum=0.0, unit="h"
            ),
            EventField(name="surcout", label_fr="Surcoût", kind="number", minimum=0.0, unit="€"),
        ),
    ),
    "instabilite_politique": EventSpec(
        event_type="instabilite_politique",
        label_fr="Instabilité politique",
        description_fr=(
            "Dégradation géopolitique : le risque politique monte en cliquet au niveau "
            "observé (il ne redescend pas spontanément)."
        ),
        fields=(
            EventField(
                name="niveau",
                label_fr="Niveau d'instabilité",
                kind="ratio",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
    ),
    "cyber_incident": EventSpec(
        event_type="cyber_incident",
        label_fr="Cyber-incident",
        description_fr=(
            "Attaque ou panne SI : une défaillance franche est observée (BAYES k=1, n=1) "
            "et la disponibilité hebdomadaire est lissée selon la durée d'arrêt."
        ),
        fields=(_FIELD_DUREE_ARRET,),
    ),
    "hausse_energie": EventSpec(
        event_type="hausse_energie",
        label_fr="Hausse du coût de l'énergie",
        description_fr=(
            "Variation signée du coût de l'énergie : le coût opérationnel est mis à jour "
            "directement (fait signé) et la volatilité des coûts est lissée."
        ),
        fields=(
            EventField(
                name="pct",
                label_fr="Variation du coût de l'énergie",
                kind="number",
                minimum=-100.0,
                maximum=500.0,
                unit="%",
            ),
        ),
    ),
    "alerte_financiere_fournisseur": EventSpec(
        event_type="alerte_financiere_fournisseur",
        label_fr="Alerte financière fournisseur",
        description_fr=(
            "Signal de santé financière : révision bayésienne graduée (surveillée, "
            "procédure, défaut) et sévérité forfaitaire en cliquet."
        ),
        fields=(
            EventField(
                name="gravite",
                label_fr="Gravité de l'alerte",
                kind="choice",
                choices=("surveillee", "procedure", "defaut"),
            ),
        ),
    ),
    "perte_capacite": EventSpec(
        event_type="perte_capacite",
        label_fr="Perte de capacité",
        description_fr=(
            "Capacité de stockage perdue : le volume maximal est réduit directement (fait "
            "signé) et l'exposition environnementale monte en cliquet."
        ),
        fields=(
            EventField(
                name="pct_volume_perdu",
                label_fr="Part du volume perdu",
                kind="ratio",
                minimum=0.0,
                maximum=1.0,
            ),
        ),
    ),
    "pic_demande": EventSpec(
        event_type="pic_demande",
        label_fr="Pic de demande",
        description_fr=(
            "Nouvelle demande constatée : remplacement direct de la demande réseau (fait signé)."
        ),
        fields=(
            EventField(
                name="nouvelle_demande",
                label_fr="Nouvelle demande",
                kind="number",
                minimum=0.0,
                unit="unité/temps",
            ),
        ),
    ),
}


# --- Aides internes -----------------------------------------------------------------

#: Paramètres validés : nombres convertis en float, choix en str.
_Params = dict[str, float | str]


def _kpi_value(kpis: KPIBundle, kpi_path: str) -> float | None:
    """Lit la valeur d'un KPI par son chemin qualifié ``bloc.champ``."""
    block_name, _, field_name = kpi_path.partition(".")
    return cast(float | None, getattr(getattr(kpis, block_name), field_name))


def _impact(kpi_path: str, old: float | None, new: float, rule: str) -> KpiImpact:
    """Construit un :class:`KpiImpact` en bornant ``new`` via ``clamp_kpi_value``."""
    return KpiImpact(kpi_path=kpi_path, old=old, new=clamp_kpi_value(kpi_path, new), rule=rule)


def _num(params: _Params, name: str) -> float:
    """Paramètre numérique déjà validé."""
    return cast(float, params[name])


def _choice(params: _Params, name: str) -> str:
    """Paramètre de choix déjà validé."""
    return cast(str, params[name])


def _bayes_impact(kpis: KPIBundle, k: float, n: float, contexte: str) -> KpiImpact:
    """Impact bayésien sur ``risk.failure_probability``.

    Si le KPI est None, le prior par défaut :data:`DEFAULT_FAILURE_PRIOR` (0.02)
    sert de point de départ — documenté dans la règle.
    """
    old = _kpi_value(kpis, "risk.failure_probability")
    prior = DEFAULT_FAILURE_PRIOR if old is None else old
    suffix = " — prior par défaut 0.02 (KPI non renseigné)" if old is None else ""
    rule = f"BAYES(p={prior:g}, k={k:g}, n={n:g}) : {contexte}{suffix}"
    return _impact("risk.failure_probability", old, bayes_update(prior, k, n), rule)


def _ema_impact(kpis: KPIBundle, kpi_path: str, obs: float, lam: float, contexte: str) -> KpiImpact:
    """Impact EMA sur un KPI (initialisation à l'observation si le KPI est None)."""
    old = _kpi_value(kpis, kpi_path)
    suffix = " — initialisation (ancienne valeur absente)" if old is None else ""
    rule = f"EMA(obs={obs:g}, λ={lam:g}) : {contexte}{suffix}"
    return _impact(kpi_path, old, ema_update(old, obs, lam), rule)


def _ratchet_impact(kpis: KPIBundle, kpi_path: str, niveau: float, contexte: str) -> KpiImpact:
    """Impact en cliquet : ``max(ancien ou 0, niveau)`` — ne redescend jamais."""
    old = _kpi_value(kpis, kpi_path)
    new = max(old if old is not None else 0.0, niveau)
    rule = f"CLIQUET : max(ancien ou 0, {niveau:g}) — {contexte}"
    return _impact(kpi_path, old, new, rule)


# --- Calibrations par type d'événement ----------------------------------------------


def _panne_machine(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Panne machine : BAYES gradué, EMA récupération (λ=0.4), EMA disponibilité (λ=0.3)."""
    duree = _num(params, "duree_arret_h")
    gravite = _choice(params, "gravite")
    k, n = _GRAVITE_PANNE_BAYES[gravite]
    obs_avail = max(0.0, 1.0 - duree / WEEK_HOURS)
    return [
        _bayes_impact(kpis, k, n, f"panne machine {gravite}"),
        _ema_impact(kpis, "risk.recovery_time_h", duree, 0.4, "temps de récupération observé"),
        _ema_impact(
            kpis,
            "oee.availability",
            obs_avail,
            0.3,
            f"disponibilité hebdomadaire après {duree:g} h d'arrêt",
        ),
    ]


def _retard_fournisseur(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Retard fournisseur : EMA du lead time décalé (λ=0.4) et de sa dispersion (λ=0.3)."""
    retard = _num(params, "retard_h")
    old_lead = _kpi_value(kpis, "time.lead_time_h")
    obs_lead = retard if old_lead is None else old_lead + retard
    return [
        _ema_impact(kpis, "time.lead_time_h", obs_lead, 0.4, f"lead time décalé de {retard:g} h"),
        _ema_impact(kpis, "time.lead_time_std_h", retard, 0.3, "dispersion du lead time"),
    ]


def _greve(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Grève : disponibilité réduite au prorata (ignorée si None), sévérité en cliquet."""
    duree = _num(params, "duree_prevue_h")
    part = _num(params, "part_effectif")
    impacts: list[KpiImpact] = []
    old_avail = _kpi_value(kpis, "oee.availability")
    if old_avail is not None:
        new = old_avail * (1.0 - part * min(duree / WEEK_HOURS, 1.0))
        rule = f"DIRECT : disponibilité × (1 − {part:g} × min({duree:g}/168, 1))"
        impacts.append(_impact("oee.availability", old_avail, new, rule))
    impacts.append(_ratchet_impact(kpis, "risk.severity", part, "part de l'effectif en grève"))
    return impacts


def _hausse_tarif(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Hausse de tarif : multiplicateur mis à jour directement, volatilité lissée."""
    pct = _num(params, "pct")
    old_tariff = _kpi_value(kpis, "cost.tariff")
    base = 1.0 if old_tariff is None else old_tariff
    suffix = " — base neutre 1 (KPI non renseigné)" if old_tariff is None else ""
    rule = f"DIRECT : tarif × (1 + {pct:g}/100){suffix}"
    return [
        _impact("cost.tariff", old_tariff, base * (1.0 + pct / 100.0), rule),
        _ema_impact(
            kpis,
            "risk.cost_volatility",
            min(abs(pct) / 100.0, 1.0),
            0.3,
            "volatilité tarifaire observée",
        ),
    ]


def _rupture_matiere(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Rupture matière : débit réduit (ignoré si None), BAYES(k=criticité), cliquet sévérité."""
    criticite = _num(params, "criticite")
    impacts: list[KpiImpact] = []
    old_flow = _kpi_value(kpis, "inventory.flow_rate")
    if old_flow is not None:
        rule = f"DIRECT : débit × (1 − {criticite:g})"
        impacts.append(_impact("inventory.flow_rate", old_flow, old_flow * (1.0 - criticite), rule))
    impacts.append(_bayes_impact(kpis, criticite, 1.0, "rupture matière pondérée par la criticité"))
    impacts.append(_ratchet_impact(kpis, "risk.severity", criticite, "criticité de la rupture"))
    return impacts


def _accident(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Accident : BAYES gradué, EMA récupération réactive (λ=0.5), sévérité forfaitaire."""
    duree = _num(params, "duree_arret_h")
    gravite = _choice(params, "gravite")
    k, n = _GRAVITE_PANNE_BAYES[gravite]
    severite = _GRAVITE_ACCIDENT_SEVERITE[gravite]
    return [
        _bayes_impact(kpis, k, n, f"accident {gravite}"),
        _ema_impact(kpis, "risk.recovery_time_h", duree, 0.5, "temps de récupération observé"),
        _ratchet_impact(
            kpis, "risk.severity", severite, f"sévérité forfaitaire accident {gravite}"
        ),
    ]


def _non_conformite_qualite(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Non-conformité qualité : EMA de la qualité OEE vers 1 − taux de rebut (λ=0.4)."""
    taux = _num(params, "taux_rebut_obs")
    return [
        _ema_impact(
            kpis,
            "oee.quality",
            1.0 - taux,
            0.4,
            f"qualité observée (1 − taux de rebut {taux:g})",
        )
    ]


def _perturbation_transport(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Perturbation transport : EMA du lead time décalé, surcoût ajouté directement."""
    retard = _num(params, "retard_h")
    surcout = _num(params, "surcout")
    old_lead = _kpi_value(kpis, "time.lead_time_h")
    obs_lead = retard if old_lead is None else old_lead + retard
    old_cost = _kpi_value(kpis, "cost.op_cost")
    base_cost = 0.0 if old_cost is None else old_cost
    suffix = " — base 0 (KPI non renseigné)" if old_cost is None else ""
    rule_cost = f"DIRECT : coût opérationnel + {surcout:g}{suffix}"
    return [
        _ema_impact(kpis, "time.lead_time_h", obs_lead, 0.4, f"lead time décalé de {retard:g} h"),
        _impact("cost.op_cost", old_cost, base_cost + surcout, rule_cost),
    ]


def _instabilite_politique(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Instabilité politique : cliquet sur le risque politique."""
    niveau = _num(params, "niveau")
    return [
        _ratchet_impact(
            kpis, "risk.political_risk", niveau, "niveau d'instabilité politique observé"
        )
    ]


def _cyber_incident(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Cyber-incident : défaillance franche (BAYES k=1, n=1), EMA disponibilité (λ=0.3)."""
    duree = _num(params, "duree_arret_h")
    obs_avail = max(0.0, 1.0 - duree / WEEK_HOURS)
    return [
        _bayes_impact(kpis, 1.0, 1.0, "cyber-incident"),
        _ema_impact(
            kpis,
            "oee.availability",
            obs_avail,
            0.3,
            f"disponibilité hebdomadaire après {duree:g} h d'arrêt",
        ),
    ]


def _hausse_energie(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Hausse énergie : coût opérationnel mis à jour (ignoré si None), volatilité lissée."""
    pct = _num(params, "pct")
    impacts: list[KpiImpact] = []
    old_cost = _kpi_value(kpis, "cost.op_cost")
    if old_cost is not None:
        rule = f"DIRECT : coût opérationnel × (1 + {pct:g}/100)"
        impacts.append(_impact("cost.op_cost", old_cost, old_cost * (1.0 + pct / 100.0), rule))
    impacts.append(
        _ema_impact(
            kpis,
            "risk.cost_volatility",
            min(abs(pct) / 100.0, 1.0),
            0.3,
            "volatilité énergétique observée",
        )
    )
    return impacts


def _alerte_financiere_fournisseur(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Alerte financière : BAYES gradué (jusqu'à k=3, n=3) et sévérité forfaitaire."""
    gravite = _choice(params, "gravite")
    k, n = _GRAVITE_FINANCE_BAYES[gravite]
    severite = _GRAVITE_FINANCE_SEVERITE[gravite]
    return [
        _bayes_impact(kpis, k, n, f"alerte financière fournisseur ({gravite})"),
        _ratchet_impact(kpis, "risk.severity", severite, f"sévérité forfaitaire alerte {gravite}"),
    ]


def _perte_capacite(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Perte de capacité : volume max réduit (ignoré si None), exposition en cliquet."""
    pct = _num(params, "pct_volume_perdu")
    impacts: list[KpiImpact] = []
    old_volume = _kpi_value(kpis, "inventory.max_volume_m3")
    if old_volume is not None:
        rule = f"DIRECT : volume max × (1 − {pct:g})"
        impacts.append(
            _impact("inventory.max_volume_m3", old_volume, old_volume * (1.0 - pct), rule)
        )
    impacts.append(_ratchet_impact(kpis, "risk.env_exposure", pct, "part de capacité perdue"))
    return impacts


def _pic_demande(params: _Params, kpis: KPIBundle) -> list[KpiImpact]:
    """Pic de demande : remplacement direct de la demande réseau (fait signé)."""
    demande = _num(params, "nouvelle_demande")
    old = _kpi_value(kpis, "network.demand")
    rule = f"DIRECT : demande remplacée par {demande:g} (fait signé)"
    return [_impact("network.demand", old, demande, rule)]


#: Table de dispatch type d'événement -> fonction de calibration.
_HANDLERS: dict[str, Callable[[_Params, KPIBundle], list[KpiImpact]]] = {
    "panne_machine": _panne_machine,
    "retard_fournisseur": _retard_fournisseur,
    "greve": _greve,
    "hausse_tarif": _hausse_tarif,
    "rupture_matiere": _rupture_matiere,
    "accident": _accident,
    "non_conformite_qualite": _non_conformite_qualite,
    "perturbation_transport": _perturbation_transport,
    "instabilite_politique": _instabilite_politique,
    "cyber_incident": _cyber_incident,
    "hausse_energie": _hausse_energie,
    "alerte_financiere_fournisseur": _alerte_financiere_fournisseur,
    "perte_capacite": _perte_capacite,
    "pic_demande": _pic_demande,
}


def _validate_params(spec: EventSpec, params: Mapping[str, object]) -> _Params:
    """Valide les paramètres d'un événement contre sa spécification.

    Raises:
        ValueError: paramètre inconnu, manquant, non numérique, non fini,
            hors bornes ou choix non admis.
    """
    known = {field.name for field in spec.fields}
    unknown = set(params) - known
    if unknown:
        raise ValueError(
            f"{spec.event_type} : paramètre(s) inconnu(s) {sorted(unknown)} "
            f"— attendus {sorted(known)}"
        )
    validated: _Params = {}
    for field in spec.fields:
        if field.name not in params:
            raise ValueError(f"{spec.event_type} : paramètre manquant « {field.name} »")
        raw = params[field.name]
        if field.kind == "choice":
            if not isinstance(raw, str) or raw not in field.choices:
                raise ValueError(
                    f"{spec.event_type} : « {field.name} » doit être parmi "
                    f"{field.choices}, reçu {raw!r}"
                )
            validated[field.name] = raw
            continue
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ValueError(
                f"{spec.event_type} : « {field.name} » doit être numérique, reçu {raw!r}"
            )
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError(f"{spec.event_type} : « {field.name} » non fini ({raw!r})")
        if field.minimum is not None and value < field.minimum:
            raise ValueError(
                f"{spec.event_type} : « {field.name} » = {value} < minimum {field.minimum}"
            )
        if field.maximum is not None and value > field.maximum:
            raise ValueError(
                f"{spec.event_type} : « {field.name} » = {value} > maximum {field.maximum}"
            )
        if field.name in _STRICTLY_POSITIVE_FIELDS and value <= 0.0:
            raise ValueError(
                f"{spec.event_type} : « {field.name} » doit être strictement positif (reçu {value})"
            )
        validated[field.name] = value
    return validated


# --- API publique -------------------------------------------------------------------


def compute_impacts(
    event_type: str, params: Mapping[str, object], kpis: KPIBundle
) -> list[KpiImpact]:
    """Calcule les impacts calibrés d'un événement sur un bundle de KPIs.

    Fonction PURE : le bundle n'est jamais modifié, les impacts sont seulement
    calculés et retournés. Chaque valeur ``new`` est bornée par
    :func:`supplyscore.domain.constraints.clamp_kpi_value`. Les impacts dont le
    KPI source est None et marqués « ignorer » dans la calibration ne
    produisent pas de :class:`KpiImpact`.

    Args:
        event_type: clé de :data:`EVENT_CALIBRATION`.
        params: paramètres saisis, conformes aux ``fields`` de l'EventSpec.
        kpis: bundle de KPIs courant (lecture seule).

    Returns:
        La liste des impacts calibrés.

    Raises:
        ValueError: type d'événement inconnu, ou paramètre invalide/hors bornes.
    """
    spec = EVENT_CALIBRATION.get(event_type)
    if spec is None:
        raise ValueError(
            f"Type d'événement inconnu : {event_type!r} — types admis : {sorted(EVENT_CALIBRATION)}"
        )
    validated = _validate_params(spec, params)
    return _HANDLERS[event_type](validated, kpis)


def weekly_decay(kpis: KPIBundle) -> list[KpiImpact]:
    """Décroissance hebdomadaire : « semaine sans incident ».

    La probabilité de défaillance est révisée par ``bayes_update(p, k=0, n=1)`` :
    une semaine écoulée sans défaillance est une observation favorable qui érode
    doucement le risque (jamais sous la borne 1e-4).

    Args:
        kpis: bundle de KPIs courant (lecture seule).

    Returns:
        Un impact sur ``risk.failure_probability``, ou ``[]`` si le KPI est None.
    """
    p = _kpi_value(kpis, "risk.failure_probability")
    if p is None:
        return []
    rule = f"BAYES(p={p:g}, k=0, n=1) : semaine sans incident — décroissance hebdomadaire"
    return [_impact("risk.failure_probability", p, bayes_update(p, 0.0, 1.0), rule)]
