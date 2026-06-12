"""Scénario de démo « Programme AERIS » — données réalistes pour présentation.

Construit un projet nommé (10 nœuds sur 4 rangs, arcs croisés + arc de secours),
puis SIMULE 8 SEMAINES de serious game (revues hebdo complètes, événements
calibrés, décisions tracées) pour que le dashboard, le rapport de session et la
calibration aient du contenu. Données SIMULÉES, pour la démonstration uniquement.

La dramaturgie scriptée :
- S2  : non-conformité qualité chez Ferralu Forge (rebuts fonderie) ;
- S3  : retard fournisseur 120 h chez PowerChip — dont le joueur SOUS-DÉCLARE
        l'urgence pendant 3 semaines -> risque caché H visible au dashboard ;
- S4  : grève chez Mines & Alliages Atlas -> le choc remonte la branche fonderie ;
- S5  : jalon « Qualification » terminé chez Composites Atlantique ; hausse
        énergie chez CellTech ;
- S6  : perte de capacité 25 % chez PowerChip (la crise sous-déclarée s'aggrave),
        décision : activation du fournisseur de secours AccuPol ;
- S7-8: la chaîne se stabilise… mais le client final panique À RETARDEMENT
        (Ud 0.85 quand Ur redescend) -> fausse urgence F en fin de partie.

Usage :
    .venv\\Scripts\\python.exe scripts\\demo_scenario.py [--db-dir DIR] [--reset]
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import uuid
from pathlib import Path

from supplyscore.data.generator import RandomSupplyChainGenerator
from supplyscore.domain.milestones import Milestone
from supplyscore.domain.models import (
    ArcKind,
    CO2KPIs,
    CostKPIs,
    InventoryKPIs,
    KPIBundle,
    NetworkKPIs,
    OEEKPIs,
    Project,
    RiskKPIs,
    SupplyArc,
    SupplyNode,
    TimeKPIs,
)
from supplyscore.domain.specsheet import (
    CahierDesCharges,
    Deliverable,
    PenaltyClause,
    QualityRequirements,
    cdc_to_json,
)
from supplyscore.domain.tags import Tag, TagCategory
from supplyscore.services import SupplyScoreService
from supplyscore.services.decisions import DecisionService
from supplyscore.services.events import EventEngine
from supplyscore.services.exports import ExportService
from supplyscore.services.report import SessionReport
from supplyscore.services.weekly import WeeklyReview

WEEK = 604_800.0
PROJECT_ID = "prog-aeris"
ANIMATEUR = "John (animateur)"

#: (id, nom, label, rang, ville, lat, lon, produit, lead_h, std_h, dispo, p_def)
NOEUDS = [
    ("aeris-oem", "Aeris Industries — Assemblage final", "Client", 0,
     "Toulouse", 43.60, 1.44, "Drone cargo AER-200", 48.0, 8.0, 0.97, 0.010),
    ("mecanika", "Mecanika SAS — Nacelles & structures", "Factory", 1,
     "Lyon", 45.76, 4.84, "Nacelle équipée", 120.0, 20.0, 0.93, 0.025),
    ("voltech", "Voltech GmbH — Propulsion électrique", "Factory", 1,
     "Hambourg", 53.55, 9.99, "Module propulsion", 160.0, 30.0, 0.91, 0.030),
    ("composites-atl", "Composites Atlantique", "Workshop", 2,
     "Nantes", 47.22, -1.55, "Panneaux carbone", 200.0, 35.0, 0.90, 0.030),
    ("ferralu", "Ferralu Forge", "Supplier", 2,
     "Gdansk", 54.35, 18.65, "Carters forgés", 240.0, 45.0, 0.88, 0.045),
    ("celltech", "CellTech Batteries", "Factory", 2,
     "Dresde", 51.05, 13.74, "Pack batterie 800V", 220.0, 40.0, 0.90, 0.035),
    ("powerchip", "PowerChip Semiconducteurs", "Supplier", 2,
     "Hsinchu", 24.80, 120.97, "Contrôleurs de puissance", 320.0, 60.0, 0.92, 0.040),
    ("accupol", "AccuPol — Cellules de secours", "Supplier", 2,
     "Poznan", 52.41, 16.93, "Cellules LFP (backup)", 260.0, 50.0, 0.93, 0.030),
    ("minalliages", "Mines & Alliages Atlas", "Supplier", 3,
     "Casablanca", 33.57, -7.59, "Alliages aluminium", 300.0, 55.0, 0.87, 0.050),
    ("lithium-andes", "Lithium Andes", "Supplier", 3,
     "Antofagasta", -23.65, -70.40, "Carbonate de lithium", 400.0, 80.0, 0.89, 0.045),
]

#: (source, target, gamma, beta, label) — orientation fournisseur -> client.
ARCS = [
    ("mecanika", "aeris-oem", 0.75, 0.70, "Truck"),
    ("voltech", "aeris-oem", 0.70, 0.65, "Truck"),
    ("composites-atl", "mecanika", 0.60, 0.60, "Truck"),
    ("ferralu", "mecanika", 0.55, 0.60, "Train"),
    ("celltech", "voltech", 0.60, 0.65, "Train"),
    ("powerchip", "voltech", 0.45, 0.70, "Ship"),
    ("powerchip", "mecanika", 0.30, 0.50, "Ship"),  # arc croisé : actionneurs nacelle
    ("minalliages", "ferralu", 0.45, 0.55, "Ship"),
    ("lithium-andes", "celltech", 0.45, 0.60, "Ship"),
]

#: Trajectoires d'urgence DÉCLARÉE (bias AHP par semaine 1..8) — la dramaturgie.
BIAS = {
    "aeris-oem":      [0.35, 0.35, 0.40, 0.40, 0.45, 0.60, 0.85, 0.90],  # panique tardive -> F
    "mecanika":       [0.40, 0.42, 0.50, 0.55, 0.55, 0.50, 0.45, 0.40],
    "voltech":        [0.40, 0.42, 0.55, 0.60, 0.62, 0.65, 0.55, 0.45],
    "composites-atl": [0.35, 0.35, 0.38, 0.40, 0.35, 0.30, 0.30, 0.28],
    "ferralu":        [0.40, 0.55, 0.60, 0.65, 0.60, 0.50, 0.45, 0.40],
    "celltech":       [0.38, 0.40, 0.42, 0.45, 0.55, 0.50, 0.45, 0.40],
    "powerchip":      [0.30, 0.28, 0.28, 0.30, 0.32, 0.35, 0.40, 0.42],  # sous-déclare -> H
    "accupol":        [0.25, 0.25, 0.25, 0.28, 0.30, 0.40, 0.45, 0.40],
    "minalliages":    [0.40, 0.42, 0.45, 0.65, 0.60, 0.50, 0.45, 0.40],
    "lithium-andes":  [0.42, 0.45, 0.45, 0.45, 0.45, 0.45, 0.45, 0.42],
}

JOUEURS = {
    "aeris-oem": "Sarah", "mecanika": "Marc", "voltech": "Greta",
    "composites-atl": "Nadia", "ferralu": "Piotr", "celltech": "Jonas",
    "powerchip": "Mei", "accupol": "Ola", "minalliages": "Yassine",
    "lithium-andes": "Carla",
}

#: semaine -> liste de (noeud, type d'événement, params, décision tracée)
EVENEMENTS = {
    2: [("ferralu", "non_conformite_qualite", {"taux_rebut_obs": 0.08},
         "Plan de surveillance qualité renforcé sur la fonderie (audit sous 2 semaines).")],
    3: [("powerchip", "retard_fournisseur", {"retard_h": 120.0},
         "Demande d'un point hebdomadaire dédié avec PowerChip ; étude de double sourcing lancée.")],
    4: [("minalliages", "greve", {"duree_prevue_h": 96.0, "part_effectif": 0.6},
         "Constitution d'un stock tampon d'alliages (3 semaines) chez Ferralu.")],
    5: [("celltech", "hausse_energie", {"pct": 18.0},
         "Renégociation du contrat énergie CellTech ; indexation plafonnée.")],
    6: [("powerchip", "perte_capacite", {"pct_volume_perdu": 0.25},
         "ACTIVATION DU PLAN DE SECOURS : qualification AccuPol accélérée, "
         "30 % du volume contrôleurs re-routé.")],
    7: [("lithium-andes", "perturbation_transport", {"retard_h": 48.0, "surcout": 15_000.0},
         "Bascule ponctuelle sur fret maritime express ; surcoût accepté.")],
}

#: Dérives KPI hebdomadaires discrètes (saisies volet 2) : semaine -> [(noeud, chemin, valeur)]
DERIVES_KPI = {
    2: [("ferralu", "oee.quality", 0.86)],
    3: [("powerchip", "time.delay_h", 96.0), ("voltech", "time.delay_h", 24.0)],
    4: [("minalliages", "oee.availability", 0.74)],
    5: [("celltech", "cost.op_cost", 21_000.0)],
    6: [("powerchip", "oee.availability", 0.78)],
    7: [("powerchip", "time.delay_h", 48.0), ("minalliages", "oee.availability", 0.85)],
    8: [("powerchip", "time.delay_h", 12.0), ("ferralu", "oee.quality", 0.93)],
}

#: Écart d'avancement DÉCLARÉ vs théorique au volet jalons — PowerChip traîne
#: (u_time v2 pénalise le retard constaté avec κ_retard = 0.5) puis rattrape.
def _retard_declare(nid: str, semaine: int) -> float:
    if nid == "powerchip":
        return -0.35 if semaine <= 6 else (-0.25 if semaine == 7 else -0.20)
    return {"ferralu": -0.06}.get(nid, 0.02)


def _kpis(produit: str, lead_h: float, std_h: float, dispo: float, p_def: float,
          distance_km: float, demande: float) -> KPIBundle:
    """KPIs complets et plausibles, tous blocs renseignés (PERT inclus pour Monte Carlo)."""
    op = 18_000.0 + demande * 40.0
    co2 = 2_200.0 + distance_km * 0.8
    return KPIBundle(
        network=NetworkKPIs(product=produit, distance_km=distance_km, demand=demande),
        inventory=InventoryKPIs(
            max_volume_m3=8_000.0, max_weight_kg=60_000.0,
            current_volume_m3=3_200.0, current_weight_kg=24_000.0,
            flow_rate=demande * 1.05,
        ),
        time=TimeKPIs(
            speed_kmh=70.0, distance_range_km=distance_km * 1.2,
            time_range_h=lead_h * 1.3, refuel_time_h=1.5,
            lead_time_h=lead_h, lead_time_std_h=std_h,
            lead_time_min_h=lead_h * 0.8, lead_time_mode_h=lead_h,
            lead_time_max_h=lead_h * 1.6,
            delay_h=0.0, deadline_h=lead_h * 1.8,
        ),
        cost=CostKPIs(
            product_cost=850.0, tariff=1.08, nominal_op_cost=op, op_cost=op * 1.05,
            fuel_cost=1_800.0, risk_cost=op * 0.04, storage_cost=900.0,
        ),
        co2=CO2KPIs(
            fuel_emission_g_km=420.0, op_emission_g_h=co2 * 0.7, energy_mix_g_h=co2 * 0.3,
            co2_target_g_h=co2 * 0.8, co2_max_g_h=co2 * 1.4,
        ),
        oee=OEEKPIs(
            production_time_h=140.0 * dispo, operating_time_h=140.0,
            availability=dispo, performance=0.90, quality=0.96,
        ),
        risk=RiskKPIs(
            failure_probability=p_def, recovery_time_h=72.0, severity=0.45,
            cost_volatility=0.12, env_exposure=0.10, political_risk=0.08,
        ),
    )


def construire(svc: SupplyScoreService) -> Project:
    """Projet AERIS : nœuds, arcs (+ backup), tags, jalons, CdC, AHP initiaux, FBWM."""
    t0 = svc.clock.now()
    projet = Project(
        id=PROJECT_ID,
        name="Programme AERIS — drone cargo AER-200",
        owner_node_id="aeris-oem",
        description=(
            "Montée en cadence du drone cargo AER-200 : 10 acteurs sur 4 rangs, "
            "de l'assemblage final Toulouse aux matières premières (Maroc, Chili). "
            "Données SIMULÉES pour la démonstration."
        ),
        t0_ts=t0,
    )

    # Taxonomie de tags.
    cat_procede = TagCategory(id=str(uuid.uuid4()), project_id=PROJECT_ID,
                              name="Procédé", color="#2c5f7c")
    cat_region = TagCategory(id=str(uuid.uuid4()), project_id=PROJECT_ID,
                             name="Région", color="#b06000")
    noms_tags = {
        "Assemblage": cat_procede, "Fonderie": cat_procede, "Électronique": cat_procede,
        "Composites": cat_procede, "Matières premières": cat_procede,
        "Europe": cat_region, "Asie": cat_region, "Afrique": cat_region,
        "Amérique du Sud": cat_region,
    }
    tags = {nom: Tag(id=str(uuid.uuid4()), project_id=PROJECT_ID, name=nom,
                     category_id=cat.id) for nom, cat in noms_tags.items()}
    tags_par_noeud = {
        "aeris-oem": ["Assemblage", "Europe"], "mecanika": ["Assemblage", "Europe"],
        "voltech": ["Électronique", "Europe"], "composites-atl": ["Composites", "Europe"],
        "ferralu": ["Fonderie", "Europe"], "celltech": ["Électronique", "Europe"],
        "powerchip": ["Électronique", "Asie"], "accupol": ["Électronique", "Europe"],
        "minalliages": ["Matières premières", "Afrique"],
        "lithium-andes": ["Matières premières", "Amérique du Sud"],
    }

    distances = {0: 30.0, 1: 600.0, 2: 1_200.0, 3: 9_000.0}
    demandes = {0: 12.0, 1: 30.0, 2: 80.0, 3: 200.0}
    noeuds = [
        SupplyNode(
            id=nid, name=nom, label=label, rank=rang, project_id=PROJECT_ID,
            location=ville, latitude=lat, longitude=lon,
            kpis=_kpis(produit, lead, std, dispo, p_def, distances[rang], demandes[rang]),
            tags=[tags[t].id for t in tags_par_noeud[nid]],
        )
        for nid, nom, label, rang, ville, lat, lon, produit, lead, std, dispo, p_def in NOEUDS
    ]
    arcs = [
        SupplyArc(src, dst, label=label, gamma=g, beta=b, delta=1.0)
        for src, dst, g, b, label in ARCS
    ]
    arcs.append(SupplyArc("accupol", "voltech", label="Backup", gamma=0.0, beta=0.0,
                          kind_arc=ArcKind.BACKUP))

    svc.registry.save_project(projet)
    for cat in (cat_procede, cat_region):
        svc.registry.save_tag_category(cat)
    for tag in tags.values():
        svc.registry.save_tag(tag)
    svc.create_project(projet, noeuds, arcs)

    # Jalons : Proto -> Qualification -> Livraison série, décalés par rang.
    for nid, _, _, rang, *_ in NOEUDS:
        depart = t0
        for position, (nom_jalon, kind, duree_sem) in enumerate([
            ("Proto", "proto", 6 + rang),
            ("Qualification", "custom", 6),
            ("Livraison série 1", "livraison", 8),
        ]):
            deadline = depart + duree_sem * WEEK
            svc.registry.save_milestone(Milestone(
                id=f"{nid}-j{position}", node_id=nid, name=nom_jalon, kind=kind,
                start_ts=depart, deadline_ts=deadline, position=position,
            ))
            depart = deadline

    # Cahiers des charges des acteurs clés.
    cdcs = {
        "aeris-oem": CahierDesCharges(
            deliverables=[Deliverable("Drone cargo AER-200", 24, "appareils")],
            budget_total=18_500_000.0, target_unit_cost=720_000.0,
            quality=QualityRequirements(standards=["EN 9100", "DO-178C"],
                                        max_scrap_rate=0.02),
            penalties=[PenaltyClause("late_delivery",
                                     "Retard de livraison série", 12_000.0, 600_000.0)],
            notes="Cadence cible : 2 appareils/mois à partir de la série 1.",
        ),
        "mecanika": CahierDesCharges(
            deliverables=[Deliverable("Nacelle équipée", 48, "unités")],
            budget_total=3_200_000.0, target_unit_cost=58_000.0,
            quality=QualityRequirements(standards=["EN 9100"], max_scrap_rate=0.03),
        ),
        "voltech": CahierDesCharges(
            deliverables=[Deliverable("Module propulsion 800V", 96, "unités")],
            budget_total=4_100_000.0, target_unit_cost=39_000.0,
            quality=QualityRequirements(standards=["EN 9100", "CEI 61508"],
                                        max_scrap_rate=0.02),
        ),
        "powerchip": CahierDesCharges(
            deliverables=[Deliverable("Contrôleur de puissance PC-8", 220, "pièces")],
            budget_total=950_000.0, target_unit_cost=3_900.0,
            quality=QualityRequirements(certifications=["AEC-Q100"], max_scrap_rate=0.01),
            penalties=[PenaltyClause("quality", "Lot non conforme AEC-Q100", None, 80_000.0)],
        ),
    }
    for nid, cdc in cdcs.items():
        svc.mutations.save_spec_sheet(nid, cdc_to_json(cdc), source="demo",
                                      operator_id=ANIMATEUR)

    # Évaluations AHP initiales (S0) + pondération FBWM des blocs d'Ur.
    gen = RandomSupplyChainGenerator(seed=2026)
    for nid, traj in BIAS.items():
        svc.submit_assessment(gen.generate_assessment(
            nid, PROJECT_ID, JOUEURS[nid], urgency_bias=max(0.2, traj[0] - 0.05),
            notes="Évaluation initiale (onboarding).",
        ))

    from supplyscore.mcda.fbwm import resoudre_fbwm
    fbwm = resoudre_fbwm(
        criteres=["time", "cap", "perf", "risk", "cost", "co2"],
        best="time", worst="co2",
        best_vers_autres={
            "risk": "faiblement_plus_important",
            "perf": "assez_plus_important",
            "cost": "assez_plus_important",
            "cap": "tres_plus_important",
            "co2": "absolument_plus_important",
        },
        autres_vers_worst={
            "risk": "tres_plus_important",
            "perf": "assez_plus_important",
            "cost": "assez_plus_important",
            "cap": "faiblement_plus_important",
        },
    )
    svc.set_poids_criteres(PROJECT_ID, fbwm.poids, methode="fbwm", xi_star=fbwm.xi_star)
    print(f"FBWM : poids={ {k: round(v, 3) for k, v in fbwm.poids.items()} } "
          f"xi*={fbwm.xi_star:.3f} CR={fbwm.cr:.3f}")
    return projet


def jouer(svc: SupplyScoreService) -> None:
    """8 semaines de serious game : revues hebdo, événements, décisions."""
    events = EventEngine(svc)
    decisions = DecisionService(svc)
    review = WeeklyReview(svc)
    gen = RandomSupplyChainGenerator(seed=777)

    svc.set_clock_mode(PROJECT_ID, "game")
    svc.evaluate_all(persist=True)  # point S0 de l'historique

    for semaine in range(1, 9):
        svc.advance_week(PROJECT_ID)
        derives = {(nid): (chemin, valeur)
                   for nid, chemin, valeur in DERIVES_KPI.get(semaine, [])}

        for nid, traj in BIAS.items():
            joueur = JOUEURS[nid]
            review.start(nid)

            # Volet 1 — AHP de la semaine (trajectoire scriptée).
            svc.submit_assessment(gen.generate_assessment(
                nid, PROJECT_ID, joueur, urgency_bias=traj[semaine - 1]))
            review.mark_volet(nid, "ahp", joueur)

            # Volet 2 — KPIs : dérive scriptée ou « rien n'a changé ».
            if nid in derives:
                chemin, valeur = derives[nid]
                svc.mutations.update_kpis(nid, {chemin: valeur},
                                          source="hebdo", operator_id=joueur)
            else:
                review.confirm_block(nid, "time", joueur)
            review.mark_volet(nid, "kpis", joueur)

            # Volet 3 — jalons : avancement déclaré vs théorique (PowerChip traîne).
            maintenant = svc.clock_for(PROJECT_ID).now()
            jalons = [m for m in svc.registry.list_milestones(nid)
                      if str(m.status) == "active"]
            if jalons:
                jalon = min(jalons, key=lambda m: m.position)
                theorique = (maintenant - jalon.start_ts) / max(
                    jalon.deadline_ts - jalon.start_ts, 1.0)
                declare = max(0.0, min(1.0, theorique + _retard_declare(nid, semaine)))
                if semaine == 5 and nid == "composites-atl":
                    review.confirm_milestone(jalon.id, "done", 1.0, joueur)
                elif declare >= 0.88:
                    review.confirm_milestone(jalon.id, "done", 1.0, joueur)
                else:
                    review.confirm_milestone(jalon.id, "active",
                                             round(declare, 2), joueur)
            review.mark_volet(nid, "jalons", joueur)

            # Volet 4 — événements scriptés de la semaine + érosion bayésienne.
            for ev_nid, ev_type, ev_params, ev_decision in EVENEMENTS.get(semaine, []):
                if ev_nid == nid:
                    events.apply(nid, ev_type, ev_params, operator_id=joueur,
                                 notes=f"Semaine {semaine} — déclaré en revue hebdo.")
                    decisions.record(nid, ev_decision, operator_id=joueur)
            events.apply_weekly_decay(nid, joueur)
            review.mark_volet(nid, "evenements", joueur)
            review.complete(nid)

        etats = svc.evaluate_all(persist=True)
        pire = min(etats, key=lambda k: etats[k].adequation or 100.0)
        print(f"S{semaine} : pire adéquation = {pire} "
              f"(A={etats[pire].adequation:.1f}, Ud={etats[pire].ud:.2f}, "
              f"Ur={etats[pire].ur:.2f})")


def sorties(svc: SupplyScoreService, dest: Path) -> None:
    """Export xlsx + rapport de session HTML + synthèse console."""
    dest.mkdir(parents=True, exist_ok=True)
    xlsx = ExportService(svc).export_project(PROJECT_ID, fmt="xlsx", dest_dir=dest)
    rapport = SessionReport(svc).build(PROJECT_ID, horizon_weeks=4, dest_dir=dest)
    print(f"\nExport xlsx : {xlsx}\nRapport     : {rapport}\n")

    etats = svc.evaluate_all(persist=True)
    print(f"{'Nœud':<18} {'Ud':>5} {'Ur':>5} {'A':>6} {'F':>5} {'H':>5}")
    for nid, *_ in NOEUDS:
        e = etats[nid]
        print(f"{nid:<18} {e.ud:>5.2f} {e.ur:>5.2f} {e.adequation:>6.1f} "
              f"{e.false_urgency:>5.2f} {e.hidden_risk:>5.2f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-dir", default=str(
        Path(os.environ.get("LOCALAPPDATA", "")) / "SupplyScore" / "demo_aeris"))
    parser.add_argument("--reset", action="store_true",
                        help="Vide d'abord le répertoire de bases de la démo.")
    parser.add_argument("--artefacts", default=str(
        Path(__file__).resolve().parents[1] / "docs" / "presentation" / "artefacts"))
    args = parser.parse_args(argv)

    db_dir = Path(args.db_dir)
    if args.reset and db_dir.exists():
        shutil.rmtree(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    if any(db_dir.glob("*.sqlite")):
        print(f"{db_dir} contient déjà des bases — utilisez --reset pour repartir de zéro.")
        return 1

    svc = SupplyScoreService(db_dir=db_dir)
    try:
        construire(svc)
        jouer(svc)
        sorties(svc, Path(args.artefacts))
    finally:
        svc.close()
    print(f"Scénario AERIS prêt dans {db_dir} — lancer l'app avec --db-dir dessus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
