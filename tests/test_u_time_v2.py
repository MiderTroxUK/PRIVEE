"""Tests de u_time v2 - echeance multi-jalons et modulation par l'avancement."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from supplyscore.core.ur_model import UrModel
from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import KPIBundle, TimeKPIs

T0 = 1_700_000_000.0  # origine epoch arbitraire du projet
H = 3600.0  # secondes par heure

#: Socles de reference des cas chiffres (cf. TestCasChiffres). L'ecart-type du travail restant decroit en RACINE de (1 - progress), donc les z ne sont plus entiers : on garde les valeurs exactes plutot que des ancres rondes fausses.
U_BASE_P25 = 0.806762  # p=0.25 : z = (60 - 75) / (20-sqrt0.75) = -0.8660
U_BASE_P50 = 0.239750  # p=0.50 : z = (60 - 50) / (20-sqrt0.50) = +0.7071


def make_milestone(
    deadline_h: float,
    start_h: float = 0.0,
    status: MilestoneStatus = MilestoneStatus.ACTIVE,
    progress: float = 0.0,
    mid: str = "m1",
) -> Milestone:
    """Jalon de test ancre sur T0, echeances exprimees en heures."""
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
    return UrModel()  # kappa_retard=0.5, kappa_avance=0.2 par defaut


@pytest.fixture
def kpis() -> KPIBundle:
    """KPIs sans deadline_h : l'echeance vient du jalon."""
    return KPIBundle(time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0))


class TestCasChiffres:
    """Cas chiffres exacts : d*=100 h, s*=0, L ~ N(100, 20), t=40.

    Marge = 60 h, p_th = 0.4. Le socle porte sur le travail RESTANT, dont la
    moyenne decroit lineairement et l'ecart-type en RACINE :
    L_restant ~ N(100-(1-p), 20-sqrt(1-p)), donc z = (60 - 100-(1-p)) / (20-sqrt(1-p)).
    """

    def test_progress_egal_p_th_socle_pur(self, model, kpis):
        # progress = 0.4 == p_th -> r = 0 -> u_time = u_base. reste = 0.6 -> mu' = 60 = marge -> z = 0 -> u_base = 0.5 EXACTEMENT (independant de sigma, donc INVARIANT au changement d'echelle de sigma) : " il reste juste le temps qu'il faut ".
        m = make_milestone(100.0, progress=0.4)
        u = model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)
        assert u == pytest.approx(0.5, abs=1e-9)

    def test_progress_en_retard_penalite(self, model, kpis):
        # progress = 0.25 -> reste = 0.75 -> mu' = 75, sigma' = 20-sqrt0.75 = 17.32 z = -0.866 -> u_base = 0.806762 ; r = 0.15 -> u = u_base + 0.075.
        m = make_milestone(100.0, progress=0.25)
        u = model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)
        assert u == pytest.approx(U_BASE_P25 + 0.075, abs=1e-4)

    def test_progress_en_avance_bonus(self, model, kpis):
        # progress = 0.5 -> reste = 0.5 -> mu' = 50, sigma' = 20-sqrt0.5 = 14.14 z = +0.707 -> u_base = 0.239750 ; r = -0.1 -> u = u_base - 0.02.
        m = make_milestone(100.0, progress=0.5)
        u = model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)
        assert u == pytest.approx(U_BASE_P50 - 0.02, abs=1e-4)

    def test_avance_nette_urgence_nulle(self, model, kpis):
        # progress = 0.9 : il reste 10 % du cycle pour 60 % du temps -> le socle est nul et le bonus d'avance clippe a 0. Consequence VOULUE du socle sur travail restant : un jalon tres avance n'est pas urgent.
        m = make_milestone(100.0, progress=0.9)
        assert model.u_time(40.0, kpis, milestones=[m], t0_ts=T0) == 0.0

    def test_apres_deadline_jalon_retard_avere(self, model, kpis):
        # t = 120 > d* = 100 -> 1.0 exactement.
        m = make_milestone(100.0, progress=0.9)
        assert model.u_time(120.0, kpis, milestones=[m], t0_ts=T0) == 1.0

    def test_kappas_personnalises(self, kpis):
        # r = 0.15 avec kappa_retard = 1.0 -> u_base(p=0.25) + 0.15.
        model = UrModel(kappa_retard=1.0, kappa_avance=0.0)
        m = make_milestone(100.0, progress=0.25)
        u = model.u_time(40.0, kpis, milestones=[m], t0_ts=T0)
        assert u == pytest.approx(U_BASE_P25 + 0.15, abs=1e-4)

    def test_sans_lead_time_modulation_seule(self, model):
        # Choix documente : lead_time None + jalon actif -> u_base = 0.0, la modulation planning s'applique quand meme.
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
        # Calcule sur d* = 200 (p_th = 0.2 = progress -> socle pur) : il reste 80 % de 100 h de cycle pour 160 h de marge -> z = 4.47, u_base ~ 4e-6. Sur d* = 50 on aurait u ~ 1.
        assert u_avec_done == pytest.approx(0.0, abs=1e-5)

    def test_deux_actifs_deadline_minimale(self, model, kpis):
        proche = make_milestone(100.0, progress=0.4, mid="proche")
        lointain = make_milestone(500.0, progress=0.0, mid="lointain")
        u = model.u_time(40.0, kpis, milestones=[lointain, proche], t0_ts=T0)
        assert u == pytest.approx(0.5, abs=1e-9)


class TestRetroCompatibiliteV1:
    """Sans jalon actif, u_time v2 == u_time v1 (numeriquement)."""

    @pytest.fixture
    def kpis_v1(self) -> KPIBundle:
        return KPIBundle(time=TimeKPIs(deadline_h=100.0, lead_time_h=50.0, lead_time_std_h=10.0))

    def test_milestones_none_et_vide(self, model, kpis_v1):
        for t in (0.0, 40.0, 90.0, 120.0):
            u_v1 = model.u_time(t, kpis_v1)
            assert model.u_time(t, kpis_v1, milestones=None) == u_v1
            assert model.u_time(t, kpis_v1, milestones=[]) == u_v1
        assert model.u_time(40.0, kpis_v1) == pytest.approx(0.158655, abs=1e-3)

    def test_jalons_tous_inactifs_v1(self, model, kpis_v1):
        # DONE + ABANDONED uniquement -> aucun M* -> bascule v1.
        jalons = [
            make_milestone(10.0, status=MilestoneStatus.DONE, mid="d"),
            make_milestone(20.0, status=MilestoneStatus.ABANDONED, mid="x"),
        ]
        u = model.u_time(40.0, kpis_v1, milestones=jalons, t0_ts=T0)
        assert u == model.u_time(40.0, kpis_v1)

    def test_kpis_incomplets_none_conserve(self, model):
        # v1 : sans deadline_h ou sans lead_time_h -> None, inchange.
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
    """Proprietes Hypothesis : bornes et monotonie en progress."""

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
        # progress2 > progress1 => u_time2 <= u_time1 (a t fixe).
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

    Regression du defaut mesure sur la campagne HELIOS : un noeud dont le lead
    time nominal depassait la marge voyait P(jalon rate) saturer a ~100 %
    quel que soit son avancement - 99,6 % annonce sur un jalon livre a l'heure.
    """

    def test_progress_zero_identique_au_socle_complet(self, model):
        # A progress = 0, le travail restant EST le cycle complet : la formule est un sur-ensemble de l'ancienne, pas un remplacement.
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
        # Cas CompoDis : cycle nominal 18,9 semaines, marge 1 semaine. Avant : socle constant a ~1 quel que soit progress. Apres : il decroit.
        tk = TimeKPIs(lead_time_h=3175.0)  # 18,9 semaines
        socles = [model.u_base_jalon(168.0, tk, p) for p in (0.0, 0.5, 0.9, 0.99)]
        assert socles == sorted(socles, reverse=True)
        assert socles[0] > 0.99  # non avance : le retard reste quasi certain
        assert socles[-1] < 0.5  # quasi fini : le socle a lache la saturation

    def test_jalon_termine_socle_nul(self, model):
        # progress = 1 : plus rien a faire -> aucune probabilite de retard, meme avec un lead time nominal enorme et une marge nulle.
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


class TestRetardChocAdditif:
    """Le temps perdu s'AJOUTE, il n'est jamais mis a l'echelle de l'avancement.

    Regression de la SUR-CORRECTION mesuree au premier essai : en routant les
    arrets dans ``time.lead_time_h``, le choc se faisait multiplier par
    ``1 - progress`` et s'evaporait precisement sur les jalons proches de leur
    echeance. NovaFab retombait de 84,6 % a 0,0 % sur un jalon reellement rate,
    apres quatre semaines d'arret.
    """

    def test_retard_nul_identique_au_socle_sans_choc(self, model):
        tk = TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0)
        for progress in (0.0, 0.5, 0.9):
            assert model.u_base_jalon(60.0, tk, progress, 0.0) == pytest.approx(
                model.u_base_jalon(60.0, tk, progress), abs=1e-12
            )

    def test_retard_consomme_la_marge(self, model):
        # marge 60 h, 20 h perdues -> le socle est celui d'une marge de 40 h.
        tk = TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0)
        assert model.u_base_jalon(60.0, tk, 0.4, 20.0) == pytest.approx(
            model.u_base_jalon(40.0, tk, 0.4), abs=1e-12
        )

    def test_choc_survit_a_un_avancement_eleve(self, model):
        # LE test qui aurait attrape la sur-correction : jalon a 95 %, marge d'une semaine, deux semaines de production perdues -> retard certain.
        tk = TimeKPIs(lead_time_h=500.0, lead_time_std_h=125.0)
        sans_choc = model.u_base_jalon(168.0, tk, 0.95, 0.0)
        avec_choc = model.u_base_jalon(168.0, tk, 0.95, 336.0)
        assert sans_choc < 0.05  # sans choc : 5 % de 500 h a faire en 168 h
        assert avec_choc > 0.95  # avec 336 h perdues : la marge est deja mangee

    def test_croissant_en_retard(self, model):
        tk = TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0)
        socles = [model.u_base_jalon(200.0, tk, 0.5, r) for r in (0.0, 50.0, 100.0, 200.0)]
        assert socles == sorted(socles)

    def test_sans_lead_time_le_choc_seul_peut_mettre_en_retard(self, model):
        # Pas de cycle connu : seul le temps perdu peut creer un retard.
        tk = TimeKPIs()
        assert model.u_base_jalon(60.0, tk, 0.5, 20.0) == 0.0
        assert model.u_base_jalon(60.0, tk, 0.5, 100.0) == 1.0

    def test_u_time_lit_delay_h(self, model):
        # Chainage complet : le KPI ecrit par les evenements atteint u_time.
        m = make_milestone(100.0, progress=0.4)
        calme = KPIBundle(time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0))
        choque = KPIBundle(time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0))
        choque.time.delay_h = 40.0
        u_calme = model.u_time(40.0, calme, milestones=[m], t0_ts=T0)
        u_choque = model.u_time(40.0, choque, milestones=[m], t0_ts=T0)
        assert u_calme == pytest.approx(0.5, abs=1e-9)
        assert u_choque > u_calme


class TestRetardEnV1:
    """Le temps perdu atteint AUSSI le chemin v1 (noeud sans jalon actif).

    Regression : le socle v2 lisait ``time.delay_h``, pas le socle v1. Un noeud
    sans jalon ACTIF restait donc totalement aveugle aux chocs de capacite -
    1 000 h de production perdue laissaient u_time a 0.0000 - alors que le
    simulateur MC et la prevision, qui replient tous deux sur ``deadline_h``,
    appliquaient bien le retard. Trois estimateurs censes partager le meme
    modele d'achevement en donnaient deux reponses opposees.
    """

    @staticmethod
    def _kpis(delay: float | None) -> KPIBundle:
        k = KPIBundle(time=TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0, deadline_h=200.0))
        k.time.delay_h = delay
        return k

    def test_sans_jalon_le_retard_consomme_la_marge(self, model):
        # Marge 200 h, cycle N(100, 20) : au repos P(L > 200) = Phi(-5), quasi nul. 100 h perdues ramenent la marge au cycle moyen -> exactement 0.5.
        assert model.u_time(0.0, self._kpis(None), milestones=None) < 1e-5
        assert model.u_time(0.0, self._kpis(100.0), milestones=None) == pytest.approx(0.5, abs=1e-9)
        assert model.u_time(0.0, self._kpis(1000.0), milestones=None) > 0.99

    def test_sans_jalon_croissant_en_retard(self, model):
        valeurs = [
            model.u_time(0.0, self._kpis(d), milestones=None) for d in (0.0, 50.0, 100.0, 200.0)
        ]
        assert valeurs == sorted(valeurs)

    def test_none_et_zero_identiques(self, model):
        assert model.u_time(0.0, self._kpis(None), milestones=None) == model.u_time(
            0.0, self._kpis(0.0), milestones=None
        )


class TestJalonAcheveJamaisEnRetard:
    """Travail acheve => le temps perdu ne peut plus rien repousser.

    Regression du faux positif CERTAIN : a progress = 1, ``reste`` vaut 0 donc
    mu = 0, ``_p_late`` basculait dans sa branche degeneree et renvoyait
    " 1.0 si 0 > marge ", c'est-a-dire retard certain des que le temps perdu
    depassait la marge - sur un jalon dont tout le travail est fait. Le temps
    perdu est deja DANS l'avancement observe : le compter encore le compte deux
    fois.
    """

    def test_progress_1_socle_nul_quel_que_soit_le_retard(self, model):
        tk = TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0)
        for retard in (0.0, 20.0, 60.0, 200.0, 10_000.0):
            assert model.u_base_jalon(50.0, tk, 1.0, retard) == 0.0

    def test_progress_1_sans_lead_time_non_plus(self, model):
        # Le repli " pas de cycle connu " ne doit pas rouvrir la porte.
        assert model.u_base_jalon(50.0, TimeKPIs(), 1.0, 200.0) == 0.0

    def test_avancement_partiel_reste_sensible(self, model):
        # Le garde-fou ne doit PAS desamorcer le choc avant l'achevement.
        tk = TimeKPIs(lead_time_h=100.0, lead_time_std_h=20.0)
        for progress in (0.0, 0.5, 0.9, 0.99):
            assert model.u_base_jalon(50.0, tk, progress, 60.0) > 0.9


class TestValidationKappas:
    def test_kappa_retard_negatif_rejete(self):
        with pytest.raises(ValueError):
            UrModel(kappa_retard=-0.1)

    def test_kappa_avance_negatif_rejete(self):
        with pytest.raises(ValueError):
            UrModel(kappa_avance=-0.1)
