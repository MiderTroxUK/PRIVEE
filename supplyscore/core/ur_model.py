"""Urgence reelle Ur - agregation de blocs KPI en une urgence locale  dans  [0, 1].

Chaque bloc (temps, capacite, performance, risque, cout, CO2) produit une
urgence partielle dans [0, 1] ou None si les KPIs necessaires manquent.
L'agregation est un OU probabiliste pondere : un seul bloc critique suffit
a rendre le noeud urgent, les blocs manquants sont simplement ignores.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from supplyscore.core.status_rules import effective_ur_local
from supplyscore.domain.milestones import Milestone, next_active_milestone, theoretical_progress
from supplyscore.domain.models import KPIBundle, TaskStatus, TimeKPIs

#: Noms des blocs d'urgence, dans l'ordre d'agregation.
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
        sigma: ecart-type strictement positif.

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
    """Urgence temporelle a singularite finie (Sornette & Johansen).

    L'urgence diverge de facon hyperbolique a l'approche de l'echeance tc,
    ecrasee par tanh pour rester dans [0, 1] avant tc. Apres tc la tache est
    en retard : l'urgence depasse 1 et croit lineairement.

    - t <= tc : tanh(K / max(tc - t, eps_min)) ;
    - t >  tc : 1 + K-(t - tc).

    Args:
        t: date courante (heures).
        tc: date critique (singularite).
        K: gain de la divergence, > 0.
        eps_min: garde-fou numerique pres de la singularite, > 0.

    Returns:
        Urgence >= 0, dans [0, 1] avant tc, > 1 apres tc.

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
    """Urgence percue simulee - actualisation hyperbolique (Mazur).

    Ud(t) = 1 / (1 + k-max(tc - t, 0)) : l'humain sous-pondere les echeances
    lointaines puis " se reveille " hyperboliquement pres de tc. Sert au
    generateur de donnees simulees.

    Args:
        t: date courante (heures).
        tc: date critique.
        k: taux d'actualisation hyperbolique, >= 0.

    Returns:
        Urgence percue dans [0, 1].

    Raises:
        ValueError: si k < 0.
    """
    if k < 0:
        raise ValueError(f"k doit être >= 0, reçu {k}")
    return _clip01(1.0 / (1.0 + k * max(tc - t, 0.0)))


def filtered_error(ud: float, ur_t: float, eps_tol: float = 0.0) -> float:
    """Erreur Ud - Ur filtree par une zone morte de tolerance.

    e = sign(Ud - Ur) - max(|Ud - Ur| - eps_tol, 0) : les ecarts plus petits
    que eps_tol sont consideres comme du bruit et ramenes a 0.

    Args:
        ud: urgence declaree.
        ur_t: urgence reelle a la date t.
        eps_tol: demi-largeur de la zone morte, >= 0.

    Returns:
        Erreur signee filtree.

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
    """Modele d'urgence reelle locale d'un noeud a partir de ses KPIs.

    Chaque methode ``u_*`` renvoie une urgence partielle dans [0, 1] ou None
    si les KPIs necessaires manquent. :meth:`ur_local` agrege les blocs
    disponibles par OU probabiliste pondere.

    Attributes:
        alpha_cap: poids (volume, poids, flux) du bloc capacite.
        beta_cost: poids (surcout op, tarif, stockage) du bloc cout.
        t_ref_h: horizon de reference (heures) pour la normalisation du risque.
        c_ref: cout de stockage de reference pour la normalisation du cout.
        kappa_retard: gain kappa_retard >= 0 de la penalite de retard
            d'avancement (u_time v2, jalon en retard sur son planning).
        kappa_avance: gain kappa_avance >= 0 du bonus d'avance (u_time v2,
            jalon en avance sur son planning).
        omega: poids d'agregation omega_m >= 0 par bloc (defaut : tous 1.0).
        eps: garde-fou numerique des divisions.
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
        """Valide les poids d'agregation et les gains de modulation planning.

        Raises:
            ValueError: si un poids omega_m est negatif, si un bloc est inconnu
                ou si kappa_retard / kappa_avance est negatif.
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

    # Blocs d'urgence

    def _p_late(self, slack_h: float, lead_time_h: float, lead_time_std_h: float | None) -> float:
        """Probabilite de retard P(L > slack) pour L ~ Normale(mu, sigma).

        sigma = ``lead_time_std_h`` si fourni, sinon 0.25-mu par defaut ;
        sigma <= 0 degenere en lead time deterministe (retard certain ou
        impossible selon la marge restante).

        Args:
            slack_h: marge restante avant l'echeance (heures).
            lead_time_h: lead time moyen mu (heures).
            lead_time_std_h: ecart-type sigma du lead time (heures), ou None.

        Returns:
            P(L > slack) dans [0, 1].
        """
        mu = lead_time_h
        if lead_time_std_h is None:
            # sigma par defaut RELATIF (0.25-mu) : on travaille sur l'echelle normalisee slack/mu - mathematiquement identique a N(mu, 0.25-mu), mais sans le sous-passement denormalise de 0.25-mu vers 0.0 qui rendait p_late non monotone en mu (contre-exemple Hypothesis : mu = 5e-324 sautait a 1.0 alors que mu = 1.0 donnait Phi(4) < 1).
            if mu <= 0.0:
                # Lead time nul : retard certain ssi l'echeance est deja passee.
                return 1.0 if mu > slack_h else 0.0
            return _clip01(_normal_sf(slack_h / mu, 1.0, 0.25))
        std = lead_time_std_h
        if std <= 0:
            # Lead time deterministe : retard certain ou impossible.
            return 1.0 if mu > slack_h else 0.0
        return _clip01(_normal_sf(slack_h, mu, std))

    def u_base_jalon(
        self,
        slack_h: float,
        tk: TimeKPIs,
        progress: float,
        retard_choc_h: float = 0.0,
    ) -> float:
        """Socle probabiliste du retard : travail RESTANT plus temps PERDU.

        Deux termes de nature differente, et les confondre est precisement le
        defaut corrige ici :

        - **le cycle restant**, PROPORTIONNEL a ce qu'il reste a faire. Le lead
          time nominal mu mesure un cycle COMPLET ; le comparer tel quel a la
          marge d'un jalon deja avance confond " demarrer ET finir " avec
          " finir ", et le socle sature des que mu depasse la marge quel que
          soit l'avancement. Par linearite de la loi normale,
          L_restant ~ Normale((1 - p)-mu, (1 - p)-sigma) ;
        - **le temps perdu**, ADDITIF (``time.delay_h``). Quatre
          semaines d'arret coutent quatre semaines qu'on soit a 10 % ou a 90 %
          du jalon : ce terme ne doit PAS etre mis a l'echelle de l'avancement,
          sous peine de s'evaporer precisement sur les jalons proches de leur
          echeance.

        Soit P(L_restant + retard > marge), c'est-a-dire
        P(L_restant > marge - retard).

        Consequence voulue : un jalon a 90 % dont le cycle nominal est long
        n'est plus declare perdu d'avance, MAIS un noeud arrete quatre semaines
        le reste. A progress = 0 et sans choc, la formule redonne exactement
        le socle anterieur (c'est un sur-ensemble).

        Args:
            slack_h: marge restante avant l'echeance du jalon (heures, >= 0).
            tk: bloc ``time`` des KPIs (lead time nominal et sa dispersion).
            progress: avancement du jalon actif dans [0, 1].
            retard_choc_h: temps de production perdu et non encore rattrape
                (``time.delay_h``), en heures ; 0.0 si inconnu. A ne pas
                confondre avec ``risk.recovery_time_h``, qui est un parametre
                de risque par noeud et non un etat accumule.

        Returns:
            P(retard) dans [0, 1] ; 0.0 si le lead time est absent ET qu'aucun
            choc n'est en cours (choix documente : socle nul, la modulation
            planning joue seule).
        """
        reste = _clip01(1.0 - progress)
        marge = slack_h - max(retard_choc_h, 0.0)
        if reste <= 0.0:
            # TRAVAIL ACHEVE : ni le cycle restant ni le temps perdu ne peuvent repousser un achevement DEJA atteint. Sans ce garde-fou, reste = 0 annule mu, _p_late bascule dans sa branche degeneree et renvoie " 1.0 si 0 > marge ", c'est-a-dire retard CERTAIN des que le temps perdu depasse la marge - sur un jalon dont tout le travail est fait. Le temps perdu est deja DANS l'avancement observe (un noeud arrete n'a pas avance) ; le compter encore ici le compte deux fois.
            return 0.0
        if tk.lead_time_h is None:
            # Pas de cycle connu : seul le temps perdu peut creer un retard.
            return 1.0 if marge < 0.0 else 0.0
        if tk.lead_time_h <= 0.0:
            # Lead time degenere : on laisse _p_late trancher (il gere la division par zero et le sous-passement denormalise).
            std_nul = None if tk.lead_time_std_h is None else tk.lead_time_std_h * reste
            return self._p_late(marge, tk.lead_time_h * reste, std_nul)
        # sigma decroit en RACINE du travail restant, pas lineairement : le travail restant est une somme d'increments, sa variance decroit lineairement avec leur nombre, donc son ecart-type en sqrt(1 - p). Une mise a l'echelle lineaire supposerait le cycle parfaitement correle. A progress = 0 les deux formules coincident (sqrt1 = 1). HONNETETE SUR LA PORTEE : ce choix est le bon statistiquement, mais il est SANS EFFET MESURABLE sur HELIOS - rejeu complet, scores et binarite identiques au millieme pres. Il ne corrige donc PAS la sur-confiance de P(jalon rate), qui sort exactement 0 ou 1 dans 95 % des cas. La cause est ailleurs : l'avancement du jalon entre dans le calcul comme une valeur EXACTE, alors que c'est une declaration - la grandeur la moins fiable du dispositif, et precisement celle que cet outil existe pour mettre en doute.
        sigma = tk.lead_time_std_h if tk.lead_time_std_h is not None else 0.25 * tk.lead_time_h
        return self._p_late(marge, tk.lead_time_h * reste, sigma * math.sqrt(reste))

    def u_time(
        self,
        t: float,
        kpis: KPIBundle,
        milestones: list[Milestone] | None = None,
        t0_ts: float = 0.0,
    ) -> float | None:
        """Urgence temporelle : P(retard), modulee par l'avancement jalon (v2).

        **v1 (sans jalon actif)** - si ``milestones`` est None, vide ou sans
        jalon ACTIVE, comportement inchange : u = P(L > d - t) avec
        d = ``deadline_h`` des KPIs et L ~ Normale(lead_time_h,
        lead_time_std_h), l'ecart-type valant 0.25-lead_time par defaut ;
        1.0 si t a depasse la deadline ; None si ``deadline_h`` ou
        ``lead_time_h`` manquent.

        **v2 (jalon actif)** - soit M* = :func:`next_active_milestone`,
        d* = (M*.deadline_ts - t0_ts)/3600 et s* = (M*.start_ts - t0_ts)/3600
        (heures depuis t0 projet) :

        - si t > d* : u_time = 1.0 (retard avere) ;
        - sinon :
            - u_base = P(L_restant + retard > d* - t) avec L_restant ~
              Normale((1 - progress)-mu, sqrt(1 - progress)-sigma) et retard =
              ``time.delay_h`` - cf. :meth:`u_base_jalon` : le socle
              porte sur le travail RESTANT plus le temps PERDU, pas sur un
              cycle complet ;
            - p_th = clip01((t - s*) / (d* - s*)), avancement theorique
              (1.0 si d* <= s*) ;
            - r = p_th - M*.progress  dans  [-1, 1], retard d'avancement ;
            - u_time = clip01(u_base + kappa_retard-max(r, 0) - kappa_avance-max(-r, 0)).

        La forme ADDITIVE est volontaire : la contribution kappa_retard-max(r, 0)
        reste isolable du socle probabiliste u_base pour l'explicabilite.

        Choix documente : si ``lead_time_h`` est None alors qu'un jalon est
        actif, u_base = 0.0 (et non None) - le jalon fournit l'echeance et
        l'avancement, la modulation planning s'applique donc quand meme.

        Le socle reagit aux chocs par deux canaux : ``time.lead_time_h`` (le
        cycle est durablement plus lent - retard fournisseur, transport) et
        ``time.delay_h`` (du temps de production a ete perdu - panne,
        accident, greve, rupture, cyber ; cf.
        :func:`supplyscore.domain.events._arret_impact`). Sans le second, ce
        bloc restait aveugle a tous les chocs de capacite.

        Args:
            t: date courante (heures depuis t0 projet).
            kpis: bundle KPI du noeud (bloc ``time``).
            milestones: jalons du noeud ; None ou sans jalon ACTIVE -> v1.
            t0_ts: origine du referentiel projet (epoch s), pour convertir
                les timestamps des jalons en heures.

        Returns:
            Urgence temporelle dans [0, 1] ; None uniquement en v1 quand
            ``deadline_h`` ou ``lead_time_h`` manquent.
        """
        tk = kpis.time
        m_star = next_active_milestone(milestones) if milestones else None
        if m_star is None:
            # v1 : echeance portee par les KPIs.
            if tk.deadline_h is None or tk.lead_time_h is None:
                return None
            if t > tk.deadline_h:
                return 1.0
            # Le temps perdu CONSOMME la marge ici aussi. Sans ce terme, un noeud sans jalon actif restait totalement aveugle aux chocs de capacite (mesure : 1 000 h de production perdue laissaient u_time a 0.0000), alors que le simulateur MC et la prevision, qui replient tous deux sur ``deadline_h``, appliquaient bien le retard. Trois estimateurs censes partager le meme modele d'achevement en donnaient deux reponses opposees sur la meme classe de noeuds.
            retard = max(tk.delay_h or 0.0, 0.0)
            return self._p_late(
                tk.deadline_h - t - retard, tk.lead_time_h, tk.lead_time_std_h
            )
        # v2 : echeance portee par le prochain jalon actif M*.
        d_star = (m_star.deadline_ts - t0_ts) / 3600.0
        if t > d_star:
            return 1.0
        retard = tk.delay_h or 0.0
        u_base = self.u_base_jalon(d_star - t, tk, m_star.progress, retard)
        p_th = theoretical_progress(m_star, t0_ts + t * 3600.0)
        r = p_th - m_star.progress
        return _clip01(u_base + self.kappa_retard * max(r, 0.0) - self.kappa_avance * max(-r, 0.0))

    def u_cap(self, kpis: KPIBundle) -> float | None:
        """Urgence capacitaire : saturation volume/poids et deficit de flux.

        u = clip(alpha1-(1 - vol_restant/vol_max) + alpha2-(1 - poids_restant/poids_max)
        + alpha3-[(demande - flux)/(demande + epsilon)]+, 0, 1), les alpha etant renormalises
        sur les termes effectivement calculables.

        Args:
            kpis: bundle KPI du noeud (blocs ``inventory`` et ``network``).

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
        """Urgence de performance : 1 - OEE (taux de rendement synthetique).

        Args:
            kpis: bundle KPI du noeud (bloc ``oee``).

        Returns:
            1 - OEE dans [0, 1], ou None si l'OEE n'est pas calculable.
        """
        oee = kpis.oee.oee
        if oee is None:
            return None
        return _clip01(1.0 - oee)

    def u_risk(self, kpis: KPIBundle) -> float | None:
        """Urgence de risque : exposition a la defaillance, enrichie.

        base = 1 - exp(-p_defaillance - t_recup - severite / T_ref), puis
        composition OU probabiliste avec les expositions environnementale et
        politique : u = 1 - (1 - base)(1 - env)(1 - pol). Les expositions
        manquantes comptent pour 0. Les composantes du noyau manquantes
        prennent des valeurs neutres (p -> 0, t_recup -> T_ref, severite -> 1).

        Args:
            kpis: bundle KPI du noeud (bloc ``risk``).

        Returns:
            Urgence dans [0, 1], ou None si p_defaillance, t_recup et
            severite manquent tous les trois.
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
        """Urgence de cout : derive operationnelle, tarifs et stockage.

        u = clip(beta1-(cout_op - cout_nominal)/(cout_nominal + epsilon)
        + beta2-max(tarif - 1, 0) + beta3-cout_stockage/C_ref, 0, 1), le tarif
        etant un multiplicateur (1 = neutre). Les beta sont renormalises sur
        les termes disponibles.

        Args:
            kpis: bundle KPI du noeud (bloc ``cost``).

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
        """Urgence carbone : depassement de la cible d'emissions.

        u = clip((total - cible) / (max - cible + epsilon), 0, 1) sur les emissions
        horaires totales (``CO2KPIs.total_g_h``).

        Args:
            kpis: bundle KPI du noeud (bloc ``co2``).

        Returns:
            Urgence dans [0, 1], ou None si total, cible ou max manquent.
        """
        co2 = kpis.co2
        total = co2.total_g_h
        if total is None or co2.co2_target_g_h is None or co2.co2_max_g_h is None:
            return None
        # Garde E9.6 : si max <= cible (bornes incoherentes mais valides champ a champ), l'ancien denominateur " max - cible + eps " pouvait valoir 0 exactement (ZeroDivisionError). On force un span strictement positif : tout depassement de la cible sature alors immediatement vers 1.
        span = max(co2.co2_max_g_h - co2.co2_target_g_h, 0.0) + self.eps
        return _clip01((total - co2.co2_target_g_h) / span)

    # Agregation

    def blocks(
        self,
        t: float,
        kpis: KPIBundle,
        milestones: list[Milestone] | None = None,
        t0_ts: float = 0.0,
        u_time_override: float | None = None,
    ) -> dict[str, float | None]:
        """Calcule les six urgences partielles d'un noeud.

        ``u_time_override`` est le point d'extension du mode Monte Carlo
        (E13) - la simulation calcule P(C_i > d_i) sur tout le graphe et
        l'injecte noeud par noeud ; simulate_shock reste analytique (rapidite).
        Quand il est fourni (non-None), le bloc ``time`` prend cette valeur
        clipee sur [0, 1] au lieu du calcul local (analytique ou jalons),
        y compris si le calcul local aurait donne None : le bloc devient
        alors actif. :meth:`u_time` lui-meme n'est pas modifie - l'override
        se joue uniquement au niveau de l'agregation.

        Args:
            t: date courante (heures depuis t0 projet).
            kpis: bundle KPI du noeud.
            milestones: jalons du noeud, propages au bloc ``time`` (u_time v2).
            t0_ts: origine du referentiel projet (epoch s), propagee au bloc
                ``time``.
            u_time_override: urgence temporelle imposee (mode Monte Carlo),
                clipee sur [0, 1] ; None -> calcul local via :meth:`u_time`.

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
        """Urgence reelle locale par OU probabiliste pondere des blocs.

        ur = 1 - Pi_m (1 - u_m)^omega_m sur les blocs non-None de poids omega_m > 0 :
        un seul bloc sature (u_m = 1) suffit a rendre le noeud urgent.

        Les regles de statut (DONE -> 0.0, ABANDONED -> 1.0) sont deleguees a
        :func:`supplyscore.core.status_rules.effective_ur_local`, source de
        verite unique - elles restent prioritaires meme quand
        ``u_time_override`` est fourni.

        ``u_time_override`` est le point d'extension du mode Monte Carlo
        (E13) - la simulation calcule P(C_i > d_i) sur tout le graphe et
        l'injecte noeud par noeud ; simulate_shock reste analytique (rapidite).
        Le parametre est simplement propage a :meth:`blocks`.

        Args:
            t: date courante (heures depuis t0 projet).
            kpis: bundle KPI du noeud.
            status: statut de la tache portee par le noeud.
            milestones: jalons du noeud, propages au bloc ``time`` (u_time v2).
            t0_ts: origine du referentiel projet (epoch s), propagee au bloc
                ``time``.
            u_time_override: urgence temporelle imposee (mode Monte Carlo),
                clipee sur [0, 1] ; None -> calcul local via :meth:`u_time`.

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
