"""Urgence réelle Ur — agrégation de blocs KPI en une urgence locale ∈ [0, 1].

Chaque bloc (temps, capacité, performance, risque, coût, CO2) produit une
urgence partielle dans [0, 1] ou None si les KPIs nécessaires manquent.
L'agrégation est un OU probabiliste pondéré : un seul bloc critique suffit
à rendre le nœud urgent, les blocs manquants sont simplement ignorés.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from supplyscore.core.status_rules import effective_ur_local
from supplyscore.domain.milestones import Milestone, next_active_milestone, theoretical_progress
from supplyscore.domain.models import KPIBundle, TaskStatus

#: Noms des blocs d'urgence, dans l'ordre d'agrégation.
BLOCKS: tuple[str, ...] = ("time", "cap", "perf", "risk", "cost", "co2")

_EPS: float = 1e-9


def _clip01(x: float) -> float:
    """Borne une valeur sur [0, 1]."""
    return min(max(x, 0.0), 1.0)


def _normal_sf(x: float, mu: float, sigma: float) -> float:
    """Fonction de survie P(X > x) d'une loi Normale(mu, sigma), via erf.

    Args:
        x: seuil.
        mu: moyenne.
        sigma: écart-type strictement positif.

    Returns:
        P(X > x) dans [0, 1].
    """
    z = (x - mu) / (sigma * math.sqrt(2.0))
    return 0.5 * (1.0 - math.erf(z))


def ur_singularity(
    t: float,
    tc: float,
    K: float = 1.0,  # noqa: N803  # convention math : K = gain de divergence
    eps_min: float = 1e-9,
) -> float:
    """Urgence temporelle à singularité finie (Sornette & Johansen).

    L'urgence diverge de façon hyperbolique à l'approche de l'échéance tc,
    écrasée par tanh pour rester dans [0, 1] avant tc. Après tc la tâche est
    en retard : l'urgence dépasse 1 et croît linéairement.

    - t <= tc : tanh(K / max(tc − t, eps_min)) ;
    - t >  tc : 1 + K·(t − tc).

    Args:
        t: date courante (heures).
        tc: date critique (singularité).
        K: gain de la divergence, > 0.
        eps_min: garde-fou numérique près de la singularité, > 0.

    Returns:
        Urgence >= 0, dans [0, 1] avant tc, > 1 après tc.

    Raises:
        ValueError: si K <= 0 ou eps_min <= 0.
    """
    if K <= 0:
        raise ValueError(f"K doit être > 0, reçu {K}")
    if eps_min <= 0:
        raise ValueError(f"eps_min doit être > 0, reçu {eps_min}")
    if t <= tc:
        return math.tanh(K / max(tc - t, eps_min))
    return 1.0 + K * (t - tc)


def ud_hyperbolic(t: float, tc: float, k: float = 0.05) -> float:
    """Urgence perçue simulée — actualisation hyperbolique (Mazur).

    Ud(t) = 1 / (1 + k·max(tc − t, 0)) : l'humain sous-pondère les échéances
    lointaines puis « se réveille » hyperboliquement près de tc. Sert au
    générateur de données simulées.

    Args:
        t: date courante (heures).
        tc: date critique.
        k: taux d'actualisation hyperbolique, >= 0.

    Returns:
        Urgence perçue dans [0, 1].

    Raises:
        ValueError: si k < 0.
    """
    if k < 0:
        raise ValueError(f"k doit être >= 0, reçu {k}")
    return _clip01(1.0 / (1.0 + k * max(tc - t, 0.0)))


def filtered_error(ud: float, ur_t: float, eps_tol: float = 0.0) -> float:
    """Erreur Ud − Ur filtrée par une zone morte de tolérance.

    e = sign(Ud − Ur) · max(|Ud − Ur| − eps_tol, 0) : les écarts plus petits
    que eps_tol sont considérés comme du bruit et ramenés à 0.

    Args:
        ud: urgence déclarée.
        ur_t: urgence réelle à la date t.
        eps_tol: demi-largeur de la zone morte, >= 0.

    Returns:
        Erreur signée filtrée.

    Raises:
        ValueError: si eps_tol < 0.
    """
    if eps_tol < 0:
        raise ValueError(f"eps_tol doit être >= 0, reçu {eps_tol}")
    diff = ud - ur_t
    magnitude = max(abs(diff) - eps_tol, 0.0)
    if magnitude == 0.0:
        return 0.0
    return math.copysign(magnitude, diff)


@dataclass
class UrModel:
    """Modèle d'urgence réelle locale d'un nœud à partir de ses KPIs.

    Chaque méthode ``u_*`` renvoie une urgence partielle dans [0, 1] ou None
    si les KPIs nécessaires manquent. :meth:`ur_local` agrège les blocs
    disponibles par OU probabiliste pondéré.

    Attributes:
        alpha_cap: poids (volume, poids, flux) du bloc capacité.
        beta_cost: poids (surcoût op, tarif, stockage) du bloc coût.
        t_ref_h: horizon de référence (heures) pour la normalisation du risque.
        c_ref: coût de stockage de référence pour la normalisation du coût.
        kappa_retard: gain κ_retard >= 0 de la pénalité de retard
            d'avancement (u_time v2, jalon en retard sur son planning).
        kappa_avance: gain κ_avance >= 0 du bonus d'avance (u_time v2,
            jalon en avance sur son planning).
        omega: poids d'agrégation ω_m >= 0 par bloc (défaut : tous 1.0).
        eps: garde-fou numérique des divisions.
    """

    alpha_cap: tuple[float, float, float] = (0.4, 0.3, 0.3)
    beta_cost: tuple[float, float, float] = (0.5, 0.3, 0.2)
    t_ref_h: float = 24.0
    c_ref: float = 1000.0
    kappa_retard: float = 0.5
    kappa_avance: float = 0.2
    omega: dict[str, float] = field(default_factory=lambda: {name: 1.0 for name in BLOCKS})
    eps: float = _EPS

    def __post_init__(self) -> None:
        """Valide les poids d'agrégation et les gains de modulation planning.

        Raises:
            ValueError: si un poids ω_m est négatif, si un bloc est inconnu
                ou si κ_retard / κ_avance est négatif.
        """
        for name, w in self.omega.items():
            if name not in BLOCKS:
                raise ValueError(f"Bloc inconnu dans omega : {name!r}")
            if w < 0:
                raise ValueError(f"Poids omega[{name!r}] négatif : {w}")
        if self.kappa_retard < 0:
            raise ValueError(f"kappa_retard doit être >= 0, reçu {self.kappa_retard}")
        if self.kappa_avance < 0:
            raise ValueError(f"kappa_avance doit être >= 0, reçu {self.kappa_avance}")

    # --- Blocs d'urgence ------------------------------------------------------

    def _p_late(self, slack_h: float, lead_time_h: float, lead_time_std_h: float | None) -> float:
        """Probabilité de retard P(L > slack) pour L ~ Normale(μ, σ).

        σ = ``lead_time_std_h`` si fourni, sinon 0.25·μ par défaut ;
        σ <= 0 dégénère en lead time déterministe (retard certain ou
        impossible selon la marge restante).

        Args:
            slack_h: marge restante avant l'échéance (heures).
            lead_time_h: lead time moyen μ (heures).
            lead_time_std_h: écart-type σ du lead time (heures), ou None.

        Returns:
            P(L > slack) dans [0, 1].
        """
        mu = lead_time_h
        if lead_time_std_h is None:
            # σ par défaut RELATIF (0.25·μ) : on travaille sur l'échelle
            # normalisée slack/μ — mathématiquement identique à N(μ, 0.25·μ),
            # mais sans le sous-passement dénormalisé de 0.25·μ vers 0.0 qui
            # rendait p_late non monotone en μ (contre-exemple Hypothesis :
            # μ = 5e-324 sautait à 1.0 alors que μ = 1.0 donnait Φ(4) < 1).
            if mu <= 0.0:
                # Lead time nul : retard certain ssi l'échéance est déjà passée.
                return 1.0 if mu > slack_h else 0.0
            return _clip01(_normal_sf(slack_h / mu, 1.0, 0.25))
        std = lead_time_std_h
        if std <= 0:
            # Lead time déterministe : retard certain ou impossible.
            return 1.0 if mu > slack_h else 0.0
        return _clip01(_normal_sf(slack_h, mu, std))

    def u_time(
        self,
        t: float,
        kpis: KPIBundle,
        milestones: list[Milestone] | None = None,
        t0_ts: float = 0.0,
    ) -> float | None:
        """Urgence temporelle : P(retard), modulée par l'avancement jalon (v2).

        **v1 (sans jalon actif)** — si ``milestones`` est None, vide ou sans
        jalon ACTIVE, comportement inchangé : u = P(L > d − t) avec
        d = ``deadline_h`` des KPIs et L ~ Normale(lead_time_h,
        lead_time_std_h), l'écart-type valant 0.25·lead_time par défaut ;
        1.0 si t a dépassé la deadline ; None si ``deadline_h`` ou
        ``lead_time_h`` manquent.

        **v2 (jalon actif)** — soit M* = :func:`next_active_milestone`,
        d* = (M*.deadline_ts − t0_ts)/3600 et s* = (M*.start_ts − t0_ts)/3600
        (heures depuis t0 projet) :

        - si t > d* : u_time = 1.0 (retard avéré) ;
        - sinon :
            - u_base = P(L > d* − t), même loi normale qu'en v1 ;
            - p_th = clip01((t − s*) / (d* − s*)), avancement théorique
              (1.0 si d* <= s*) ;
            - r = p_th − M*.progress ∈ [−1, 1], retard d'avancement ;
            - u_time = clip01(u_base + κ_retard·max(r, 0) − κ_avance·max(−r, 0)).

        La forme ADDITIVE est volontaire : la contribution κ_retard·max(r, 0)
        reste isolable du socle probabiliste u_base pour l'explicabilité.

        Choix documenté : si ``lead_time_h`` est None alors qu'un jalon est
        actif, u_base = 0.0 (et non None) — le jalon fournit l'échéance et
        l'avancement, la modulation planning s'applique donc quand même.

        Args:
            t: date courante (heures depuis t0 projet).
            kpis: bundle KPI du nœud (bloc ``time``).
            milestones: jalons du nœud ; None ou sans jalon ACTIVE → v1.
            t0_ts: origine du référentiel projet (epoch s), pour convertir
                les timestamps des jalons en heures.

        Returns:
            Urgence temporelle dans [0, 1] ; None uniquement en v1 quand
            ``deadline_h`` ou ``lead_time_h`` manquent.
        """
        tk = kpis.time
        m_star = next_active_milestone(milestones) if milestones else None
        if m_star is None:
            # v1 : échéance portée par les KPIs.
            if tk.deadline_h is None or tk.lead_time_h is None:
                return None
            if t > tk.deadline_h:
                return 1.0
            return self._p_late(tk.deadline_h - t, tk.lead_time_h, tk.lead_time_std_h)
        # v2 : échéance portée par le prochain jalon actif M*.
        d_star = (m_star.deadline_ts - t0_ts) / 3600.0
        if t > d_star:
            return 1.0
        if tk.lead_time_h is None:
            u_base = 0.0  # Pas de lead time : socle nul, modulation planning seule.
        else:
            u_base = self._p_late(d_star - t, tk.lead_time_h, tk.lead_time_std_h)
        p_th = theoretical_progress(m_star, t0_ts + t * 3600.0)
        r = p_th - m_star.progress
        return _clip01(u_base + self.kappa_retard * max(r, 0.0) - self.kappa_avance * max(-r, 0.0))

    def u_cap(self, kpis: KPIBundle) -> float | None:
        """Urgence capacitaire : saturation volume/poids et déficit de flux.

        u = clip(α1·(1 − vol_restant/vol_max) + α2·(1 − poids_restant/poids_max)
        + α3·[(demande − flux)/(demande + ε)]+, 0, 1), les α étant renormalisés
        sur les termes effectivement calculables.

        Args:
            kpis: bundle KPI du nœud (blocs ``inventory`` et ``network``).

        Returns:
            Urgence dans [0, 1], ou None si aucun terme n'est calculable.
        """
        inv = kpis.inventory
        net = kpis.network
        terms: list[float] = []
        weights: list[float] = []

        rv = inv.remaining_volume_m3
        if rv is not None and inv.max_volume_m3 and inv.max_volume_m3 > 0:
            terms.append(1.0 - rv / inv.max_volume_m3)
            weights.append(self.alpha_cap[0])

        rw = inv.remaining_weight_kg
        if rw is not None and inv.max_weight_kg and inv.max_weight_kg > 0:
            terms.append(1.0 - rw / inv.max_weight_kg)
            weights.append(self.alpha_cap[1])

        if net.demand is not None and inv.flow_rate is not None:
            deficit = (net.demand - inv.flow_rate) / (net.demand + self.eps)
            terms.append(max(deficit, 0.0))
            weights.append(self.alpha_cap[2])

        if not terms:
            return None
        total_w = sum(weights)
        if total_w <= 0:
            return None
        return _clip01(sum(w * u for w, u in zip(weights, terms, strict=True)) / total_w)

    def u_perf(self, kpis: KPIBundle) -> float | None:
        """Urgence de performance : 1 − OEE (taux de rendement synthétique).

        Args:
            kpis: bundle KPI du nœud (bloc ``oee``).

        Returns:
            1 − OEE dans [0, 1], ou None si l'OEE n'est pas calculable.
        """
        oee = kpis.oee.oee
        if oee is None:
            return None
        return _clip01(1.0 - oee)

    def u_risk(self, kpis: KPIBundle) -> float | None:
        """Urgence de risque : exposition à la défaillance, enrichie.

        base = 1 − exp(−p_défaillance · t_récup · sévérité / T_ref), puis
        composition OU probabiliste avec les expositions environnementale et
        politique : u = 1 − (1 − base)(1 − env)(1 − pol). Les expositions
        manquantes comptent pour 0. Les composantes du noyau manquantes
        prennent des valeurs neutres (p → 0, t_récup → T_ref, sévérité → 1).

        Args:
            kpis: bundle KPI du nœud (bloc ``risk``).

        Returns:
            Urgence dans [0, 1], ou None si p_défaillance, t_récup et
            sévérité manquent tous les trois.
        """
        rk = kpis.risk
        core = (rk.failure_probability, rk.recovery_time_h, rk.severity)
        if all(v is None for v in core):
            return None
        fp = rk.failure_probability if rk.failure_probability is not None else 0.0
        rt = rk.recovery_time_h if rk.recovery_time_h is not None else self.t_ref_h
        sev = rk.severity if rk.severity is not None else 1.0
        base = 1.0 - math.exp(-fp * rt * sev / self.t_ref_h)
        env = rk.env_exposure if rk.env_exposure is not None else 0.0
        pol = rk.political_risk if rk.political_risk is not None else 0.0
        u = 1.0 - (1.0 - base) * (1.0 - env) * (1.0 - pol)
        return _clip01(u)

    def u_cost(self, kpis: KPIBundle) -> float | None:
        """Urgence de coût : dérive opérationnelle, tarifs et stockage.

        u = clip(β1·(coût_op − coût_nominal)/(coût_nominal + ε)
        + β2·max(tarif − 1, 0) + β3·coût_stockage/C_ref, 0, 1), le tarif
        étant un multiplicateur (1 = neutre). Les β sont renormalisés sur
        les termes disponibles.

        Args:
            kpis: bundle KPI du nœud (bloc ``cost``).

        Returns:
            Urgence dans [0, 1], ou None si aucun terme n'est calculable.
        """
        ck = kpis.cost
        terms: list[float] = []
        weights: list[float] = []

        if ck.op_cost is not None and ck.nominal_op_cost is not None:
            drift = (ck.op_cost - ck.nominal_op_cost) / (ck.nominal_op_cost + self.eps)
            terms.append(drift)
            weights.append(self.beta_cost[0])

        if ck.tariff is not None:
            terms.append(max(ck.tariff - 1.0, 0.0))
            weights.append(self.beta_cost[1])

        if ck.storage_cost is not None:
            terms.append(ck.storage_cost / self.c_ref)
            weights.append(self.beta_cost[2])

        if not terms:
            return None
        total_w = sum(weights)
        if total_w <= 0:
            return None
        return _clip01(sum(w * u for w, u in zip(weights, terms, strict=True)) / total_w)

    def u_co2(self, kpis: KPIBundle) -> float | None:
        """Urgence carbone : dépassement de la cible d'émissions.

        u = clip((total − cible) / (max − cible + ε), 0, 1) sur les émissions
        horaires totales (``CO2KPIs.total_g_h``).

        Args:
            kpis: bundle KPI du nœud (bloc ``co2``).

        Returns:
            Urgence dans [0, 1], ou None si total, cible ou max manquent.
        """
        co2 = kpis.co2
        total = co2.total_g_h
        if total is None or co2.co2_target_g_h is None or co2.co2_max_g_h is None:
            return None
        # Garde E9.6 : si max <= cible (bornes incohérentes mais valides champ à
        # champ), l'ancien dénominateur « max − cible + eps » pouvait valoir 0
        # exactement (ZeroDivisionError). On force un span strictement positif :
        # tout dépassement de la cible sature alors immédiatement vers 1.
        span = max(co2.co2_max_g_h - co2.co2_target_g_h, 0.0) + self.eps
        return _clip01((total - co2.co2_target_g_h) / span)

    # --- Agrégation -----------------------------------------------------------

    def blocks(
        self,
        t: float,
        kpis: KPIBundle,
        milestones: list[Milestone] | None = None,
        t0_ts: float = 0.0,
        u_time_override: float | None = None,
    ) -> dict[str, float | None]:
        """Calcule les six urgences partielles d'un nœud.

        ``u_time_override`` est le point d'extension du mode Monte Carlo
        (E13) — la simulation calcule P(C_i > d_i) sur tout le graphe et
        l'injecte nœud par nœud ; simulate_shock reste analytique (rapidité).
        Quand il est fourni (non-None), le bloc ``time`` prend cette valeur
        clipée sur [0, 1] au lieu du calcul local (analytique ou jalons),
        y compris si le calcul local aurait donné None : le bloc devient
        alors actif. :meth:`u_time` lui-même n'est pas modifié — l'override
        se joue uniquement au niveau de l'agrégation.

        Args:
            t: date courante (heures depuis t0 projet).
            kpis: bundle KPI du nœud.
            milestones: jalons du nœud, propagés au bloc ``time`` (u_time v2).
            t0_ts: origine du référentiel projet (epoch s), propagée au bloc
                ``time``.
            u_time_override: urgence temporelle imposée (mode Monte Carlo),
                clipée sur [0, 1] ; None → calcul local via :meth:`u_time`.

        Returns:
            Dictionnaire ``{nom_de_bloc: urgence ou None}`` (cf. :data:`BLOCKS`).

        Raises:
            ValueError: si ``u_time_override`` est NaN ou infini.
        """
        if u_time_override is None:
            u_time = self.u_time(t, kpis, milestones=milestones, t0_ts=t0_ts)
        else:
            if not math.isfinite(u_time_override):
                raise ValueError(f"u_time_override doit être un réel fini, reçu {u_time_override}")
            u_time = _clip01(u_time_override)
        return {
            "time": u_time,
            "cap": self.u_cap(kpis),
            "perf": self.u_perf(kpis),
            "risk": self.u_risk(kpis),
            "cost": self.u_cost(kpis),
            "co2": self.u_co2(kpis),
        }

    def ur_local(
        self,
        t: float,
        kpis: KPIBundle,
        status: TaskStatus = TaskStatus.ACTIVE,
        milestones: list[Milestone] | None = None,
        t0_ts: float = 0.0,
        u_time_override: float | None = None,
    ) -> float:
        """Urgence réelle locale par OU probabiliste pondéré des blocs.

        ur = 1 − Π_m (1 − u_m)^ω_m sur les blocs non-None de poids ω_m > 0 :
        un seul bloc saturé (u_m = 1) suffit à rendre le nœud urgent.

        Les règles de statut (DONE → 0.0, ABANDONED → 1.0) sont déléguées à
        :func:`supplyscore.core.status_rules.effective_ur_local`, source de
        vérité unique — elles restent prioritaires même quand
        ``u_time_override`` est fourni.

        ``u_time_override`` est le point d'extension du mode Monte Carlo
        (E13) — la simulation calcule P(C_i > d_i) sur tout le graphe et
        l'injecte nœud par nœud ; simulate_shock reste analytique (rapidité).
        Le paramètre est simplement propagé à :meth:`blocks`.

        Args:
            t: date courante (heures depuis t0 projet).
            kpis: bundle KPI du nœud.
            status: statut de la tâche portée par le nœud.
            milestones: jalons du nœud, propagés au bloc ``time`` (u_time v2).
            t0_ts: origine du référentiel projet (epoch s), propagée au bloc
                ``time``.
            u_time_override: urgence temporelle imposée (mode Monte Carlo),
                clipée sur [0, 1] ; None → calcul local via :meth:`u_time`.

        Returns:
            Urgence locale dans [0, 1] ; 0.0 si tous les blocs sont None.

        Raises:
            ValueError: si ``u_time_override`` est NaN ou infini.
        """
        product = 1.0
        any_block = False
        block_values = self.blocks(
            t, kpis, milestones=milestones, t0_ts=t0_ts, u_time_override=u_time_override
        )
        for name, u in block_values.items():
            if u is None:
                continue
            w = self.omega.get(name, 1.0)
            if w == 0:
                continue
            any_block = True
            product *= (1.0 - _clip01(u)) ** w
        aggregated = _clip01(1.0 - product) if any_block else 0.0
        return effective_ur_local(status, aggregated)
