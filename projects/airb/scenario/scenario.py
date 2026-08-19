"""Scenario AIRB — chaine d'approvisionnement d'un constructeur aeronautique.

Second banc d'essai de SupplyScore, concu pour eprouver ce que HELIOS ne pouvait
pas eprouver :

- **profondeur 4 et forte densite** : 15 noeuds, 30 arcs, plusieurs chemins entre
  un fournisseur profond et le client final. HELIOS etait une chaine quasi
  lineaire de 8 noeuds ou chaque niveau n'avait qu'un ou deux predecesseurs, donc
  la propagation n'y etait jamais vraiment mise a l'epreuve ;
- **degradation purement ENDOGENE** : aucun choc exogene scripte. Trois
  fournisseurs s'enlisent progressivement, les douze autres restent nominaux. Le
  modele est donc juge sur ce qu'il peut voir venir, et seulement sur cela ;
- **verite jalon DERIVEE des KPI** (``verite_derivee.py``), non ecrite a la
  main : un jalon rate parce que son noeud avance moins vite, pas parce qu'une
  table le decrete.

Les trois noeuds qui derivent sont choisis pour etre STRUCTURELLEMENT CENTRAUX,
a des rangs differents, de facon que leur degradation se propage par des chemins
distincts : le stratificateur composite (rang 3, trois clients), le cablage
(rang 3, trois clients) et le metallurgiste titane (rang 4, deux clients dont
un critique). Un scenario ou seuls des noeuds peripheriques se degradent ne
testerait pas la propagation.

Ancrages : ecosysteme Airbus (Premium Aerotec, Figeac Aero, Liebherr Aerospace,
Aubert & Duval, Hexcel, Collins). Les entites sont FICTIVES ; seuls les ordres
de grandeur de cycle et de criticite sont repris du domaine.
"""

from __future__ import annotations

# --- Compression temporelle ---------------------------------------------------------
# Un tour de jeu = une semaine MOTEUR (168 h) = un mois REEL. Meme convention que
# HELIOS, pour que les deux campagnes se scorent avec les memes outils.

#: Heures moteur representant une semaine reelle (168 / 4.345).
REAL_WEEK_ENGINE_H: float = 168.0 / 4.345


def real_weeks_h(weeks: float) -> float:
    """Convertit des semaines REELLES en heures MOTEUR."""
    return weeks * REAL_WEEK_ENGINE_H


def real_days_h(days: float) -> float:
    """Convertit des jours REELS en heures MOTEUR."""
    return real_weeks_h(days / 7.0)


# --- Identite du projet -------------------------------------------------------------

PROJECT_ID = "airb"
PROJECT_NAME = "Programme AIRB"
PROJECT_DESCRIPTION = (
    "Chaine d'approvisionnement d'un programme avion court-courrier : quinze "
    "acteurs sur quatre rangs, fortement interconnectes. Aucun choc exogene — "
    "trois fournisseurs se degradent progressivement, et la question est de "
    "savoir si le systeme les designe avant que leurs jalons ne glissent."
)

N_TOURS = 18

#: Correspondance tour -> mois narratif (un tour = un mois reel).
TOUR_TO_MONTH: dict[int, str] = {
    0: "M0", 1: "M1", 2: "M2", 3: "M3", 4: "M4", 5: "M5", 6: "M6", 7: "M7",
    8: "M8", 9: "M9", 10: "M10", 11: "M11", 12: "M12", 13: "M13", 14: "M14",
    15: "M15", 16: "M16", 17: "M17", 18: "M18",
}

# --- Reseau -------------------------------------------------------------------------

NODES: list[dict] = [
    # Rang 0 — client final
    {"id": "airb_fal", "name": "AIRB Ligne d'Assemblage Final", "label": "Client",
     "rank": 0, "location": "Toulouse, France", "consultant": "A1"},

    # Rang 1 — grandes sections
    {"id": "aerostruct", "name": "AeroStruct Fuselage", "label": "Factory",
     "rank": 1, "location": "Hambourg, Allemagne", "consultant": "A2"},
    {"id": "voilure", "name": "Voilure Composite", "label": "Factory",
     "rank": 1, "location": "Broughton, Royaume-Uni", "consultant": "A3"},
    {"id": "sysintegra", "name": "SysIntegra Systemes", "label": "Factory",
     "rank": 1, "location": "Filton, Royaume-Uni", "consultant": "A4"},

    # Rang 2 — equipementiers
    {"id": "propulsia", "name": "Propulsia Nacelles", "label": "Factory",
     "rank": 2, "location": "Toulouse, France", "consultant": "A5"},
    {"id": "avionia", "name": "Avionia Cockpit", "label": "Factory",
     "rank": 2, "location": "Bordeaux, France", "consultant": "A6"},
    {"id": "atterral", "name": "Atterral Trains", "label": "Factory",
     "rank": 2, "location": "Lindenberg, Allemagne", "consultant": "A7"},
    {"id": "cabinova", "name": "CabiNova Interieurs", "label": "Factory",
     "rank": 2, "location": "Buxtehude, Allemagne", "consultant": "A8"},

    # Rang 3 — pieces et sous-ensembles
    {"id": "compolam", "name": "CompoLam Stratifies", "label": "Supplier",
     "rank": 3, "location": "Illescas, Espagne", "consultant": "A9"},
    {"id": "usiforge", "name": "UsiForge Pieces", "label": "Supplier",
     "rank": 3, "location": "Figeac, France", "consultant": "A10"},
    {"id": "harnetec", "name": "HarneTec Cablage", "label": "Supplier",
     "rank": 3, "location": "Kaunas, Lituanie", "consultant": "A11"},
    {"id": "hydralec", "name": "Hydralec Actionneurs", "label": "Supplier",
     "rank": 3, "location": "Vendome, France", "consultant": "A12"},

    # Rang 4 — matiere et logistique
    {"id": "titanor", "name": "Titanor Metaux", "label": "Supplier",
     "rank": 4, "location": "Ussel, France", "consultant": "A13"},
    {"id": "fibrelia", "name": "Fibrelia Carbone", "label": "Supplier",
     "rank": 4, "location": "Besancon, France", "consultant": "A14"},
    {"id": "translog", "name": "TransLog Aero", "label": "Transport",
     "rank": 4, "location": "Hambourg, Allemagne", "consultant": "A15"},
]

#: Arcs orientes fournisseur -> client. ``gamma`` attenue la demande qui descend,
#: ``beta`` amplifie le risque qui remonte. Trente arcs pour quinze noeuds : la
#: densite est le point du scenario, plusieurs chemins reliant un rang 4 au
#: client final.
ARCS: list[dict] = [
    # Rang 1 -> client final
    {"source": "aerostruct", "target": "airb_fal", "gamma": 0.95, "beta": 0.95, "kind": "nominal"},
    {"source": "voilure", "target": "airb_fal", "gamma": 0.95, "beta": 0.95, "kind": "nominal"},
    {"source": "sysintegra", "target": "airb_fal", "gamma": 0.90, "beta": 0.90, "kind": "nominal"},
    {"source": "propulsia", "target": "airb_fal", "gamma": 0.70, "beta": 0.75, "kind": "nominal"},
    {"source": "cabinova", "target": "airb_fal", "gamma": 0.55, "beta": 0.45, "kind": "nominal"},

    # Rang 2 -> rang 1
    {"source": "propulsia", "target": "voilure", "gamma": 0.60, "beta": 0.65, "kind": "nominal"},
    {"source": "avionia", "target": "sysintegra", "gamma": 0.90, "beta": 0.90, "kind": "nominal"},
    {"source": "atterral", "target": "aerostruct", "gamma": 0.75, "beta": 0.80, "kind": "nominal"},
    {"source": "atterral", "target": "voilure", "gamma": 0.45, "beta": 0.50, "kind": "nominal"},
    {"source": "cabinova", "target": "aerostruct", "gamma": 0.65, "beta": 0.55, "kind": "nominal"},
    {"source": "avionia", "target": "aerostruct", "gamma": 0.40, "beta": 0.45, "kind": "nominal"},

    # Rang 3 -> rang 2 (le coeur de la densite)
    {"source": "compolam", "target": "voilure", "gamma": 0.90, "beta": 0.90, "kind": "nominal"},
    {"source": "compolam", "target": "propulsia", "gamma": 0.70, "beta": 0.75, "kind": "nominal"},
    {"source": "compolam", "target": "cabinova", "gamma": 0.50, "beta": 0.45, "kind": "nominal"},
    {"source": "usiforge", "target": "aerostruct", "gamma": 0.80, "beta": 0.85, "kind": "nominal"},
    {"source": "usiforge", "target": "atterral", "gamma": 0.85, "beta": 0.85, "kind": "nominal"},
    {"source": "usiforge", "target": "propulsia", "gamma": 0.55, "beta": 0.60, "kind": "nominal"},
    {"source": "harnetec", "target": "avionia", "gamma": 0.90, "beta": 0.90, "kind": "nominal"},
    {"source": "harnetec", "target": "sysintegra", "gamma": 0.65, "beta": 0.70, "kind": "nominal"},
    {"source": "harnetec", "target": "cabinova", "gamma": 0.60, "beta": 0.55, "kind": "nominal"},
    {"source": "hydralec", "target": "atterral", "gamma": 0.75, "beta": 0.80, "kind": "nominal"},
    {"source": "hydralec", "target": "sysintegra", "gamma": 0.70, "beta": 0.70, "kind": "nominal"},
    {"source": "hydralec", "target": "voilure", "gamma": 0.50, "beta": 0.55, "kind": "nominal"},

    # Rang 4 -> rang 3
    {"source": "titanor", "target": "usiforge", "gamma": 0.90, "beta": 0.90, "kind": "nominal"},
    {"source": "titanor", "target": "hydralec", "gamma": 0.70, "beta": 0.75, "kind": "nominal"},
    {"source": "fibrelia", "target": "compolam", "gamma": 0.90, "beta": 0.90, "kind": "nominal"},
    {"source": "fibrelia", "target": "voilure", "gamma": 0.35, "beta": 0.40, "kind": "nominal"},

    # Logistique : elle traverse les rangs, c'est sa nature
    {"source": "translog", "target": "aerostruct", "gamma": 0.45, "beta": 0.50, "kind": "nominal"},
    {"source": "translog", "target": "voilure", "gamma": 0.45, "beta": 0.50, "kind": "nominal"},
    {"source": "translog", "target": "compolam", "gamma": 0.30, "beta": 0.35, "kind": "nominal"},
]

# --- Socle de KPI -------------------------------------------------------------------
# Ordres de grandeur du domaine : un cycle de section fuselage se compte en mois,
# une piece usinee en semaines, une bobine de fibre en semaines longues. Les six
# blocs sont renseignes sur CHAQUE noeud — la lecon de HELIOS, ou une couverture
# de 25,6 % rendait la moitie des blocs muets et toute calibration illusoire.


def _socle(lead_semaines: float, ecart: float, oee: tuple[float, float, float],
           p_panne: float, recup_semaines: float, severite: float,
           volume: tuple[float, float], co2: tuple[float, float, float]) -> dict[str, float]:
    """Construit un socle KPI complet a partir des grandeurs qui distinguent un noeud.

    Args:
        lead_semaines: cycle nominal, en semaines REELLES.
        ecart: ecart-type du cycle, en semaines REELLES.
        oee: (disponibilite, performance, qualite).
        p_panne: probabilite hebdomadaire de defaillance.
        recup_semaines: temps de retour a la normale, en semaines REELLES.
        severite: gravite d'une defaillance, dans [0, 1].
        volume: (capacite, occupation) en m3.
        co2: (plafond, cible, mix energetique) en g/h.

    Returns:
        Le dictionnaire KPI complet du noeud.
    """
    dispo, perf, qual = oee
    vol_max, vol_courant = volume
    co2_max, co2_cible, co2_mix = co2
    return {
        "time.lead_time_h": real_weeks_h(lead_semaines),
        "time.lead_time_std_h": real_weeks_h(ecart),
        "time.delay_h": 0.0,
        "network.demand": 100.0,
        "inventory.flow_rate": 100.0,
        "inventory.max_volume_m3": vol_max,
        "inventory.current_volume_m3": vol_courant,
        "oee.availability": dispo,
        "oee.performance": perf,
        "oee.quality": qual,
        "cost.nominal_op_cost": 100.0,
        "cost.op_cost": 100.0,
        "cost.storage_cost": 20.0,
        "cost.tariff": 1.0,
        "risk.failure_probability": p_panne,
        "risk.recovery_time_h": real_weeks_h(recup_semaines),
        "risk.severity": severite,
        "risk.env_exposure": 0.05,
        "risk.political_risk": 0.04,
        "co2.co2_max_g_h": co2_max,
        "co2.co2_target_g_h": co2_cible,
        "co2.energy_mix_g_h": co2_mix,
        "co2.op_emission_g_h": co2_mix * 1.35,
    }


BASELINE_KPIS: dict[str, dict[str, float]] = {
    # Rang 0 : assemblage final, cycle long, qualite intransigeante.
    "airb_fal": _socle(26, 4, (0.92, 0.90, 0.998), 0.008, 20, 0.30, (900, 300), (18000, 9000, 4200)),

    # Rang 1 : grandes sections.
    "aerostruct": _socle(20, 3.5, (0.93, 0.91, 0.996), 0.010, 16, 0.28, (700, 260), (16000, 8200, 3900)),
    "voilure": _socle(22, 4, (0.90, 0.89, 0.995), 0.012, 18, 0.32, (750, 300), (17000, 8600, 4100)),
    "sysintegra": _socle(18, 3, (0.94, 0.92, 0.997), 0.009, 14, 0.26, (500, 180), (12000, 6200, 2900)),

    # Rang 2 : equipementiers.
    "propulsia": _socle(16, 3, (0.92, 0.90, 0.995), 0.012, 14, 0.30, (450, 170), (14000, 7000, 3300)),
    "avionia": _socle(14, 2.5, (0.95, 0.93, 0.998), 0.010, 12, 0.24, (300, 110), (9000, 4600, 2200)),
    "atterral": _socle(17, 3, (0.91, 0.90, 0.996), 0.013, 15, 0.31, (400, 160), (13000, 6700, 3100)),
    "cabinova": _socle(12, 2.5, (0.93, 0.91, 0.993), 0.014, 10, 0.22, (600, 240), (10000, 5100, 2400)),

    # Rang 3 : pieces. compolam et harnetec sont deux des trois noeuds qui deriveront.
    "compolam": _socle(13, 2.5, (0.90, 0.88, 0.992), 0.016, 12, 0.34, (350, 140), (15000, 7600, 3600)),
    "usiforge": _socle(11, 2, (0.92, 0.90, 0.994), 0.015, 9, 0.28, (320, 120), (13500, 6900, 3200)),
    "harnetec": _socle(9, 2, (0.94, 0.91, 0.991), 0.014, 8, 0.25, (250, 95), (7000, 3600, 1700)),
    "hydralec": _socle(12, 2.5, (0.92, 0.90, 0.995), 0.013, 11, 0.29, (280, 105), (11000, 5600, 2600)),

    # Rang 4 : matiere et logistique. titanor est le troisieme noeud qui derivera.
    "titanor": _socle(24, 4.5, (0.89, 0.87, 0.990), 0.018, 22, 0.38, (500, 200), (26000, 13000, 6300)),
    "fibrelia": _socle(15, 3, (0.91, 0.89, 0.993), 0.015, 13, 0.33, (420, 165), (21000, 10500, 5000)),
    "translog": _socle(6, 1.5, (0.96, 0.93, 0.997), 0.011, 5, 0.20, (1200, 480), (24000, 12000, 5800)),
}

# --- Jalons -------------------------------------------------------------------------
# (node_id, nom, nature, tour de debut, echeance d'origine). Les echeances sont
# etalees pour que les issues ne se concentrent pas sur quelques tours : un
# echantillon groupe ne dit rien du pouvoir de classement du modele.

MILESTONES: list[tuple[str, str, str, int, int]] = [
    ("airb_fal", "Jalon d'assemblage MSN-001", "livraison", 0, 14),
    ("airb_fal", "Jalon d'assemblage MSN-002", "livraison", 14, 22),
    ("aerostruct", "Troncon central lot 1", "serie", 0, 8),
    ("aerostruct", "Troncon central lot 2", "serie", 8, 16),
    ("voilure", "Caisson de voilure lot 1", "serie", 0, 9),
    ("voilure", "Caisson de voilure lot 2", "serie", 9, 18),
    ("sysintegra", "Integration systemes bloc A", "custom", 0, 11),
    ("propulsia", "Nacelles serie 1", "serie", 0, 10),
    ("avionia", "Suite avionique v1", "serie", 0, 7),
    ("avionia", "Suite avionique v2", "serie", 7, 17),
    ("atterral", "Trains lot de qualification", "serie", 0, 12),
    ("cabinova", "Amenagement cabine lot 1", "serie", 0, 6),
    ("cabinova", "Amenagement cabine lot 2", "serie", 6, 15),
    ("compolam", "Stratifies voilure lot 1", "livraison", 0, 7),
    ("compolam", "Stratifies voilure lot 2", "livraison", 7, 16),
    ("usiforge", "Pieces usinees lot 1", "livraison", 0, 6),
    ("usiforge", "Pieces usinees lot 2", "livraison", 6, 13),
    ("harnetec", "Harnais cabine lot 1", "livraison", 0, 5),
    ("harnetec", "Harnais cabine lot 2", "livraison", 5, 12),
    ("hydralec", "Actionneurs lot 1", "livraison", 0, 9),
    ("titanor", "Contrat titane annuel", "livraison", 0, 10),
    ("titanor", "Contrat titane annee 2", "livraison", 10, 20),
    ("fibrelia", "Fibre carbone campagne 1", "livraison", 0, 8),
    ("translog", "Contrat de flux annuel", "custom", 0, 13),
]

#: AUCUNE replanification scriptee : replanifier est une DECISION de joueur, pas
#: une donnee de scenario. En bras ferme, les personas le feront eux-memes.
MILESTONE_REPLAN: dict[tuple[str, str, int], int] = {}

#: AUCUNE derive d'avancement scriptee : l'avancement DECOULE des KPI, calcule
#: par ``verite_derivee.py``. C'est toute la difference avec HELIOS, ou la verite
#: etait ecrite a la main et ou degrader un fournisseur ne changeait donc rien a
#: ce qu'il advenait de ses jalons.
MILESTONE_DRIFT: dict[tuple[str, str, int], float] = {}

#: Idem : rempli par la derivation, pas ecrit ici.
MILESTONE_DONE: dict[tuple[str, str], int] = {}

# --- Degradation endogene -----------------------------------------------------------

#: Les trois fournisseurs qui s'enlisent : ``node_id -> (hausse du lead time en
#: heures moteur par tour, tour de depart)``. Departs ECHELONNES pour que les
#: issues se repartissent dans le temps.
#:
#: Choix des trois : chacun est central et a un rang different, de sorte que leur
#: degradation se propage par des chemins distincts.
#:   - ``compolam`` (rang 3) alimente voilure, propulsia et cabinova ;
#:   - ``harnetec`` (rang 3) alimente avionia, sysintegra et cabinova ;
#:   - ``titanor`` (rang 4) alimente usiforge et hydralec, deux rangs sous le client.
DERIVE_ENDOGENE: dict[str, tuple[float, int]] = {
    "compolam": (22.0, 2),
    "harnetec": (14.0, 4),
    "titanor": (30.0, 1),
}

#: Aucun evenement moteur : la campagne est purement endogene.
EVENTS: dict[int, list[dict]] = {}

# --- Personas -----------------------------------------------------------------------
# Une carte de role par noeud. Elles decrivent un METIER et une PERSONNALITE, pas
# une conduite a tenir : un declarant a qui l'on dit quoi declarer ne mesure plus
# rien. Les biais sont volontairement contrastes, parce que l'outil mesure
# justement l'ecart entre ce qui est declare et ce qui est calcule.

PERSONAS: dict[str, dict[str, str]] = {
    "airb_fal": {
        "role": "Directeur de programme, ligne d'assemblage final",
        "profil": "Vingt ans de programmes. Vous ne regardez que la date de sortie "
                  "d'usine. Vous avez tendance a croire vos fournisseurs sur parole "
                  "tant qu'ils ne vous ont pas encore fait defaut.",
    },
    "aerostruct": {
        "role": "Responsable production, troncons fuselage",
        "profil": "Ingenieur methodes devenu manager. Factuel, prudent, vous "
                  "annoncez rarement un probleme avant d'en avoir la preuve chiffree.",
    },
    "voilure": {
        "role": "Responsable production, caissons de voilure",
        "profil": "Vous sortez d'un programme qui a derape. Vous surveillez vos "
                  "fournisseurs composite de tres pres et vous alertez tot, quitte "
                  "a passer pour inquiet.",
    },
    "sysintegra": {
        "role": "Responsable integration systemes",
        "profil": "Vous dependez de beaucoup de monde et vous le savez. Vous "
                  "raisonnez en chemin critique et vous detestez les surprises.",
    },
    "propulsia": {
        "role": "Responsable nacelles",
        "profil": "Commercial de formation. Optimiste, vous presentez toujours la "
                  "situation sous son meilleur jour et vous rattrapez a la fin.",
    },
    "avionia": {
        "role": "Responsable avionique de cockpit",
        "profil": "Culture logicielle, cycles courts. Vous croyez pouvoir absorber "
                  "un retard amont par une reorganisation interne.",
    },
    "atterral": {
        "role": "Responsable trains d'atterrissage",
        "profil": "Metier lourd, certification stricte. Vous savez qu'un retard de "
                  "matiere ne se rattrape pas et vous le dites sans detour.",
    },
    "cabinova": {
        "role": "Responsable amenagements cabine",
        "profil": "Vos delais sont courts et vos clients changent d'avis. Vous avez "
                  "l'habitude de vivre en tension et vous la sous-estimez.",
    },
    "compolam": {
        "role": "Directeur d'usine, stratifies composites",
        "profil": "Vous etes sous pression de trois clients a la fois. Vous "
                  "n'aimez pas annoncer une mauvaise nouvelle et vous esperez "
                  "toujours rattraper au tour suivant.",
    },
    "usiforge": {
        "role": "Directeur d'usine, pieces usinees",
        "profil": "Sous-traitant de rang 3 rigoureux. Vous tenez vos engagements "
                  "et vous declarez ce que vous voyez, sans dramatiser.",
    },
    "harnetec": {
        "role": "Directeur d'usine, cablage electrique",
        "profil": "Main-d'oeuvre nombreuse, marges faibles. Vous encaissez les "
                  "a-coups en silence tant que vous pensez pouvoir tenir.",
    },
    "hydralec": {
        "role": "Responsable actionneurs hydrauliques",
        "profil": "Technicien meticuleux. Vous quantifiez tout et vous vous mefiez "
                  "des jugements a vue de nez, y compris des votres.",
    },
    "titanor": {
        "role": "Responsable commercial, metaux et forge",
        "profil": "Vos cycles sont les plus longs de la chaine et vos clients ne "
                  "s'en rendent compte que trop tard. Vous vous estimez injustement "
                  "mis en cause et vous defendez votre position.",
    },
    "fibrelia": {
        "role": "Responsable production, fibre de carbone",
        "profil": "Procede continu, capacite rigide. Vous raisonnez en carnet de "
                  "commandes et vous savez tres tot si vous allez tenir.",
    },
    "translog": {
        "role": "Responsable logistique aeronautique",
        "profil": "Vous voyez passer tous les flux et vous etes souvent le premier "
                  "informe. Vous vous jugez rarement responsable des retards.",
    },
}

#: Profils synthetiques du mode sans LLM : biais fixe ajoute au Ud calcule, sur
#: l'echelle bipolaire du questionnaire. " paniqueur " sur-declare, " sous_declarant "
#: minimise, " neutre " suit. Meme format que HELIOS : {profil: {bias, nodes}}.
#:
#: Les trois noeuds qui derivent sont volontairement places chez les
#: sous-declarants : c'est le cas defavorable et le seul interessant. Un
#: fournisseur qui s'enlise ET qui l'annonce ne teste rien — l'ecart entre
#: urgence declaree et urgence calculee, qui est ce que l'outil mesure, n'existe
#: que si le declarant minimise.
SYNTHETIC_PROFILES: dict[str, dict] = {
    "paniqueur": {"bias": 2.0, "nodes": ["voilure", "atterral"]},
    "sous_declarant": {
        "bias": -2.0,
        "nodes": ["compolam", "harnetec", "titanor", "propulsia", "cabinova"],
    },
    "neutre": {
        "bias": 0.0,
        "nodes": ["airb_fal", "aerostruct", "sysintegra", "avionia",
                  "usiforge", "hydralec", "fibrelia", "translog"],
    },
}

#: Aucune fiche placebo : le scenario ne cherche pas a mesurer la suggestibilite.
PLACEBO: dict[tuple[str, int], dict[str, str]] = {}

#: Narration par tour. Volontairement NEUTRE : aucune mention d'un fournisseur en
#: difficulte, aucune actualite orientee. Un declarant ne doit apprendre l'etat de
#: la chaine que par ses propres indicateurs, sinon la campagne mesure la lecture
#: d'un communique et non la perception d'un operateur.
NARRATIVE: dict[int, dict] = {
    tour: {
        "titre": f"Mois {tour} du programme",
        "contexte": (
            "Cadence de programme nominale. Aucun evenement exterieur notable "
            "ce mois-ci. Reportez-vous a vos propres indicateurs."
        ),
    }
    for tour in range(N_TOURS + 1)
}

#: Sources : aucune serie publique n'alimente ce scenario, entierement construit.
SOURCES: dict[str, str] = {
    "note": "Scenario construit, sans serie externe. Ordres de grandeur de cycle "
            "et de criticite repris du domaine aeronautique civil ; entites fictives.",
}
