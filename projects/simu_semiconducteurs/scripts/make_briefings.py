"""Générateur de fiches consultants (U7) — anti-lookahead structurel.

Usage :
    python make_briefings.py --tour N [--placebo]
    python make_briefings.py --role-cards

Garantie anti-fuite (HC5) : ce script ne lit QUE les fichiers préparés des
tours <= N. Aucune donnée future n'est présente en mémoire au moment de
générer une fiche — l'exclusion est structurelle, pas une consigne.

``--placebo`` : pour les couples (nœud, tour) définis dans scenario.PLACEBO,
génère EN PLUS une variante ``<node>_placebo.md`` dont les canaux narratifs
(presse/bilatéral/interne) racontent une continuation alternative plausible.
Le tableau de données (<= N) reste identique : seul le récit est manipulé
(contrôle HC4).

Sorties : ``briefings/tour_NN/<node>.md`` et ``briefings/cartes_de_role/``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import _common
from _common import PREPARED, PROJECT_DIR, scenario

BRIEFINGS = PROJECT_DIR / "briefings"

#: Champs montrés au consultant, par nœud : uniquement SES données pilotées.
#: Libellés métier (jamais les chemins techniques).
FIELD_LABELS: dict[str, str] = {
    "network.demand": "Indice de demande client (base 100)",
    "inventory.flow_rate": "Indice de volume servi (base 100)",
    "time.lead_time_h": "Délai fournisseur constaté (semaines réelles)",
    "cost.op_cost": "Indice de coût opérationnel (base 100)",
    "risk.cost_volatility": "Volatilité des coûts (3 derniers tours)",
    "risk.failure_probability": "Probabilité d'incident majeur (mensuelle)",
    "oee.performance": "Performance de production (0-1)",
    "oee.availability": "Disponibilité de l'outil (0-1)",
    "inventory.current_volume_m3": "Remplissage d'entrepôt (m³ occupés)",
}


def _fmt_value(path: str, value: float) -> str:
    if path == "time.lead_time_h":
        return f"{value / scenario.REAL_WEEK_ENGINE_H:.1f}"
    if path in ("oee.performance", "oee.availability"):
        return f"{value:.2f}"
    if path == "risk.failure_probability":
        return f"{value:.3f}"
    if path == "risk.cost_volatility":
        return f"{value:.4f}"
    return f"{value:.1f}"


def _node_data_upto(node_id: str, tour: int) -> dict[str, list[tuple[int, float]]]:
    """Historique {kpi_path: [(tour, valeur)]} du nœud, tours 0..N UNIQUEMENT."""
    series: dict[str, list[tuple[int, float]]] = {}
    for t in range(0, tour + 1):
        with (PREPARED / f"tour_{t:02d}.csv").open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["node_id"] == node_id:
                    series.setdefault(row["kpi_path"], []).append(
                        (t, float(row["valeur"]))
                    )
    return series


def _own_milestones(node_id: str, tour: int) -> list[dict]:
    data = json.loads(
        (PREPARED / f"milestones_{tour:02d}.json").read_text(encoding="utf-8")
    )
    return [m for m in data if m["node"] == node_id]


def _narrative_for(node_id: str, tour: int, placebo: bool) -> tuple[str, str, str]:
    if placebo and (node_id, tour) in scenario.PLACEBO:
        alt = scenario.PLACEBO[(node_id, tour)]
        return alt["presse"], alt.get("bilateral", ""), alt.get("interne", "")
    nar = scenario.NARRATIVE.get(tour, {})
    return (
        nar.get("presse", ""),
        nar.get("bilateral", {}).get(node_id, ""),
        nar.get("interne", {}).get(node_id, ""),
    )


def _neighbours(node_id: str) -> tuple[list[str], list[str]]:
    names = {n["id"]: n["name"] for n in scenario.NODES}
    clients = [names[a["target"]] for a in scenario.ARCS if a["source"] == node_id]
    suppliers = [
        names[a["source"]]
        + (" (secours)" if a["kind"] == "backup" else "")
        for a in scenario.ARCS
        if a["target"] == node_id
    ]
    return clients, suppliers


def briefing(node_id: str, tour: int, placebo: bool = False) -> str:
    spec = next(n for n in scenario.NODES if n["id"] == node_id)
    clients, suppliers = _neighbours(node_id)
    presse, bilateral, interne = _narrative_for(node_id, tour, placebo)
    data = _node_data_upto(node_id, tour)
    milestones = _own_milestones(node_id, tour)

    lines = [
        f"# Tour {tour} — {spec['name']}",
        "",
        f"*Vous êtes le/la responsable supply chain de **{spec['name']}** "
        f"({spec['location']}).*",
        f"*Vos clients : {', '.join(clients) or '(client final)'} — "
        f"vos fournisseurs : {', '.join(suppliers) or '(aucun en amont)'}.*",
        "",
        "## Revue de presse du secteur",
        "",
        presse or "(rien de notable ce tour-ci)",
        "",
    ]
    if bilateral:
        lines += ["## Vos échanges clients / fournisseurs", "", bilateral, ""]
    if interne:
        lines += ["## Vos constats internes", "", interne, ""]

    if data:
        lines += ["## Vos indicateurs (jusqu'au tour courant)", ""]
        shown_tours = sorted({t for pts in data.values() for t, _ in pts})[-4:]
        header = "| Indicateur | " + " | ".join(f"T{t}" for t in shown_tours) + " |"
        sep = "|---" * (len(shown_tours) + 1) + "|"
        lines += [header, sep]
        for path, pts in sorted(data.items()):
            label = FIELD_LABELS.get(path, path)
            by_tour = dict(pts)
            cells = [
                _fmt_value(path, by_tour[t]) if t in by_tour else "—"
                for t in shown_tours
            ]
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
        lines.append("")

    if milestones:
        lines += ["## Vos jalons", ""]
        for m in milestones:
            statut = "TERMINÉ" if m.get("status") == "done" else "en cours"
            lines.append(f"- **{m['name']}** : avancement {m['progress']:.0%} ({statut})")
        lines.append("")

    lines += [
        "## À faire maintenant (10 min max)",
        "",
        "Remplissez le questionnaire hebdomadaire (volet AHP) dans l'outil, en "
        "comparant les 4 critères pour VOTRE périmètre :",
        "1. **Impact opérationnel** — si ma tâche échoue, quelle conséquence en aval ?",
        "2. **Fenêtre temporelle** — combien de temps avant que ce soit irrattrapable ?",
        "3. **Dépendances aval** — combien d'acteurs attendent après moi ?",
        "4. **Récupérabilité** — peut-on rattraper un retard ?",
        "",
        "*Rappels : ne consultez que cette fiche et la page questionnaire ; pas "
        "de concertation avec les autres rôles ; il n'y a pas de « bonne "
        "réponse » — déclarez ce que VOUS percevez.*",
    ]
    return "\n".join(lines)


def role_card(node_id: str) -> str:
    spec = next(n for n in scenario.NODES if n["id"] == node_id)
    persona = scenario.PERSONAS[node_id]
    clients, suppliers = _neighbours(node_id)
    return "\n".join(
        [
            f"# Carte de rôle — {spec['name']} ({spec['consultant']})",
            "",
            f"**Vous êtes le/la responsable supply chain de {spec['name']}**, "
            f"{spec['location']}.",
            "",
            scenario.PROJECT_DESCRIPTION,
            "",
            f"- **Vos clients directs** : {', '.join(clients) or 'le client final du programme'}",
            f"- **Vos fournisseurs directs** : {', '.join(suppliers) or 'aucun (amont de la chaîne)'}",
            "",
            "## Votre entreprise, votre voix",
            "",
            f"- **Ton interne** : {persona['ton']}.",
            f"- **Vous parlez en** : {persona['parler']}.",
            f"- **Votre peur principale** : {persona['peur']}.",
            f"- **Votre réflexe de crise** : {persona['reflexe']}.",
            f"- **Votre angle** : {persona['angle']}.",
            "",
            "*Ce persona vous aide à incarner le rôle : il décrit comment votre "
            "entreprise parle et ce qu'elle craint — jamais combien il faut "
            "s'inquiéter à un tour donné. Ça, c'est VOTRE jugement.*",
            "",
            "## Les règles du jeu",
            "",
            "1. Deux tours par jour (matin et fin de journée), ~10 minutes chacun.",
            "2. À chaque tour : lisez votre fiche, remplissez le volet AHP dans l'outil.",
            "3. Vous ne voyez QUE votre fiche — pas celles des autres rôles.",
            "4. Pas de concertation entre rôles pendant la campagne.",
            "5. Ne consultez pas le tableau de bord ni les scores : uniquement la "
            "page questionnaire.",
            "6. Il n'y a pas de bonne réponse : déclarez votre perception, "
            "pas ce que vous croyez attendu.",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tour", type=int, help="Génère les fiches du tour N")
    parser.add_argument("--placebo", action="store_true",
                        help="Génère aussi les variantes placebo (scenario.PLACEBO)")
    parser.add_argument("--role-cards", action="store_true",
                        help="Génère les cartes de rôle (kickoff J5)")
    args = parser.parse_args(argv)

    if args.role_cards:
        out = BRIEFINGS / "cartes_de_role"
        out.mkdir(parents=True, exist_ok=True)
        for spec in scenario.NODES:
            path = out / f"{spec['id']}.md"
            path.write_text(role_card(spec["id"]), encoding="utf-8")
            print(f"[carte] {path}")
        return 0

    if args.tour is None:
        parser.error("--tour N ou --role-cards requis")
    out = BRIEFINGS / f"tour_{args.tour:02d}"
    out.mkdir(parents=True, exist_ok=True)
    for spec in scenario.NODES:
        path = out / f"{spec['id']}.md"
        path.write_text(briefing(spec["id"], args.tour), encoding="utf-8")
        print(f"[fiche] {path}")
        if args.placebo and (spec["id"], args.tour) in scenario.PLACEBO:
            alt = out / f"{spec['id']}_placebo.md"
            alt.write_text(briefing(spec["id"], args.tour, placebo=True), encoding="utf-8")
            print(f"[fiche PLACEBO] {alt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
