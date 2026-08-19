"""Tests du simulateur Monte Carlo des dates d'achèvement (phase E13, Lot 13.1).

Cas analytiques (nœud isolé, chaîne et diamant déterministes), validation
croisée MC ↔ erf (LE test le plus important de la phase), familles de lois,
garde-fous et reproductibilité. Les tolérances stochastiques sont exprimées
en multiples de l'erreur-type (jamais à tolérance fixe arbitraire).
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from supplyscore.core.ur_model import UrModel
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import KPIBundle, SupplyArc, SupplyNode, TimeKPIs
from supplyscore.graph import InMemoryGraphRepository
from supplyscore.mc import (
    LoiLeadTime,
    ResultatMC,
    SimulateurLeadTime,
    resoudre_loi,
    tirer_lead_times,
)


def _noeud(
    node_id: str,
    lead: float | None = None,
    std: float | None = None,
    deadline: float | None = None,
) -> SupplyNode:
    """Nœud minimal avec les seuls KPIs temporels utiles à la simulation."""
    return SupplyNode(
        id=node_id,
        name=node_id,
        kpis=KPIBundle(time=TimeKPIs(lead_time_h=lead, lead_time_std_h=std, deadline_h=deadline)),
    )


def _repo_isole(
    lead: float | None, std: float | None, deadline: float | None
) -> InMemoryGraphRepository:
    """Dépôt à un seul nœud « n »."""
    repo = InMemoryGraphRepository()
    repo.add_node(_noeud("n", lead=lead, std=std, deadline=deadline))
    return repo


# --- Nœud isolé : normale tronquée et validation croisée MC <-> erf ----------


class TestNoeudIsole:
    def test_normale_tronquee_p_un_demi(self):
        """mu=100, sigma=20, deadline=200, t=100 : slack = mu -> p = 0.5 +- 3 SE."""
        repo = _repo_isole(lead=100.0, std=20.0, deadline=200.0)
        sim = SimulateurLeadTime(repo, n_tirages=10_000, graine=42, famille="normale")
        res = sim.executer(t=100.0)
        p = res.u_time["n"]
        assert p is not None
        # 3 erreurs-types a N=1e4 : 3 x 0.5/sqrt(10_000) = 0.015.
        assert abs(p - 0.5) <= 0.015
        assert res.ic95["n"] == pytest.approx(1.96 * math.sqrt(p * (1 - p) / 10_000))

    @pytest.mark.parametrize("deadline", [200.0, 230.0])
    def test_validation_croisee_mc_vs_erf(self, deadline: float):
        """VALIDATION CROISEE : nœud isolé normal, |p_MC - survie erf| <= 0.005.

        Le constructeur borne N a 50 000 : on atteint N effectif = 100 000 en
        moyennant DEUX exécutions indépendantes (graines distinctes) de
        50 000 tirages — p_MC reste l'estimateur empirique sur 1e5 tirages.
        Pour un nœud isolé, P(t + L > d) doit coïncider avec la survie
        analytique de L au seuil (d − t), ici UrModel()._p_late (erf).
        """
        mu, sigma, t = 100.0, 20.0, 100.0
        repo = _repo_isole(lead=mu, std=sigma, deadline=deadline)
        p_hats = []
        for graine in (11, 22):
            sim = SimulateurLeadTime(repo, n_tirages=50_000, graine=graine, famille="normale")
            p = sim.executer(t=t).u_time["n"]
            assert p is not None
            p_hats.append(p)
        p_mc = sum(p_hats) / len(p_hats)
        p_erf = UrModel()._p_late(deadline - t, mu, sigma)
        # Recalcul erf direct (independant de UrModel) : les deux references concordent.
        z = (deadline - t - mu) / (sigma * math.sqrt(2.0))
        assert p_erf == pytest.approx(0.5 * (1.0 - math.erf(z)), abs=1e-12)
        assert abs(p_mc - p_erf) <= 0.005


# --- Chaine et diamant deterministes ------------------------------------------


def _repo_chaine() -> InMemoryGraphRepository:
    """Chaine A -> B -> C avec leads deterministes 10, 20, 30 h (s = 0)."""
    repo = InMemoryGraphRepository()
    repo.add_node(_noeud("A", lead=10.0, std=0.0))
    repo.add_node(_noeud("B", lead=20.0, std=0.0))
    repo.add_node(_noeud("C", lead=30.0, std=0.0))
    repo.add_arc(SupplyArc(source_id="A", target_id="B"))
    repo.add_arc(SupplyArc(source_id="B", target_id="C"))
    return repo


class TestChaineDeterministe:
    def test_deadline_55_retard_certain(self):
        """10+20+30 = 60 h > 55 : p == 1.0 EXACTEMENT (aucun bruit MC)."""
        repo = _repo_chaine()
        node_c = repo.get_node("C")
        assert node_c is not None
        node_c.kpis.time.deadline_h = 55.0
        res = SimulateurLeadTime(repo, n_tirages=2_000, graine=1).executer(t=0.0)
        assert res.u_time["C"] == 1.0
        assert res.ic95["C"] == 0.0

    def test_deadline_65_retard_impossible(self):
        """10+20+30 = 60 h < 65 : p == 0.0 exactement."""
        repo = _repo_chaine()
        node_c = repo.get_node("C")
        assert node_c is not None
        node_c.kpis.time.deadline_h = 65.0
        res = SimulateurLeadTime(repo, n_tirages=2_000, graine=1).executer(t=0.0)
        assert res.u_time["C"] == 0.0
        assert res.ic95["C"] == 0.0

    def test_achevements_cumules_exacts(self):
        """Quantiles degeneres : C_A = 10, C_B = 30, C_C = 60 exactement."""
        res = SimulateurLeadTime(_repo_chaine(), n_tirages=2_000, graine=1).executer(t=0.0)
        assert res.completion_quantiles["A"] == {0.5: 10.0, 0.9: 10.0}
        assert res.completion_quantiles["B"] == {0.5: 30.0, 0.9: 30.0}
        assert res.completion_quantiles["C"] == {0.5: 60.0, 0.9: 60.0}


class TestDiamantDeterministe:
    def test_max_des_chemins_paralleles(self):
        """Chemins 40 h et 50 h vers le client : C_client = 50 + L_client = 60.

        Verifie via les quantiles que la propagation prend le MAX (50), pas le
        minimum (40) ni la somme des chemins (90).
        """
        repo = InMemoryGraphRepository()
        repo.add_node(_noeud("A", lead=40.0, std=0.0))
        repo.add_node(_noeud("B", lead=50.0, std=0.0))
        repo.add_node(_noeud("client", lead=10.0, std=0.0))
        repo.add_arc(SupplyArc(source_id="A", target_id="client"))
        repo.add_arc(SupplyArc(source_id="B", target_id="client"))
        res = SimulateurLeadTime(repo, n_tirages=2_000, graine=3).executer(t=0.0)
        assert res.completion_quantiles["client"] == {0.5: 60.0, 0.9: 60.0}

    def test_client_stochastique_decale_de_50(self):
        """Client lognormal : mediane(C_client) = 50 + mediane theorique de L."""
        repo = InMemoryGraphRepository()
        repo.add_node(_noeud("A", lead=40.0, std=0.0))
        repo.add_node(_noeud("B", lead=50.0, std=0.0))
        repo.add_node(_noeud("client", lead=10.0, std=2.0))
        repo.add_arc(SupplyArc(source_id="A", target_id="client"))
        repo.add_arc(SupplyArc(source_id="B", target_id="client"))
        res = SimulateurLeadTime(repo, n_tirages=50_000, graine=4).executer(t=0.0)
        var_ln = math.log(1.0 + (2.0 / 10.0) ** 2)
        mediane_l = 10.0 * math.exp(-var_ln / 2.0)  # exp(mu_ln)
        # SE(mediane) = sqrt(0.25/N)/f(mediane) ~ 0.011 h a N=5e4 : tolerance 4 SE.
        assert res.completion_quantiles["client"][0.5] == pytest.approx(50.0 + mediane_l, abs=0.05)


# --- Familles de lois -----------------------------------------------------------


class TestFamillesDeLois:
    def test_lognormale_retrouve_les_moments(self):
        """Parametrage par moments : mean/std empiriques a 2 % de (m, s) a N=1e5."""
        loi = resoudre_loi(_noeud("n", lead=100.0, std=25.0))
        assert loi.famille == "lognormale"
        rng = np.random.Generator(np.random.PCG64(123))
        x = tirer_lead_times(loi, rng, 100_000)
        assert float(np.mean(x)) == pytest.approx(100.0, rel=0.02)
        assert float(np.std(x)) == pytest.approx(25.0, rel=0.02)

    def test_std_par_defaut_un_quart_de_m(self):
        """lead_time_std_h absent : s = 0.25 x m par defaut."""
        loi = resoudre_loi(_noeud("n", lead=100.0, std=None))
        assert loi == LoiLeadTime("lognormale", m=100.0, s=25.0)

    def test_s_nul_degenere_en_deterministe(self):
        """s == 0 : famille deterministe, tirages constants a m."""
        loi = resoudre_loi(_noeud("n", lead=100.0, std=0.0))
        assert loi.famille == "deterministe"
        rng = np.random.Generator(np.random.PCG64(0))
        assert (tirer_lead_times(loi, rng, 2_000) == 100.0).all()

    def test_lead_absent_vaut_zero_deterministe(self):
        """lead_time_h absent : L = 0 (le nœud n'ajoute aucun delai)."""
        loi = resoudre_loi(_noeud("n"))
        assert loi == LoiLeadTime("deterministe", m=0.0)
        repo = _repo_isole(lead=None, std=None, deadline=10.0)
        res = SimulateurLeadTime(repo, n_tirages=2_000, graine=5).executer(t=0.0)
        assert res.u_time["n"] == 0.0  # C = t + 0 = 0 <= 10

    def test_lognormale_m_nul_avec_s_positif_degenere(self):
        """m <= 0 : la lognormale est indefinie (ln m), repli deterministe."""
        loi = resoudre_loi(_noeud("n", lead=0.0, std=5.0))
        assert loi == LoiLeadTime("deterministe", m=0.0)

    def test_normale_tronquee_a_zero_par_clip(self):
        """Troncature par clip : aucun tirage negatif meme si m << s."""
        loi = resoudre_loi(_noeud("n", lead=1.0, std=10.0), famille_defaut="normale")
        assert loi.famille == "normale"
        rng = np.random.Generator(np.random.PCG64(7))
        x = tirer_lead_times(loi, rng, 10_000)
        assert (x >= 0.0).all()
        assert float(np.min(x)) == 0.0  # la masse P(X<0) est deplacee sur {0}

    def test_triangulaire_detectee_via_champs_optionnels(self):
        """min/mode/max presents (via getattr) : famille triangulaire."""
        node = _noeud("n", lead=100.0, std=20.0)
        node.kpis.time.lead_time_min_h = 10.0  # type: ignore[attr-defined]
        node.kpis.time.lead_time_mode_h = 20.0  # type: ignore[attr-defined]
        node.kpis.time.lead_time_max_h = 40.0  # type: ignore[attr-defined]
        loi = resoudre_loi(node)
        assert loi == LoiLeadTime("triangulaire", minimum=10.0, mode=20.0, maximum=40.0)
        rng = np.random.Generator(np.random.PCG64(9))
        x = tirer_lead_times(loi, rng, 100_000)
        assert float(np.min(x)) >= 10.0
        assert float(np.max(x)) <= 40.0
        # E[Tri(a, c, b)] = (a + c + b)/3 ; SE(mean) ~ 6.2/sqrt(1e5) ~ 0.02.
        assert float(np.mean(x)) == pytest.approx((10.0 + 20.0 + 40.0) / 3.0, abs=0.1)

    def test_triangulaire_bornes_incoherentes(self):
        """min > mode : ValueError explicite (et pas l'erreur anglaise de numpy)."""
        node = _noeud("n")
        node.kpis.time.lead_time_min_h = 30.0  # type: ignore[attr-defined]
        node.kpis.time.lead_time_mode_h = 20.0  # type: ignore[attr-defined]
        node.kpis.time.lead_time_max_h = 40.0  # type: ignore[attr-defined]
        with pytest.raises(ValueError, match="triangulaires incohérentes"):
            resoudre_loi(node)

    def test_triangulaire_degeneree_min_egale_max(self):
        """min == mode == max : repli deterministe au mode."""
        node = _noeud("n")
        node.kpis.time.lead_time_min_h = 20.0  # type: ignore[attr-defined]
        node.kpis.time.lead_time_mode_h = 20.0  # type: ignore[attr-defined]
        node.kpis.time.lead_time_max_h = 20.0  # type: ignore[attr-defined]
        assert resoudre_loi(node) == LoiLeadTime("deterministe", m=20.0)

    def test_famille_defaut_inconnue(self):
        """Famille par defaut hors {lognormale, normale} : ValueError."""
        with pytest.raises(ValueError, match="Famille de loi inconnue"):
            resoudre_loi(_noeud("n", lead=10.0), famille_defaut="weibull")

    def test_tirer_famille_inconnue(self):
        """LoiLeadTime forgee avec une famille inconnue : ValueError au tirage."""
        rng = np.random.Generator(np.random.PCG64(0))
        with pytest.raises(ValueError, match="Famille de loi inconnue"):
            tirer_lead_times(LoiLeadTime("weibull", m=1.0, s=1.0), rng, 10)


# --- Echeances : jalons, repli KPI, absences, retard avere -----------------------


class TestEcheances:
    def test_deadline_absente_u_time_none_ic95_zero(self):
        repo = _repo_isole(lead=100.0, std=20.0, deadline=None)
        res = SimulateurLeadTime(repo, n_tirages=2_000, graine=6).executer(t=0.0)
        assert res.u_time["n"] is None
        assert res.ic95["n"] == 0.0
        assert set(res.completion_quantiles["n"]) == {0.5, 0.9}  # quantiles fournis

    def test_noeud_en_retard_force_a_un(self):
        """d <= t : u_time = 1.0 EXACTEMENT (hors estimateur), ic95 = 0.0."""
        repo = _repo_isole(lead=100.0, std=20.0, deadline=50.0)
        res = SimulateurLeadTime(repo, n_tirages=2_000, graine=6).executer(t=100.0)
        assert res.u_time["n"] == 1.0
        assert res.ic95["n"] == 0.0
        # Cas limite d == t : encore en retard avere.
        repo2 = _repo_isole(lead=100.0, std=20.0, deadline=100.0)
        res2 = SimulateurLeadTime(repo2, n_tirages=2_000, graine=6).executer(t=100.0)
        assert res2.u_time["n"] == 1.0

    def test_deadline_du_prochain_jalon_actif(self):
        """d = (deadline_ts - t0_ts)/3600 du jalon ACTIF le plus proche."""
        t0_ts = 1_000_000.0
        repo = _repo_isole(lead=100.0, std=20.0, deadline=None)
        jalons = {
            "n": [
                Milestone(
                    id="m-done",
                    node_id="n",
                    name="Proto",
                    deadline_ts=t0_ts + 150.0 * 3600.0,
                    status=MilestoneStatus.DONE,
                ),
                Milestone(
                    id="m-actif",
                    node_id="n",
                    name="Serie",
                    deadline_ts=t0_ts + 200.0 * 3600.0,
                    status=MilestoneStatus.ACTIVE,
                ),
            ]
        }
        sim = SimulateurLeadTime(repo, n_tirages=10_000, graine=8, famille="normale")
        res = sim.executer(t=100.0, milestones_par_noeud=jalons, t0_ts=t0_ts)
        p = res.u_time["n"]
        assert p is not None
        assert abs(p - 0.5) <= 0.015  # slack = 200 - 100 = mu -> 0.5 +- 3 SE

    def test_jalons_tous_inactifs_repli_sur_deadline_kpi(self):
        """Aucun jalon ACTIF : repli sur kpis.time.deadline_h (v1)."""
        repo = _repo_isole(lead=10.0, std=0.0, deadline=5.0)
        jalons = {
            "n": [
                Milestone(
                    id="m1",
                    node_id="n",
                    name="Proto",
                    deadline_ts=1e9,
                    status=MilestoneStatus.ABANDONED,
                )
            ]
        }
        res = SimulateurLeadTime(repo, n_tirages=2_000, graine=9).executer(
            t=0.0, milestones_par_noeud=jalons
        )
        assert res.u_time["n"] == 1.0  # L = 10 > slack 5, deterministe


# --- Garde-fous -------------------------------------------------------------------


class TestGardeFous:
    @pytest.mark.parametrize("n", [1_999, 50_001, 0, -1])
    def test_n_tirages_hors_bornes(self, n: int):
        with pytest.raises(ValueError, match=r"n_tirages doit être dans \[2000, 50000\]"):
            SimulateurLeadTime(InMemoryGraphRepository(), n_tirages=n)

    @pytest.mark.parametrize("n", [2_000, 50_000])
    def test_n_tirages_bornes_incluses(self, n: int):
        sim = SimulateurLeadTime(InMemoryGraphRepository(), n_tirages=n)
        assert sim.n_tirages == n

    def test_famille_inconnue_au_constructeur(self):
        with pytest.raises(ValueError, match="Famille de loi inconnue"):
            SimulateurLeadTime(InMemoryGraphRepository(), famille="exponentielle")

    def test_garde_fou_memoire(self):
        """N x n_nœuds > 5e7 : ValueError français AVANT toute allocation."""
        repo = InMemoryGraphRepository()
        for i in range(1_001):  # 50_000 x 1_001 = 5.005e7 > 5e7
            repo.add_node(_noeud(f"n{i}", lead=1.0))
        sim = SimulateurLeadTime(repo, n_tirages=50_000, graine=0)
        with pytest.raises(ValueError, match="Budget mémoire dépassé"):
            sim.executer()

    def test_quantile_hors_bornes(self):
        repo = _repo_isole(lead=10.0, std=2.0, deadline=20.0)
        sim = SimulateurLeadTime(repo, n_tirages=2_000, graine=0)
        with pytest.raises(ValueError, match=r"quantile hors \[0, 1\]"):
            sim.executer(quantiles=(0.5, 1.5))


# --- Reproductibilite et resultat -----------------------------------------------


class TestReproductibilite:
    def _repo(self) -> InMemoryGraphRepository:
        repo = InMemoryGraphRepository()
        repo.add_node(_noeud("amont", lead=50.0, std=10.0))
        repo.add_node(_noeud("aval", lead=60.0, std=15.0, deadline=115.0))
        repo.add_arc(SupplyArc(source_id="amont", target_id="aval"))
        return repo

    def test_meme_graine_resultats_identiques_bit_a_bit(self):
        repo = self._repo()
        res1 = SimulateurLeadTime(repo, n_tirages=2_000, graine=777).executer(t=0.0)
        res2 = SimulateurLeadTime(repo, n_tirages=2_000, graine=777).executer(t=0.0)
        assert res1.u_time == res2.u_time
        assert res1.ic95 == res2.ic95
        assert res1.completion_quantiles == res2.completion_quantiles

    def test_graines_differentes_resultats_differents(self):
        repo = self._repo()
        res1 = SimulateurLeadTime(repo, n_tirages=2_000, graine=1).executer(t=0.0)
        res2 = SimulateurLeadTime(repo, n_tirages=2_000, graine=2).executer(t=0.0)
        assert res1.u_time != res2.u_time

    def test_resultat_immuable_et_metadonnees(self):
        repo = self._repo()
        res = SimulateurLeadTime(repo, n_tirages=2_000, graine=5).executer(t=0.0)
        assert isinstance(res, ResultatMC)
        assert res.n_tirages == 2_000
        assert res.graine == 5
        with pytest.raises(dataclasses.FrozenInstanceError):
            res.n_tirages = 1  # type: ignore[misc]


# --- Travail restant : le lead time tire est un cycle COMPLET ---------------------


class TestTravailRestant:
    """C_i = S_i + L_i·(1 − p_i) : seul le travail restant est devant nous.

    Même correction que ``UrModel.u_base_jalon`` et ``ForecastService`` — les
    trois estimateurs de P(jalon raté) doivent rester d'accord. Régression du
    défaut mesuré sur la campagne HÉLIOS (99,6 % annoncé sur un jalon livré à
    l'heure, faute d'avoir tenu compte de l'avancement).
    """

    T0_TS = 1_000_000.0

    def _jalons(self, progress: float, deadline_h: float = 200.0) -> dict:
        return {
            "n": [
                Milestone(
                    id="m",
                    node_id="n",
                    name="Serie",
                    start_ts=self.T0_TS,
                    deadline_ts=self.T0_TS + deadline_h * 3600.0,
                    status=MilestoneStatus.ACTIVE,
                    progress=progress,
                )
            ]
        }

    def _u_time(self, progress: float) -> float:
        repo = _repo_isole(lead=100.0, std=20.0, deadline=None)
        sim = SimulateurLeadTime(repo, n_tirages=10_000, graine=8, famille="normale")
        res = sim.executer(
            t=100.0, milestones_par_noeud=self._jalons(progress), t0_ts=self.T0_TS
        )
        return res.u_time["n"]

    def test_progress_zero_inchange(self):
        # Marge = 200 - 100 = 100 = mu -> p = 0.5. La correction est un
        # SUR-ENSEMBLE : a progress = 0 le comportement anterieur est conserve.
        assert abs(self._u_time(0.0) - 0.5) <= 0.015

    def test_avancement_reduit_le_risque(self):
        # A 50 % : L_restant ~ N(50, 10) contre 100 h de marge -> z = 5, p ~ 0.
        assert self._u_time(0.5) < 0.01

    def test_decroissant_en_progress(self):
        valeurs = [self._u_time(p) for p in (0.0, 0.25, 0.5, 0.75, 1.0)]
        assert valeurs == sorted(valeurs, reverse=True)

    def test_jalon_termine_aucun_retard(self):
        # progress = 1 : C = S exactement, la marge suffit toujours.
        assert self._u_time(1.0) == 0.0

    def test_validation_croisee_mc_erf_avec_avancement(self):
        """MC == survie analytique de L·(1 − p), l'invariant documente du module."""
        reste = 0.4
        repo = _repo_isole(lead=100.0, std=20.0, deadline=None)
        sim = SimulateurLeadTime(repo, n_tirages=20_000, graine=11, famille="normale")
        p_mc = sim.executer(
            t=100.0, milestones_par_noeud=self._jalons(1.0 - reste), t0_ts=self.T0_TS
        ).u_time["n"]
        # P(L·reste > 100) = P(L > 250) pour L ~ N(100, 20) tronquee a 0.
        p_erf = 0.5 * math.erfc((250.0 - 100.0) / (20.0 * math.sqrt(2.0)))
        assert abs(p_mc - p_erf) <= 0.01

    def test_reste_sans_jalon_actif_vaut_un(self):
        assert SimulateurLeadTime._reste(None) == 1.0
        assert SimulateurLeadTime._reste([]) == 1.0
        jalons = self._jalons(0.3)["n"]
        assert SimulateurLeadTime._reste(jalons) == pytest.approx(0.7)
