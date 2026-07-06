"""Scénario « Programme HÉLIOS » — crise des semi-conducteurs 2020-2022 rejouée.

Source de vérité UNIQUE de la campagne de validation : réseau, coefficients,
jalons, événements par tour, personas, narration par point de vue, correspondance
tour <-> mois réel, ancrages documentaires.

Ce fichier est INTERNE (facilitateur/doctorante). Les consultants ne voient que
les fiches générées par make_briefings.py, qui ne contiennent jamais les mois
réels, les ancrages, ni les sections d'autres nœuds.

Convention temporelle (compression narrative) :
    1 tour de jeu = 1 semaine moteur (advance_week) = 1 mois réel raconté.
    Les durées réelles sont convergées en heures moteur via REAL_WEEK_ENGINE_H :
    1 semaine réelle ≈ 38.66 h moteur (168 h / 4.345 semaines par mois).
"""

from __future__ import annotations

# --- Compression temporelle -----------------------------------------------------

#: Heures moteur représentant une semaine réelle (1 mois réel = 1 semaine moteur).
REAL_WEEK_ENGINE_H: float = 168.0 / 4.345  # ≈ 38.66 h


def real_weeks_h(weeks: float) -> float:
    """Convertit des semaines réelles en heures moteur (compression 1 mois = 1 tour)."""
    return round(weeks * REAL_WEEK_ENGINE_H, 1)


def real_days_h(days: float) -> float:
    """Convertit des jours réels en heures moteur."""
    return real_weeks_h(days / 7.0)


# --- Identité du programme -------------------------------------------------------

PROJECT_NAME = "Programme HÉLIOS"
PROJECT_DESCRIPTION = (
    "Livraison de 2 satellites d'observation (HÉLIOS-1, HÉLIOS-2) à un opérateur "
    "institutionnel européen. Échéances contractuelles aux tours T8 et T16, "
    "pénalités de retard lourdes."
)

#: Nombre de tours de campagne (hors T0 d'entraînement).
N_TOURS = 18

#: Correspondance tour -> mois réel (INTERNE, jamais montrée aux consultants).
TOUR_TO_MONTH: dict[int, str] = {
    0: "fictif (entraînement)",
    1: "2020-09", 2: "2020-10", 3: "2020-11", 4: "2020-12",
    5: "2021-01", 6: "2021-02", 7: "2021-03", 8: "2021-04",
    9: "2021-05", 10: "2021-06", 11: "2021-07", 12: "2021-08",
    13: "2021-09", 14: "2021-10", 15: "2021-11", 16: "2021-12",
    17: "2022-01", 18: "2022-02",
}

# --- Réseau : 8 nœuds ancrés sur des acteurs réels -------------------------------
# Ancrage réel en commentaire — jamais dans les briefings.

NODES: list[dict] = [
    {
        "id": "orbitalys",
        "name": "Orbitalys",
        "label": "Client",
        "rank": 0,
        "location": "Toulouse, France",
        "consultant": "C1",
        # Ancrage : Thales Alenia Space / Airbus D&S (produit satellite fictif DISCO).
    },
    {
        "id": "aviosys",
        "name": "AvioSys Intégration",
        "label": "Factory",
        "rank": 1,
        "location": "Bordeaux, France",
        "consultant": "C2",
        # Ancrage : Safran Electronics & Defense / Thales avionique.
    },
    {
        "id": "electis",
        "name": "Électis EMS",
        "label": "Factory",
        "rank": 2,
        "location": "Cholet, France",
        "consultant": "C3",
        # Ancrage : Asteelflash / Lacroix Electronics (EMS en mode allocation, 2021).
    },
    {
        "id": "compodis",
        "name": "CompoDis Europe",
        "label": "Warehouse",
        "rank": 3,
        "location": "Rungis, France (hub Rotterdam)",
        "consultant": "C4",
        # Ancrage : Avnet / Arrow / Rutronik (allocation, primes spot, NCNR).
    },
    {
        "id": "transglobal",
        "name": "TransGlobal Fret",
        "label": "Workshop",
        "rank": 3,
        "location": "Le Havre, France",
        "consultant": "C5",
        # Ancrage : Kuehne+Nagel / DHL GF (taux de fret, Suez, congestion côte ouest).
    },
    {
        "id": "novafab",
        "name": "NovaFab Semiconductors",
        "label": "Factory",
        "rank": 4,
        "location": "Taishan (île d'Asie de l'Est) + fab Texas",
        "consultant": "C6",
        # Ancrage composite documenté : TSMC (sécheresse Taïwan, surbooking) +
        # Samsung/NXP/Infineon Austin (gel Texas février 2021).
    },
    {
        "id": "meridian",
        "name": "Meridian Semi",
        "label": "Factory",
        "rank": 4,
        "location": "Dresde, Allemagne",
        "consultant": "C7",
        # Ancrage : GlobalFoundries (carnet plein 2021 — le backup inerte).
    },
    {
        "id": "silpure",
        "name": "SilPure Materials",
        "label": "Factory",
        "rank": 5,
        "location": "Kyūshū, Japon",
        "consultant": "C8",
        # Ancrage : Shin-Etsu / SUMCO (~60 % des wafers ; polysilicium ×3 en 2021).
    },
]

#: Arcs fournisseur -> client. gamma = atténuation Ud (descendante),
#: beta = amplification Ur (montante), kind "backup" = inerte (documentaire).
ARCS: list[dict] = [
    {"source": "aviosys", "target": "orbitalys", "gamma": 0.9, "beta": 0.8, "kind": "nominal"},
    {"source": "electis", "target": "aviosys", "gamma": 0.8, "beta": 0.7, "kind": "nominal"},
    {"source": "compodis", "target": "electis", "gamma": 0.8, "beta": 0.8, "kind": "nominal"},
    {"source": "transglobal", "target": "electis", "gamma": 0.5, "beta": 0.4, "kind": "nominal"},
    {"source": "novafab", "target": "compodis", "gamma": 0.9, "beta": 0.9, "kind": "nominal"},
    {"source": "meridian", "target": "compodis", "gamma": 0.3, "beta": 0.3, "kind": "backup"},
    {"source": "silpure", "target": "novafab", "gamma": 0.7, "beta": 0.6, "kind": "nominal"},
]

# --- KPIs initiaux (T0) par nœud ---------------------------------------------------
# Valeurs u_risk sourcées (voir plan U5bis) : env_exposure et political_risk
# sont des ALÉAS MENSUELS [0, 0.10], obtenus en rebasant les rangs WorldRiskIndex
# 2021 / WGI Political Stability sur cette bande (le modèle les compose par OU
# probabiliste direct : les indices bruts 0.3-0.5 satureraient Ur — constaté au
# dry run). Facteur de rebasage = constante posée, testée en sensibilité (HD3) ;
# failure_probability = p_base par taille d'acteur (sensibilité ±50 % en U10) ;
# recovery_time_h = durées réelles documentées converties en heures moteur.

BASELINE_KPIS: dict[str, dict[str, float]] = {
    "orbitalys": {
        "risk.failure_probability": 0.01,
        "risk.recovery_time_h": real_weeks_h(2),
        "risk.severity": 0.2,
        "risk.env_exposure": 0.02,
        "risk.political_risk": 0.01,
    },
    "aviosys": {
        "time.lead_time_h": real_weeks_h(6),   # cycle d'intégration + qualification
        "time.lead_time_std_h": real_weeks_h(1.5),
        # Couverture de stock modélisée en capacité d'alimentation (flow/demand) :
        # la sémantique volume du modèle mesure la SATURATION d'entrepôt
        # (remaining = max - current), pas la couverture — constaté au dry run.
        "network.demand": 100.0,
        "inventory.flow_rate": 100.0,
        "risk.failure_probability": 0.01,
        "risk.recovery_time_h": real_weeks_h(26),  # requalif composant ≈ 6 mois réels
        "risk.severity": 0.2,
        "risk.env_exposure": 0.02,
        "risk.political_risk": 0.01,
    },
    "electis": {
        "oee.availability": 0.92,
        "oee.performance": 0.90,
        "oee.quality": 0.985,
        "cost.nominal_op_cost": 100.0,
        "cost.op_cost": 100.0,
        "inventory.max_volume_m3": 60.0,
        "inventory.current_volume_m3": 18.0,   # 30 % de remplissage (saturation basse)
        "risk.failure_probability": 0.02,
        "risk.recovery_time_h": real_weeks_h(2),
        "risk.severity": 0.2,
        "risk.env_exposure": 0.02,
        "risk.political_risk": 0.01,
    },
    "compodis": {
        "network.demand": 100.0,          # indice de demande clients (base 100)
        "inventory.flow_rate": 100.0,     # débit servi (base 100)
        "inventory.max_volume_m3": 500.0,
        "inventory.current_volume_m3": 150.0,  # 30 % de remplissage (saturation basse)
        "cost.tariff": 1.0,
        "risk.failure_probability": 0.02,
        "risk.recovery_time_h": real_weeks_h(1),
        "risk.severity": 0.2,
        "risk.env_exposure": 0.02,
        "risk.political_risk": 0.01,
    },
    "transglobal": {
        "time.lead_time_h": real_weeks_h(5),   # transit intercontinental type
        "time.lead_time_std_h": real_weeks_h(1),
        "cost.nominal_op_cost": 100.0,
        "cost.op_cost": 100.0,
        "risk.failure_probability": 0.03,
        "risk.recovery_time_h": real_days_h(3),
        "risk.severity": 0.2,
        "risk.env_exposure": 0.06,   # routes maritimes mondiales
        "risk.political_risk": 0.02,
    },
    "novafab": {
        "network.demand": 100.0,          # indice WSTS normalisé (base 100 = T0)
        "inventory.flow_rate": 100.0,     # capacité servie
        # Cycle de production PROPRE de la fab (stable) — les délais clients
        # (12 -> 25 semaines) sont portés par compodis, qui les subit : un
        # fondeur n'est pas « en retard » sur ses propres jalons parce que
        # ses clients attendent longtemps (constaté au dry run v2).
        "time.lead_time_h": real_weeks_h(10),
        "time.lead_time_std_h": real_weeks_h(1.5),
        "oee.availability": 0.95,
        "oee.performance": 0.95,
        "oee.quality": 0.99,
        "risk.failure_probability": 0.01,
        "risk.recovery_time_h": real_weeks_h(4),  # redémarrage fab ≈ 1 mois (gel Texas)
        "risk.severity": 0.2,
        "risk.env_exposure": 0.08,   # WRI : typhons, sécheresse, séismes (île)
        "risk.political_risk": 0.06,  # WGI inversé, tensions régionales 2021
    },
    "meridian": {
        "network.demand": 100.0,
        "inventory.flow_rate": 100.0,
        "time.lead_time_h": real_weeks_h(10),
        "time.lead_time_std_h": real_weeks_h(2),
        "oee.availability": 0.93,
        "oee.performance": 0.92,
        "risk.failure_probability": 0.01,
        "risk.recovery_time_h": real_weeks_h(3),
        "risk.severity": 0.2,
        "risk.env_exposure": 0.02,
        "risk.political_risk": 0.01,
    },
    "silpure": {
        "cost.nominal_op_cost": 100.0,
        "cost.op_cost": 100.0,
        "inventory.flow_rate": 100.0,
        "network.demand": 100.0,
        "risk.failure_probability": 0.01,
        "risk.recovery_time_h": real_weeks_h(8),
        "risk.severity": 0.2,
        "risk.env_exposure": 0.07,   # Japon : séismes
        "risk.political_risk": 0.015,
    },
}

# --- Jalons (offsets en semaines moteur depuis t0) ---------------------------------
# (node_id, nom, kind, start_week, deadline_week)

#: RÈGLE : chaque nœud garde AU MOINS un jalon ACTIVE jusqu'à la fin de la
#: campagne — le modèle passe automatiquement un nœud DONE (Ur_local = 0)
#: quand tous ses jalons sont terminés (constaté au dry run), et une entreprise
#: réelle a toujours une prochaine livraison.
MILESTONES: list[tuple[str, str, str, int, int]] = [
    ("orbitalys", "Livraison HÉLIOS-1", "livraison", 0, 8),
    ("orbitalys", "Livraison HÉLIOS-2", "livraison", 8, 16),
    # Échéanciers calés pour que les pics mécaniques de fin de fenêtre
    # (P(L > slack) -> 1 quand le lead time approche la fenêtre restante)
    # tombent dans les phases de crise réelles, pas dans la baseline ni la
    # décrue (constaté aux dry runs v2/v3) — les fenêtres finales gardent
    # de la marge pour que la décrue P5 soit mesurable (HA6).
    ("aviosys", "Sous-système avionique lot 1", "serie", 0, 6),
    ("aviosys", "Sous-système avionique lot 2", "serie", 6, 11),
    ("aviosys", "Sous-système avionique lot 3", "serie", 12, 16),
    ("aviosys", "Sous-système avionique lot 4", "serie", 18, 22),
    ("electis", "Cartes HÉLIOS série A", "serie", 0, 6),
    ("electis", "Cartes HÉLIOS série B", "serie", 6, 13),
    ("electis", "Cartes HÉLIOS série C", "serie", 13, 21),
    ("compodis", "Couverture composants S1", "livraison", 0, 9),
    ("compodis", "Couverture composants S2", "livraison", 9, 21),
    ("transglobal", "Contrat de flux annuel", "custom", 0, 12),
    ("transglobal", "Renouvellement contrat de flux", "custom", 12, 22),
    ("novafab", "Allocation wafers HÉLIOS", "serie", 0, 10),
    ("novafab", "Allocation wafers HÉLIOS S2", "serie", 10, 22),
    ("meridian", "Créneaux de production engagés", "custom", 0, 20),
    # Deadline 15 (pas 14) : à l'échéance exacte, l'égalité flottante t == d*
    # bascule en « retard avéré » (u_time = 1.0) pour un tour — artefact qui
    # polluerait le test HA5 à T13 (dry run v4).
    ("silpure", "Contrat wafers annuel", "livraison", 0, 15),
    ("silpure", "Contrat wafers année suivante", "livraison", 14, 20),
]

#: Re-planifications OFFICIELLES de jalons en dérive : {(node, nom, tour): nouvelle
#: deadline (semaines moteur)}. Pratique réelle (revue de programme) et
#: narrativement ancrée : l'annonce de C. Vasseur à T13 EST la re-planification
#: de HÉLIOS-1. Sans re-planification, un jalon en dépassement épingle
#: u_time = 1.0 (retard avéré — comportement documenté du modèle).
MILESTONE_REPLAN: dict[tuple[str, str, int], int] = {
    ("orbitalys", "Livraison HÉLIOS-1", 13): 14,
    ("orbitalys", "Livraison HÉLIOS-2", 16): 19,
    ("aviosys", "Sous-système avionique lot 2", 11): 12,
    ("aviosys", "Sous-système avionique lot 3", 16): 18,
}

#: Progrès scripté des jalons : {(node_id, nom_jalon, tour): progress}.
#: Seules les DÉRIVES par rapport au nominal sont listées ; le facilitateur pose
#: progress = min(tour/deadline, 1.0) par défaut (avancement nominal).
MILESTONE_DRIFT: dict[tuple[str, str, int], float] = {
    # AvioSys lot 2 (deadline T11) : dérive dès T9 (stock qualifié fond).
    ("aviosys", "Sous-système avionique lot 2", 9): 0.60,
    ("aviosys", "Sous-système avionique lot 2", 10): 0.75,
    ("aviosys", "Sous-système avionique lot 2", 11): 0.85,  # livré en retard à T12
    # AvioSys lot 3 (deadline T16) : rupture effective en P4.
    ("aviosys", "Sous-système avionique lot 3", 14): 0.45,
    ("aviosys", "Sous-système avionique lot 3", 15): 0.60,
    ("aviosys", "Sous-système avionique lot 3", 16): 0.75,
    ("aviosys", "Sous-système avionique lot 3", 17): 0.90,
    # HÉLIOS-1 (deadline T8) : glisse officiellement à T13 (annonce), livré T14.
    ("orbitalys", "Livraison HÉLIOS-1", 7): 0.80,
    ("orbitalys", "Livraison HÉLIOS-1", 8): 0.88,
    ("orbitalys", "Livraison HÉLIOS-1", 13): 0.92,
    # HÉLIOS-2 (deadline T16) : glisse, redevient atteignable en P5.
    ("orbitalys", "Livraison HÉLIOS-2", 15): 0.70,
    ("orbitalys", "Livraison HÉLIOS-2", 16): 0.82,
    ("orbitalys", "Livraison HÉLIOS-2", 18): 0.95,
    # Électis série B (deadline T13) : ralentie par le backend (T12).
    ("electis", "Cartes HÉLIOS série B", 12): 0.72,
    ("electis", "Cartes HÉLIOS série B", 13): 0.85,
    # NovaFab allocation (deadline T10) : tenue au prix d'arbitrages.
    ("novafab", "Allocation wafers HÉLIOS", 9): 0.82,
    ("novafab", "Allocation wafers HÉLIOS", 10): 0.95,
}

#: Tour où chaque jalon passe DONE (progress forcé à 1.0 à ce tour).
#: Un jalon absent reste ACTIVE jusqu'à la fin de la campagne.
MILESTONE_DONE: dict[tuple[str, str], int] = {
    ("orbitalys", "Livraison HÉLIOS-1"): 14,      # livré avec ~6 sem. de glissement
    ("aviosys", "Sous-système avionique lot 1"): 6,
    ("aviosys", "Sous-système avionique lot 2"): 12,
    ("aviosys", "Sous-système avionique lot 3"): 18,
    ("electis", "Cartes HÉLIOS série A"): 6,
    ("electis", "Cartes HÉLIOS série B"): 14,
    ("compodis", "Couverture composants S1"): 9,
    ("transglobal", "Contrat de flux annuel"): 12,
    ("novafab", "Allocation wafers HÉLIOS"): 11,
    ("silpure", "Contrat wafers annuel"): 14,
    # HÉLIOS-2 et Couverture S2 restent ACTIVE jusqu'au bout (fin de fenêtre).
}

#: Couverture de stock d'AvioSys (semaines), scriptée depuis la narration —
#: aucune série externe n'existe pour le stock d'un intégrateur fictif ;
#: assumé et étiqueté « scripté » (ancres narratives : 11 sem. à T6, 7 à T8).
AVIOSYS_COVERAGE_WEEKS: dict[int, float] = {
    0: 11.0, 1: 11.0, 2: 11.0, 3: 11.0, 4: 10.5, 5: 10.0, 6: 11.0, 7: 9.0,
    8: 7.0, 9: 6.0, 10: 5.0, 11: 4.5, 12: 4.0, 13: 3.0, 14: 3.5, 15: 4.0,
    16: 5.0, 17: 6.0, 18: 8.0,
}

#: Lead time fournisseur « constaté » (semaines RÉELLES), série reconstruite par
#: interpolation entre ancres documentées (SOURCES['delais_broadcom'] et presse) :
#: appliquée à novafab (annoncé) et compodis (constaté), converties via real_weeks_h.
LEAD_TIME_ANCHORS_WEEKS: dict[int, float] = {
    0: 12.5, 1: 13.0, 3: 14.0, 8: 22.2, 12: 24.0, 14: 25.0, 16: 25.0,
    17: 24.5, 18: 24.0,
}

# --- Événements moteur par tour ----------------------------------------------------
# Champs validés contre EVENT_CALIBRATION (supplyscore/domain/events.py).
# Choix documenté : le gel Texas (T6) est encodé en `accident` (arrêt de
# production, révision bayésienne + récupération + sévérité cliquet) plutôt qu'en
# `perte_capacite` (qui réduit le volume de STOCKAGE) — mécaniquement plus fidèle.

EVENTS: dict[int, list[dict]] = {
    3: [
        {"node": "novafab", "type": "pic_demande",
         "params": {"nouvelle_demande": 110.0},
         "note": "Recommandes automobiles sur créneaux déjà vendus (nov. 2020)."},
    ],
    5: [
        {"node": "compodis", "type": "retard_fournisseur",
         "params": {"retard_h": real_weeks_h(2)},
         "note": "Passage en mode allocation ; livraisons amont décalées (janv. 2021)."},
    ],
    6: [
        {"node": "novafab", "type": "accident",
         "params": {"duree_arret_h": real_weeks_h(4), "gravite": "critique"},
         "note": "Gel Texas : arrêt à chaud de la fab texane (févr. 2021)."},
    ],
    7: [
        {"node": "novafab", "type": "pic_demande",
         "params": {"nouvelle_demande": 125.0},
         "note": "Report de commandes après l'incendie d'un concurrent (mars 2021)."},
        {"node": "transglobal", "type": "perturbation_transport",
         "params": {"retard_h": real_days_h(6), "surcout": 15000.0},
         "note": "Blocage du canal de Suez, 6 jours + désorganisation (mars 2021)."},
    ],
    10: [
        {"node": "novafab", "type": "rupture_matiere",
         "params": {"duree_prevue_h": real_weeks_h(8), "criticite": 0.7},
         "note": "Sécheresse : rationnement d'eau ultrapure (juin 2021)."},
    ],
    12: [
        {"node": "electis", "type": "perte_capacite",
         "params": {"pct_volume_perdu": 0.30},
         "note": "Backend Asie du Sud-Est en rotation : capacité aval amputée (août 2021)."},
        {"node": "transglobal", "type": "perturbation_transport",
         "params": {"retard_h": real_weeks_h(2), "surcout": 20000.0},
         "note": "Flux backend ralentis, bascule vers le fret aérien (août 2021)."},
    ],
    13: [
        {"node": "compodis", "type": "pic_demande",
         "params": {"nouvelle_demande": 160.0},
         "note": "Sur-commandes massives des clients (bullwhip, sept. 2021)."},
    ],
    14: [
        {"node": "transglobal", "type": "perturbation_transport",
         "params": {"retard_h": real_weeks_h(3), "surcout": 30000.0},
         "note": "Congestion portuaire côte ouest US, 100+ navires (oct. 2021)."},
        {"node": "compodis", "type": "hausse_tarif",
         "params": {"pct": 25.0},
         "note": "Majorations tarifaires, primes spot (oct. 2021)."},
    ],
    16: [
        {"node": "silpure", "type": "hausse_tarif",
         "params": {"pct": 18.0},
         "note": "Répercussion de la flambée du polysilicium (déc. 2021)."},
    ],
}

# --- Personas (niveau « jeu ») ------------------------------------------------------
# RÈGLE D'ÉCRITURE (HC9) : le persona décrit comment l'entreprise parle et ce
# qu'elle craint — JAMAIS combien il faut s'inquiéter ce tour-ci.

PERSONAS: dict[str, dict[str, str]] = {
    "orbitalys": {
        "ton": "courtois mais contractuel",
        "parler": "jalons, pénalités, « engagements », courriels formels",
        "peur": "l'annonce publique d'un retard (réputation)",
        "reflexe": "escalader chez le fournisseur, exiger un plan de rattrapage",
        "angle": "aversion à la perte de face : sensible aux signaux visibles du "
                 "client, moins aux signaux amont lointains",
    },
    "aviosys": {
        "ton": "ingénieur, précis, prudent",
        "parler": "références qualifiées, lots, dossiers de requalification",
        "peur": "la rupture d'un composant qualifié (= 6 mois de requalification)",
        "reflexe": "constituer du stock dès le premier doute",
        "angle": "biais de statu quo : ne jamais changer un composant ; pense en "
                 "semaines de couverture",
    },
    "electis": {
        "ton": "pragmatique d'atelier, direct",
        "parler": "lignes, cadences, ordres de fabrication",
        "peur": "l'arrêt de ligne (équipes au chômage technique)",
        "reflexe": "arbitrer entre clients, acheter au spot",
        "angle": "surcharge d'arbitrages simultanés ; tendance à servir le client "
                 "qui insiste le plus",
    },
    "compodis": {
        "ton": "commercial, rapide, au téléphone",
        "parler": "allocations, quotas, primes, commandes fermes (NCNR)",
        "peur": "perdre un client historique faute d'allocation",
        "reflexe": "sur-commander en amont pour sécuriser ses quotas",
        "angle": "difficulté à distinguer la vraie demande des double-commandes",
    },
    "transglobal": {
        "ton": "opérationnel, factuel, un rien fataliste",
        "parler": "ETA, rotations, taux, force majeure",
        "peur": "promettre un délai qu'il ne contrôle pas",
        "reflexe": "rerouter (aérien vs maritime), payer le surcoût plutôt que le retard",
        "angle": "habitué aux crises courtes ; les crises longues sortent de son cadre",
    },
    "novafab": {
        "ton": "corporate, posé, sûr de soi",
        "parler": "capacité, wafers/mois, mix produit, allocation",
        "peur": "sur-investir dans une capacité qui se retournera (cycle du silicium)",
        "reflexe": "prioriser les marges, lisser la communication externe",
        "angle": "asymétrie d'information : sait l'état réel du carnet, communique "
                 "prudemment",
    },
    "meridian": {
        "ton": "modeste, réaliste",
        "parler": "nœuds matures, créneaux, files d'attente",
        "peur": "accepter plus que ce qu'il peut livrer",
        "reflexe": "refuser poliment, allonger les délais annoncés",
        "angle": "sollicité de toutes parts ; tentation de sur-promettre",
    },
    "silpure": {
        "ton": "long-termiste, sobre",
        "parler": "contrats pluriannuels, pureté, lingots",
        "peur": "casser une relation de 20 ans pour un gain ponctuel",
        "reflexe": "honorer d'abord les contrats historiques",
        "angle": "lent à réagir, mais stable — le contrepoint des paniqueurs",
    },
}

# --- Narration par tour et par canal -----------------------------------------------
# Trois canaux : "presse" (identique pour tous), "bilateral" (par nœud : ce que
# clients/fournisseurs directs lui disent), "interne" (par nœud : ses propres
# constats). make_briefings.py assemble fiche = presse + bilateral[nœud] +
# interne[nœud] + tableau de KPIs ≤ tour.
# RÈGLE HC9 : aucun adjectif d'intensité hors citations de presse.

NARRATIVE: dict[int, dict] = {
    0: {
        "presse": "Numéro d'essai : la revue de presse de votre secteur ne signale "
                  "rien de notable ce mois-ci.",
        "bilateral": {},
        "interne": {},
    },
    1: {
        "presse": "Sortie du premier confinement : les ventes d'ordinateurs et "
                  "d'équipements de télétravail battent des records. Les usines "
                  "électroniques mondiales tournent à plein.",
        "bilateral": {
            "orbitalys": "Courriel de Claire Vasseur (dir. programme) : « HÉLIOS entre "
                         "en production série. Tous les feux sont au vert, tenons le cap. »",
            "aviosys": "Orbitalys confirme le calendrier des lots 1 à 3.",
            "novafab": "Les commerciaux remontent des demandes de créneaux en hausse "
                       "côté grand public.",
        },
        "interne": {
            "novafab": "Taux de charge des fabs : 95 %.",
        },
    },
    2: {
        "presse": "Les constructeurs automobiles, qui avaient annulé leurs commandes "
                  "de composants au printemps, constatent une reprise plus forte "
                  "que prévu.",
        "bilateral": {
            "compodis": "Deux fabricants de composants annoncent des « délais étendus » "
                        "sur une poignée de références automobiles.",
        },
        "interne": {
            "compodis": "Références en délai étendu : 4 % du catalogue.",
        },
    },
    3: {
        "presse": "Les recommandes du secteur automobile affluent chez les fondeurs. "
                  "Un dirigeant cité : « les créneaux de production de ce trimestre "
                  "sont vendus depuis longtemps ».",
        "bilateral": {
            "compodis": "Réponse type de Wei-Han Lu (VP commercial NovaFab) aux "
                        "nouvelles demandes : « premier créneau disponible : dans "
                        "cinq mois ».",
            "silpure": "NovaFab demande une hausse de ses volumes de wafers pour "
                       "les trimestres à venir.",
        },
        "interne": {
            "novafab": "Le carnet dépasse 100 % de la capacité nominale. Délais "
                       "moyens annoncés : 14 semaines (12 en début d'année).",
        },
    },
    4: {
        "presse": "Premiers articles spécialisés sur une « tension sur les "
                  "semi-conducteurs ». Les analystes sont partagés sur sa durée.",
        "bilateral": {
            "aviosys": "Électis mentionne des ruptures ponctuelles sur des "
                       "microcontrôleurs, « résorbées sous quinzaine ».",
            "electis": "CompoDis signale des reports isolés sur deux familles de "
                       "composants.",
        },
        "interne": {
            "electis": "Deux ordres de fabrication décalés d'une semaine faute de "
                       "microcontrôleurs.",
        },
    },
    5: {
        "presse": "Un grand constructeur automobile européen annonce des arrêts de "
                  "lignes faute de puces. Le mot « pénurie » entre dans les titres.",
        "bilateral": {
            "electis": "CompoDis officialise un « mode allocation » sur une partie "
                       "de son catalogue : les volumes demandés ne seront pas tous servis.",
            "orbitalys": "AvioSys répond aux questions du programme : « nos stocks "
                         "couvrent le plan de charge actuel ».",
        },
        "interne": {
            "compodis": "30 % du catalogue passe en allocation. Les appels clients "
                        "ont doublé sur le mois.",
        },
    },
    6: {
        "presse": "Une tempête hivernale exceptionnelle paralyse le Texas : réseau "
                  "électrique effondré, plusieurs usines de semi-conducteurs "
                  "arrêtées à chaud.",
        "bilateral": {
            "compodis": "Notification officielle de NovaFab : force majeure sur sa "
                        "fab texane, livraisons décalées de 4 à 6 semaines, "
                        "réallocation en cours.",
            "electis": "CompoDis répercute : reports sur les références issues de "
                       "la fab texane.",
            "aviosys": "Note d'Électis : « point de vigilance approvisionnement sur "
                       "deux familles de composants ».",
            "transglobal": "Annulations de bookings au départ du Texas.",
            "meridian": "Trois prospects appellent « pour une capacité de secours ».",
            "silpure": "NovaFab demande de décaler des livraisons de wafers vers "
                       "son site principal.",
        },
        "interne": {
            "novafab": "Fab texane à l'arrêt. Plan de redémarrage : 4 semaines. "
                       "Réallocation partielle sur le site principal.",
            "aviosys": "Stock de composants qualifiés : 11 semaines de couverture.",
        },
    },
    7: {
        "presse": "Un incendie détruit une ligne majeure chez un fondeur spécialisé "
                  "dans l'automobile. La même semaine, un porte-conteneurs s'échoue "
                  "en travers du canal de Suez : trafic bloqué six jours.",
        "bilateral": {
            "compodis": "Les clients du fondeur sinistré se reportent en urgence : "
                        "Wei-Han Lu annonce que NovaFab « étudie les demandes par "
                        "ordre de priorité contractuelle ».",
            "electis": "TransGlobal prévient : rotations désorganisées pour "
                       "plusieurs semaines suite au blocage du canal.",
        },
        "interne": {
            "novafab": "Afflux de demandes de report (+25 % sur le carnet).",
            "transglobal": "Six jours de blocage = files d'attente aux deux "
                           "extrémités ; replanification complète des rotations.",
        },
    },
    8: {
        "presse": "Les délais moyens de livraison des semi-conducteurs atteignent "
                  "22 semaines, contre 12 un an plus tôt, selon les distributeurs.",
        "bilateral": {
            "orbitalys": "Courriel de Claire Vasseur à AvioSys : « l'échéance "
                         "HÉLIOS-1 est ce mois-ci. Où en sommes-nous précisément ? »",
            "aviosys": "Électis annonce des livraisons partielles sur le lot en cours.",
        },
        "interne": {
            "aviosys": "Stock de composants qualifiés : 7 semaines de couverture. "
                       "Rappel interne : toute substitution = 6 mois de requalification.",
            "compodis": "Délais constatés fournisseurs : 22 semaines en moyenne.",
        },
    },
    9: {
        "presse": "Sécheresse historique en Asie de l'Est : les réservoirs de l'île "
                  "où se concentre la production mondiale de puces sont à 15 % de "
                  "leur capacité.",
        "bilateral": {
            "compodis": "NovaFab : « aucun impact sur les engagements confirmés à ce "
                        "stade ».",
        },
        "interne": {
            "novafab": "L'eau ultrapure est rationnée entre les fabs du site "
                       "principal. Études de priorisation des lignes en cours.",
        },
    },
    10: {
        "presse": "La sécheresse s'aggrave. Des fondeurs affrètent des camions-"
                  "citernes pour alimenter leurs usines. Un fournisseur majeur de "
                  "wafers annonce que ses capacités sont vendues jusqu'à fin 2022.",
        "bilateral": {
            "compodis": "NovaFab révise ses fenêtres de livraison « pour cause de "
                        "contraintes industrielles temporaires ».",
            "novafab": "SilPure confirme : plus aucun volume additionnel de wafers "
                       "disponible avant fin 2022.",
        },
        "interne": {
            "novafab": "Débit des lignes les plus consommatrices d'eau réduit. "
                       "Camions-citernes affrétés.",
            "silpure": "Carnet wafers : complet jusqu'à fin 2022. Demandes spot "
                       "quotidiennes.",
        },
    },
    11: {
        "presse": "Le marché spot des composants s'envole : certaines références se "
                  "négocient à des multiples de leur prix catalogue chez les courtiers.",
        "bilateral": {
            "electis": "Un courtier propose des microcontrôleurs « disponibles "
                       "immédiatement » à 12 fois le prix catalogue.",
        },
        "interne": {
            "electis": "Achat spot validé pour tenir la ligne médicale. Arbitrages "
                       "quotidiens entre les lignes clients.",
        },
    },
    12: {
        "presse": "Vague épidémique en Asie du Sud-Est : les usines d'assemblage et "
                  "de test de composants tournent par rotations réduites. Le maillon "
                  "aval de la filière, peu connu du grand public, devient le sujet.",
        "bilateral": {
            "electis": "Deux sous-traitants backend notifient des capacités réduites "
                       "« jusqu'à nouvel ordre ».",
            "compodis": "TransGlobal signale des flux très ralentis au départ de "
                        "l'Asie du Sud-Est ; bascule partielle sur le fret aérien.",
        },
        "interne": {
            "electis": "Capacité aval effective estimée à 70 % du nominal.",
            "transglobal": "Demandes de fret aérien en forte hausse ; taux au plus haut.",
        },
    },
    13: {
        "presse": "Un constructeur automobile majeur annonce une réduction de 40 % "
                  "de sa production mondiale. Arrêts d'usines en cascade chez ses "
                  "concurrents.",
        "bilateral": {
            "compodis": "Les commandes clients bondissent bien au-delà des besoins "
                        "déclarés : plusieurs clients admettent « commander large "
                        "pour être servis ».",
            "orbitalys": "AvioSys notifie officiellement un risque de glissement sur "
                         "le lot 3, avec impact possible sur HÉLIOS-2.",
            "aviosys": "Courriel de Claire Vasseur : « HÉLIOS-1 est officiellement "
                       "décalé. Je dois l'annoncer au client final cette semaine. "
                       "Il me faut un plan de rattrapage daté pour HÉLIOS-2. »",
        },
        "interne": {
            "compodis": "Commandes entrantes : +60 % vs demande servie estimée. "
                        "Suspicion de double-commandes généralisées.",
            "orbitalys": "Jalon HÉLIOS-1 : glissement acté en revue de programme.",
        },
    },
    14: {
        "presse": "Congestion portuaire record sur la côte ouest américaine : plus "
                  "de cent navires attendent au mouillage.",
        "bilateral": {
            "electis": "CompoDis introduit des majorations tarifaires sur les "
                       "références sous allocation.",
        },
        "interne": {
            "transglobal": "ETA infiables sur le transpacifique ; réservations "
                           "aériennes complètes trois semaines à l'avance.",
            "compodis": "Majoration moyenne appliquée : +25 % sur les références "
                        "sous allocation.",
        },
    },
    15: {
        "presse": "Les délais de livraison des composants plafonnent à des niveaux "
                  "records. Les fondeurs alternatifs affichent complet.",
        "bilateral": {
            "compodis": "Meridian Semi répond aux sollicitations : « notre carnet "
                        "est complet jusqu'à mi-2023 ».",
        },
        "interne": {
            "meridian": "File de prospects sans précédent ; aucun créneau à offrir "
                        "avant mi-2023.",
        },
    },
    16: {
        "presse": "Le prix du polysilicium a triplé sur un an. Les fabricants de "
                  "wafers répercutent la hausse sur leurs contrats.",
        "bilateral": {
            "novafab": "SilPure notifie une révision tarifaire de +18 % sur les "
                       "livraisons du prochain trimestre.",
            "orbitalys": "Électis confirme le passage du programme HÉLIOS en "
                         "priorité 1 interne.",
        },
        "interne": {
            "electis": "Arbitrage acté : HÉLIOS prioritaire, ligne automobile "
                       "ralentie. Échéance contractuelle HÉLIOS-2 ce mois-ci.",
            "silpure": "Répercussion polysilicium appliquée : +18 %.",
        },
    },
    17: {
        "presse": "Premiers signes de détente sur les composants grand public "
                  "(smartphones). L'automobile et l'industriel restent tendus, "
                  "selon les distributeurs.",
        "bilateral": {
            "compodis": "Quelques clients annulent des commandes passées « par "
                        "précaution » au trimestre précédent.",
        },
        "interne": {
            "novafab": "Mix produit : la demande smartphone ralentit ; créneaux "
                       "libérés partiellement réalloués.",
        },
    },
    18: {
        "presse": "La détente se confirme lentement. Les délais restent longs mais "
                  "cessent de s'allonger, pour la première fois depuis un an et demi.",
        "bilateral": {
            "orbitalys": "Courriel de Claire Vasseur : « le plan de rattrapage "
                         "HÉLIOS-2 tient. Revue finale le mois prochain. »",
        },
        "interne": {
            "compodis": "Les annulations de sur-commandes s'accélèrent — le carnet "
                        "« réel » se dévoile.",
        },
    },
}

# --- Test placebo (HC4) -------------------------------------------------------------
# Deux couples (nœud, tour) reçoivent une fiche à continuation alternative
# plausible. Si le Ud suit le placebo, la mesure reflète la donnée fournie, pas
# un souvenir de la crise réelle. Choisis à l'avance, hors nœuds à événement au
# tour concerné.

PLACEBO: dict[tuple[str, int], dict[str, str]] = {
    ("aviosys", 9): {
        "presse": "Les tensions sur les semi-conducteurs montrent de premiers "
                  "signes d'accalmie : deux fondeurs annoncent des mises en "
                  "service anticipées de capacité.",
        "bilateral": "Électis : « les reports se résorbent ; livraisons complètes "
                     "attendues sous quinzaine ».",
        "interne": "Stock de composants qualifiés : 10 semaines de couverture.",
    },
    ("silpure", 15): {
        "presse": "Le marché des matériaux semi-conducteurs se stabilise : le "
                  "polysilicium recule pour le deuxième mois consécutif.",
        "bilateral": "NovaFab demande une révision à la baisse de ses volumes "
                     "optionnels pour le prochain trimestre.",
        "interne": "Demandes spot en net recul ce mois-ci.",
    },
}

# --- Profils synthétiques (dry run + baseline comparative U10) ----------------------
# Biais appliqué au score de chaque critère AHP (sur l'échelle locale [1, 9]).

SYNTHETIC_PROFILES: dict[str, dict] = {
    "paniqueur": {"bias": +2.0, "nodes": ["compodis", "orbitalys"]},
    "sous_declarant": {"bias": -2.0, "nodes": ["novafab", "silpure"]},
    "neutre": {"bias": 0.0, "nodes": ["aviosys", "electis", "transglobal", "meridian"]},
}

# --- Ancrages documentaires (MANIFEST / narration.md) --------------------------------

SOURCES: dict[str, str] = {
    "chronologie": "Wikipedia — 2020-2023 global chip shortage (timeline) ; "
                   "S&P Global Automotive Insights (juil. 2023)",
    "delais_broadcom": "Presse spécialisée : délais 12,2 sem. (févr. 2020) → "
                       "22,2 sem. (avr. 2021)",
    "gel_texas": "Arrêt des fabs d'Austin (Samsung/NXP/Infineon), févr. 2021, "
                 "~1 mois de redémarrage",
    "incendie": "Incendie Renesas Naka, mars 2021, ~100 jours de retour au niveau "
                "pré-incendie",
    "secheresse": "Sécheresse Taïwan 2021, rationnement d'eau, camions-citernes "
                  "affrétés par les fondeurs",
    "suez": "Ever Given, canal de Suez, mars 2021, 6 jours de blocage",
    "malaisie": "Confinements Malaisie été 2021, backend assembly/test",
    "toyota": "Toyota : réduction ~40 % de la production, sept. 2021 ; arrêts GM",
    "congestion": "Congestion Los Angeles/Long Beach, oct.-nov. 2021, 100+ navires",
    "polysilicium": "Flambée du polysilicium 2021 (×3 sur l'année)",
    "meridian_plein": "GlobalFoundries : capacité vendue jusqu'à mi-2023 (annonces 2021)",
    "wri": "WorldRiskIndex 2021 (env_exposure par pays)",
    "wgi": "Worldwide Governance Indicators, Banque mondiale (political_risk)",
}
