"""Tests de u_time v2 — échéance multi-jalons et modulation par l'avancement."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.core.ur_model import UrModel
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import KPIBundle, TimeKPIs

T0 = 1_700_000_000.0  # origine epoch arbitraire du projet
H = 3600.0  # secondes par heure

#: 1 − Φ(1) et Φ(1) : ancres des cas chiffrés (cf. TestCasChiffres).
U_BASE_REF = 0.158655
PHI1 = 0.841345


def make_milestone(
    deadline_h: float,
    start_h: float = 0.0,
    status: MilestoneStatus = MilestoneStatus.ACTIVE,
    progress: float = 0.0,
    mid: str = "m1",
) -> Milestone:
    """Jalon de test ancré sur T0, échéances exprimées en heures."""
    return Milestone(
        id=mid,
        node_id="n1",
        name=f"Jalon {mid}",
        start_ts=T0 + start_h * H,
        deadline_ts=T0 + deadline_h * H,
        status=status,
        progress=progress,
    )


@pytest.fixture
def model() -> UrModel:
    return UrModel()  # kappa_retard=0.5, kappa_avance=0.2 par défaut


@pytest.fixture
def kpis() -> KPIBundle:
    """KPIs sans deadline_h : l'échéance vient du jalon."""
    return KPIBundle(time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0))


class TestCasChiffres:
    """Cas chiffrés exacts : d*=100 h, s*=0, L ~ N(100, 20), t=40.

    Marge = 60 h, p_th = 0.4. Le socle porte sur le travail RESTANT :
    L_restant ~ N(100·(1−p), 20·(1−p)), donc z = (60 − 100·(1−p)) / (20·(1−p)).
    """

    def test_progress_egal_p_th_socle_pur(self, model, kpis):
        # progress = 0.4 == p_th -> r = 0 -> u_time = u_base.
        # reste = 0.6 -> mu' = 60 = marge -> z = 0 -> u_base = 0.5 EXACTEMENT
        # (indépendant de sigma) : « il reste juste le temps qu'il faut ».
        m = make_milestone(100.0, progress=0.4)
        u = model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)
        assert u == pytest.approx(0.5, abs=1e-9)

    def test_progress_en_retard_penalite(self, model, kpis):
        # progress = 0.25 -> reste = 0.75 -> mu' = 75, sigma' = 15 -> z = -1
        # -> u_base = Phi(1) = 0.841345 ; r = 0.15 -> u = 0.841345 + 0.075.
        m = make_milestone(100.0, progress=0.25)
        u = model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)
        assert u == pytest.approx(PHI1 + 0.075, abs=1e-4)

    def test_progress_en_avance_bonus(self, model, kpis):
        # progress = 0.5 -> reste = 0.5 -> mu' = 50, sigma' = 10 -> z = +1
        # -> u_base = 1 - Phi(1) = 0.158655 ; r = -0.1 -> u = 0.158655 - 0.02.
        m = make_milestone(100.0, progress=0.5)
        u = model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)
        assert u == pytest.approx(U_BASE_REF - 0.02, abs=1e-4)

    def test_avance_nette_urgence_nulle(self, model, kpis):
        # progress = 0.9 : il reste 10 % du cycle pour 60 % du temps -> le
        # socle est nul et le bonus d'avance clippe a 0. Consequence VOULUE
        # du socle sur travail restant : un jalon tres avance n'est pas urgent.
        m = make_milestone(100.0, progress=0.9)
        assert model.u_time(40.0, kpis, milestones=[m], t0_ts=T0) == 0.0

    def test_apres_deadline_jalon_retard_avere(self, model, kpis):
        # t = 120 > d* = 100 -> 1.0 exactement.
        m = make_milestone(100.0, progress=0.9)
        assert model.u_time(120.0, kpis, milestones=[m], t0_ts=T0) == 1.0

    def test_kappas_personnalises(self, kpis):
        # r = 0.15 avec kappa_retard = 1.0 -> Phi(1) + 0.15.
        model = UrModel(kappa_retard=1.0, kappa_avance=0.0)
        m = make_milestone(100.0, progress=0.25)
        u = model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)
        assert u == pytest.approx(PHI1 + 0.15, abs=1e-4)

    def test_sans_lead_time_modulation_seule(self, model):
        # Choix documenté : lead_time None + jalon actif -> u_base = 0.0,
        # la modulation planning s'applique quand même.
        k = KPIBundle(time=TimeKPIs())
        m = make_milestone(100.0, progress=0.0)
        u = model.u_time(40.0, k, milestones=[m], t0_ts=T0)
        # p_th = 0.4, r = 0.4 -> u = 0 + 0.5*0.4 = 0.2.
        assert u == pytest.approx(0.2, abs=1e-9)


class TestSelectionJalon:
    """M* = prochain jalon ACTIVE de deadline minimale."""

    def test_jalon_done_ignore(self, model, kpis):
        # Jalon 1 DONE (50 h) + jalon 2 ACTIVE (200 h) -> calcul sur 200 h.
        done = make_milestone(50.0, status=MilestoneStatus.DONE, progress=1.0, mid="j1")
        actif = make_milestone(200.0, progress=0.2, mid="j2")
        u_avec_done = model.u_time(40.0, kpis, milestones=[done, actif], t0_ts=T0)
        u_actif_seul = model.u_time(40.0, kpis, milestones=[actif], t0_ts=T0)
        assert u_avec_done == pytest.approx(u_actif_seul, abs=1e-12)
        # Calculé sur d* = 200 (p_th = 0.2 = progress -> socle pur) : il reste
        # 80 % de 100 h de cycle pour 160 h de marge -> z = 5, u_base ~ 0.
        # Sur d* = 50 on aurait u ~ 1.
        assert u_avec_done == pytest.approx(0.0, abs=1e-6)

    def test_deux_actifs_deadline_minimale(self, model, kpis):
        proche = make_milestone(100.0, progress=0.4, mid="proche")
        lointain = make_milestone(500.0, progress=0.0, mid="lointain")
        u = model.u_time(40.0, kpis, milestones=[lointain, proche], t0_ts=T0)
        assert u == pytest.approx(0.5, abs=1e-9)


class TestRetroCompatibiliteV1:
    """Sans jalon actif, u_time v2 == u_time v1 (numériquement)."""

    @pytest.fixture
    def kpis_v1(self) -> KPIBundle:
        return KPIBundle(time=TimeKPIs(deadline_h=100.0, lead_time_h=50.0, lead_time_std_h=10.0))

    def test_milestones_none_et_vide(self, model, kpis_v1):
        for t in (0.0, 40.0, 90.0, 120.0):
            u_v1 = model.u_time(t, kpis_v1)
            assert model.u_time(t, kpis_v1, milestones=None) == u_v1
            assert model.u_time(t, kpis_v1, milestones=[]) == u_v1
        assert model.u_time(40.0, kpis_v1) == pytest.approx(U_BASE_REF, abs=1e-3)

    def test_jalons_tous_inactifs_v1(self, model, kpis_v1):
        # DONE + ABANDONED uniquement -> aucun M* -> bascule v1.
        jalons = [
            make_milestone(10.0, status=MilestoneStatus.DONE, mid="d"),
            make_milestone(20.0, status=MilestoneStatus.ABANDONED, mid="x"),
        ]
        u = model.u_time(40.0, kpis_v1, milestones=jalons, t0_ts=T0)
        assert u == model.u_time(40.0, kpis_v1)

    def test_kpis_incomplets_none_conserve(self, model):
        # v1 : sans deadline_h ou sans lead_time_h -> None, inchangé.
        assert model.u_time(0.0, KPIBundle(), milestones=None) is None
        k = KPIBundle(time=TimeKPIs(lead_time_h=5.0))
        assert model.u_time(0.0, k, milestones=[]) is None

    def test_blocks_et_ur_local_propagent_les_jalons(self, model, kpis):
        m = make_milestone(100.0, progress=0.1)
        u_attendu = model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)
        blocs = model.blocks(40.0, kpis, milestones=[m], t0_ts=T0)
        assert blocs["time"] == pytest.approx(u_attendu, abs=1e-12)
        # Seul le bloc time est non-None -> ur_local == u_time.
        ur = model.ur_local(40.0, kpis, milestones=[m], t0_ts=T0)
        assert ur == pytest.approx(u_attendu, abs=1e-12)


class TestProprietes:
    """Propriétés Hypothesis : bornes et monotonie en progress."""

    @given(
        progress=st.floats(0.0, 1.0),
        t=st.floats(0.0, 100.0),
        lead=st.floats(0.1, 500.0),
        std=st.floats(0.1, 100.0),
    )
    def test_borne_01_avant_deadline(self, progress, t, lead, std):
        model = UrModel()
        m = make_milestone(100.0, progress=progress)
        k = KPIBundle(time=TimeKPIs(lead_time_h=lead, lead_time_std_h=std))
        u = model.u_time(t, k, milestones=[m], t0_ts=T0)
        assert u is not None
        assert 0.0 <= u <= 1.0

    @given(
        p1=st.floats(0.0, 1.0),
        p2=st.floats(0.0, 1.0),
        t=st.floats(0.0, 100.0),
        lead=st.floats(0.1, 500.0),
    )
    def test_decroissante_en_progress(self, p1, p2, t, lead):
        # progress2 > progress1 => u_time2 <= u_time1 (à t fixé).
        if p2 < p1:
            p1, p2 = p2, p1
        model = UrModel()
        k = KPIBundle(time=TimeKPIs(lead_time_h=lead, lead_time_std_h=10.0))
        u1 = model.u_time(t, k, milestones=[make_milestone(100.0, progress=p1)], t0_ts=T0)
        u2 = model.u_time(t, k, milestones=[make_milestone(100.0, progress=p2)], t0_ts=T0)
        assert u1 is not None and u2 is not None
        assert u2 <= u1 + 1e-12


class TestSocleTravailRestant:
    """Le socle porte sur le travail RESTANT, pas sur un cycle complet.

    Régression du défaut mesuré sur la campagne HÉLIOS : un nœud dont le lead
    time nominal dépassait la marge voyait P(jalon raté) saturer à ~100 %
    quel que soit son avancement — 99,6 % annoncé sur un jalon livré à l'heure.
    """

    def test_progress_zero_identique_au_socle_complet(self, model):
        # A progress = 0, le travail restant EST le cycle complet : la
        # formule est un sur-ensemble de l'ancienne, pas un remplacement.
        tk = TimeKPIs(lead_time_h=50.0, lead_time_std_h=10.0)
        for slack in (0.0, 30.0, 60.0, 500.0):
            assert model.u_base_jalon(slack, tk, 0.0) == pytest.approx(
                model._p_late(slack, 50.0, 10.0), abs=1e-12
            )

    def test_progress_zero_identique_sans_std(self, model):
        # Meme sur-ensemble quand sigma est absent (chemin sigma relatif 0.25 mu).
        tk = TimeKPIs(lead_time_h=50.0)
        for slack in (0.0, 30.0, 60.0, 500.0):
            assert model.u_base_jalon(slack, tk, 0.0) == pytest.approx(
                model._p_late(slack, 50.0, None), abs=1e-12
            )

    def test_desaturation_lead_time_long(self, model):
        # Cas CompoDis : cycle nominal 18,9 semaines, marge 1 semaine.
        # Avant : socle constant a ~1 quel que soit progress. Apres : il decroit.
        tk = TimeKPIs(lead_time_h=3175.0)  # 18,9 semaines
        socles = [model.u_base_jalon(168.0, tk, p) for p in (0.0, 0.5, 0.9, 0.99)]
        assert socles == sorted(socles, reverse=True)
        assert socles[0] > 0.99  # non avance : le retard reste quasi certain
        assert socles[-1] < 0.5  # quasi fini : le socle a lache la saturation

    def test_jalon_termine_socle_nul(self, model):
        # progress = 1 : plus rien a faire -> aucune probabilite de retard,
        # meme avec un lead time nominal enorme et une marge nulle.
        for tk in (TimeKPIs(lead_time_h=1e6, lead_time_std_h=1e5), TimeKPIs(lead_time_h=1e6)):
            assert model.u_base_jalon(0.0, tk, 1.0) == 0.0

    def test_sans_lead_time_socle_nul(self, model):
        assert model.u_base_jalon(60.0, TimeKPIs(), 0.5) == 0.0

    @given(
        p1=st.floats(0.0, 1.0),
        p2=st.floats(0.0, 1.0),
        slack=st.floats(0.0, 1000.0),
        lead=st.floats(0.1, 5000.0),
    )
    def test_socle_decroissant_en_progress(self, p1, p2, slack, lead):
        if p2 < p1:
            p1, p2 = p2, p1
        model = UrModel()
        tk = TimeKPIs(lead_time_h=lead, lead_time_std_h=lead * 0.25)
        assert model.u_base_jalon(slack, tk, p2) <= model.u_base_jalon(slack, tk, p1) + 1e-12


class TestValidationKappas:
    def test_kappa_retard_negatif_rejete(self):
        with pytest.raises(ValueError):
            UrModel(kappa_retard=-0.1)

    def test_kappa_avance_negatif_rejete(self):
        with pytest.raises(ValueError):
            UrModel(kappa_avance=-0.1)
