"""Pipeline de preparation (U5) : series brutes -> pack de donnees par tour.

Produit sous ``data/prepared/`` :
    - ``tour_NN.csv``        (node_id, kpi_path, valeur) - KPIs pilotes par les donnees ;
    - ``events_NN.json``     evenements moteur du tour (depuis scenario.EVENTS) ;
    - ``milestones_NN.json`` progres/statut des jalons du tour ;
    - ``HASHES.sha256``      gel du pack (aucune retouche en campagne).

REGLE " UN SEUL PILOTE PAR (noeud, champ) " : chaque champ KPI est pilote SOIT
par une serie, SOIT par les evenements calibres - jamais les deux. Quand un
evenement ecrit un champ a un tour donne, la serie saute ce tour (liste
SKIP_SERIES_ON_EVENT). C'est la parade au double comptage identifiee au PLAN.

Table de mapping (source -> champ), toutes transformations nommees ci-dessous :

| Noeud       | Champ                      | Pilote                                       |
|------------|----------------------------|----------------------------------------------|
| novafab    | network.demand             | WSTS worldwide / baseline x100 (sauf T3, T7 : evenements pic_demande) |
| meridian   | network.demand             | WSTS worldwide / baseline x100 (la demande de marche le frappe aussi) |
| compodis   | inventory.flow_rate        | WSTS worldwide / baseline x100 (volume servi) |
| compodis   | network.demand             | evenements uniquement (pic_demande T13)      |
| compodis   | time.lead_time_h           | serie reconstruite (delais constates) sauf T5 (evenement) |
| compodis   | cost.op_cost               | IPP composants / baseline x nominal (prix catalogue - plat en realite, et c'est informatif : la prime spot passe par l'evenement hausse_tarif T14) |
| electis    | oee.performance            | IPI NAF 26.1 lisse 3 mois / baseline x 0.90  |
| electis    | oee.availability           | TUC interpole mensuel / 82.6 (dernier trimestre pre-covid, borne [0,1]) |
| electis    | cost.op_cost               | IPP industrie / baseline x nominal           |
| silpure    | cost.op_cost               | IPP industrie / baseline x nominal (contexte ; la flambee polysilicium passe par hausse_tarif T16) |
| novafab    | cost.op_cost               | PPI semi-conducteurs US (Kaggle/BLS, HD5 : authentique) / baseline x nominal - serie arretee nov. 2021 : T16-T18 sans ecriture (derniere valeur persiste, jamais d'invention) |
| silpure    | risk.failure_probability   | defaillances industrie / baseline x p_base   |
| compodis   | risk.failure_probability   | defaillances industrie / baseline x p_base   |
| aviosys    | inventory.flow_rate        | AVIOSYS_COVERAGE_WEEKS -> capacite d'alimentation 100xmin(couv/6, 1) (scripte narration - assume) |
| *          | risk.cost_volatility       | ecart-type glissant 3 tours / moyenne de la serie de cout du noeud |

Note honnete sur les defaillances : la serie REELLE BAISSE sur 2020-2021
(soutien public " quoi qu'il en coute ") - le facteur defaillances DIMINUE donc
le risque externe pendant que la crise sectorielle fait rage. C'est exactement
l'argument multi-blocs : un indicateur macro seul raconte le contraire du
terrain. Conserve tel quel, documente au BST.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import openpyxl

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scenario"))

import scenario  # noqa: E402

RAW = _HERE.parent / "data" / "raw"
OUT = _HERE.parent / "data" / "prepared"

#: (node, kpi_path) -> tours ou un evenement pilote le champ (la serie saute).
SKIP_SERIES_ON_EVENT: dict[tuple[str, str], set[int]] = {
    ("novafab", "network.demand"): {3, 7},
    ("compodis", "time.lead_time_h"): {5},
    ("compodis", "cost.op_cost"): set(),  # hausse_tarif T14 touche tariff, pas op_cost
}


def _load_series(slug: str) -> dict[str, float]:
    with (RAW / f"{slug}.csv").open(encoding="utf-8") as f:
        return {r["periode"]: float(r["valeur"]) for r in csv.DictReader(f)}


def _load_kaggle_ppi_semi() -> dict[str, float]:
    """PPI semi-conducteurs US (Kaggle 'Semiconductor shortage affects', BLS).

    Controle HD5 passe (series FRED/BLS reconnaissables : declin seculaire du
    PPI, emploi sectoriel coherent). Dates au format 01-MM-AAAA, serie arretee
    en novembre 2021 : les mois absents ne sont simplement pas ecrits.
    """
    path = RAW / "Semiconductor shortage affects.csv"
    out: dict[str, float] = {}
    if not path.exists():
        return out
    ppi_col = "Producer Price Index(By  Industry in $)"
    with path.open(encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            raw = (row.get(ppi_col) or "").strip()
            if raw in ("", "."):
                continue
            _day, month, year = row["DATE"].split("-")
            out[f"{year}-{month}"] = float(raw)
    return out


def _load_wsts_worldwide() -> dict[str, float]:
    wb = openpyxl.load_workbook(RAW / "wsts_historical_billings.xlsx", data_only=True)
    ws = wb["Monthly Data"]
    out: dict[str, float] = {}
    year: int | None = None
    for row in ws.iter_rows(values_only=True):
        if isinstance(row[0], int):
            year = row[0]
        elif row[0] == "Worldwide" and year and year >= 2019:
            for m, v in enumerate(row[1:13], 1):
                if isinstance(v, (int, float)):
                    out[f"{year}-{m:02d}"] = float(v)
    return out


def _months() -> list[str]:
    """Mois reels des tours 1..18 (T0 = baseline, pas de mois)."""
    return [scenario.TOUR_TO_MONTH[t] for t in range(1, scenario.N_TOURS + 1)]


def _rolling3(series: dict[str, float], month: str, months: list[str]) -> float:
    """Moyenne centree 3 mois (de-saisonnalisation legere de l'IPI)."""
    idx = months.index(month)
    window = [series.get(months[i]) for i in range(max(0, idx - 1), min(len(months), idx + 2))]
    vals = [v for v in window if v is not None]
    return sum(vals) / len(vals)


def _tuc_monthly(tuc: dict[str, float]) -> dict[str, float]:
    """Interpole la serie TUC trimestrielle en mensuel (lineaire entre trimestres)."""
    quarters = sorted(k for k in tuc if "Q" in k)
    points: list[tuple[str, float]] = []
    for q in quarters:
        year, qn = int(q[:4]), int(q[-1])
        mid_month = 3 * qn - 1  # mois central du trimestre
        points.append((f"{year:04d}-{mid_month:02d}", tuc[q]))
    monthly: dict[str, float] = {}
    for (m1, v1), (m2, v2) in zip(points, points[1:], strict=False):
        y1, mo1 = int(m1[:4]), int(m1[5:])
        y2, mo2 = int(m2[:4]), int(m2[5:])
        span = (y2 - y1) * 12 + (mo2 - mo1)
        for step in range(span):
            y, mo = y1 + (mo1 + step - 1) // 12, (mo1 + step - 1) % 12 + 1
            monthly[f"{y:04d}-{mo:02d}"] = v1 + (v2 - v1) * step / span
    monthly[points[-1][0]] = points[-1][1]
    return monthly


def _lead_time_weeks(tour: int) -> float:
    """Lead time (semaines reelles) au tour donne, interpole entre ancres."""
    anchors = sorted(scenario.LEAD_TIME_ANCHORS_WEEKS.items())
    if tour <= anchors[0][0]:
        return anchors[0][1]
    for (t1, v1), (t2, v2) in zip(anchors, anchors[1:], strict=False):
        if t1 <= tour <= t2:
            return v1 + (v2 - v1) * (tour - t1) / (t2 - t1)
    return anchors[-1][1]


def _volatility(values: list[float]) -> float:
    """Volatilite glissante : ecart-type / moyenne des 3 dernieres valeurs, [0,1]."""
    tail = values[-3:]
    if len(tail) < 2:
        return 0.0
    mean = sum(tail) / len(tail)
    if mean == 0:
        return 0.0
    var = sum((v - mean) ** 2 for v in tail) / len(tail)
    return min(max((var**0.5) / mean, 0.0), 1.0)


def build_tours() -> dict[int, list[tuple[str, str, float]]]:
    """Construit les ecritures KPI (node, path, valeur) pour chaque tour 0..18."""
    months = _months()
    ipi = _load_series("insee_ipi_naf261")
    ipp_ind = _load_series("insee_ipp_industrie")
    ipp_comp = _load_series("insee_ipp_composants")
    defail = _load_series("insee_defaillances_industrie")
    tuc_m = _tuc_monthly(_load_series("insee_tuc_manuf"))
    wsts = _load_wsts_worldwide()

    def baseline(series: dict[str, float]) -> float:
        return (series["2020-07"] + series["2020-08"]) / 2.0

    b_ipi = (_rolling3(ipi, "2020-07", ["2020-06", "2020-07", "2020-08"])
             + _rolling3(ipi, "2020-08", ["2020-07", "2020-08", "2020-09"])) / 2.0
    b_ipp_ind = baseline(ipp_ind)
    b_ipp_comp = baseline(ipp_comp)
    b_defail = baseline(defail)
    b_wsts = baseline(wsts)
    tuc_ref = 82.6  # dernier trimestre pre-covid (2020-Q1), borne de normalisation

    ppi_semi = _load_kaggle_ppi_semi()
    b_ppi_semi = (
        (ppi_semi["2020-07"] + ppi_semi["2020-08"]) / 2.0 if ppi_semi else None
    )

    cost_hist: dict[str, list[float]] = {
        "electis": [], "silpure": [], "compodis": [], "novafab": []
    }
    tours: dict[int, list[tuple[str, str, float]]] = {0: []}

    for tour, month in enumerate(months, start=1):
        rows: list[tuple[str, str, float]] = []
        wsts_idx = 100.0 * wsts[month] / b_wsts
        # NovaFab : demande mondiale (les delais clients sont portes par compodis).
        if tour not in SKIP_SERIES_ON_EVENT[("novafab", "network.demand")]:
            rows.append(("novafab", "network.demand", round(wsts_idx, 1)))
        # NovaFab : contexte cout PPI US (serie arretee nov. 2021 - mois absents non ecrits, la derniere valeur persiste dans le moteur).
        if b_ppi_semi is not None and month in ppi_semi:
            op_semi = round(100.0 * ppi_semi[month] / b_ppi_semi, 2)
            rows.append(("novafab", "cost.op_cost", op_semi))
            cost_hist["novafab"].append(op_semi)
            rows.append(
                ("novafab", "risk.cost_volatility",
                 round(_volatility(cost_hist["novafab"]), 4))
            )
        # Meridian : la meme vague de demande le frappe (capacite flow constante).
        rows.append(("meridian", "network.demand", round(wsts_idx, 1)))
        # CompoDis : volume servi (WSTS), delais constates, prix catalogue, risque.
        rows.append(("compodis", "inventory.flow_rate", round(wsts_idx, 1)))
        if tour not in SKIP_SERIES_ON_EVENT[("compodis", "time.lead_time_h")]:
            rows.append(
                ("compodis", "time.lead_time_h", scenario.real_weeks_h(_lead_time_weeks(tour)))
            )
        op_comp = round(100.0 * ipp_comp[month] / b_ipp_comp, 2)
        rows.append(("compodis", "cost.op_cost", op_comp))
        cost_hist["compodis"].append(op_comp)
        rows.append(
            ("compodis", "risk.cost_volatility", round(_volatility(cost_hist["compodis"]), 4))
        )
        rows.append(
            ("compodis", "risk.failure_probability",
             round(0.02 * defail[month] / b_defail, 5))
        )
        # Electis : performance (IPI lisse), disponibilite (TUC), cout (IPP), risque.
        perf = 0.90 * _rolling3(ipi, month, months) / b_ipi
        rows.append(("electis", "oee.performance", round(min(max(perf, 0.0), 1.0), 4)))
        if month in tuc_m:
            avail = min(max(tuc_m[month] / tuc_ref, 0.0), 1.0)
            rows.append(("electis", "oee.availability", round(avail, 4)))
        op_ind = round(100.0 * ipp_ind[month] / b_ipp_ind, 2)
        rows.append(("electis", "cost.op_cost", op_ind))
        cost_hist["electis"].append(op_ind)
        rows.append(
            ("electis", "risk.cost_volatility", round(_volatility(cost_hist["electis"]), 4))
        )
        # SilPure : cout contexte (IPP industrie) + risque defaillances.
        rows.append(("silpure", "cost.op_cost", op_ind))
        cost_hist["silpure"].append(op_ind)
        rows.append(
            ("silpure", "risk.cost_volatility", round(_volatility(cost_hist["silpure"]), 4))
        )
        rows.append(
            ("silpure", "risk.failure_probability",
             round(0.01 * defail[month] / b_defail, 5))
        )
        # AvioSys : couverture de stock scriptee (narration) exprimee en capacite d'alimentation des lignes : flow = 100 x min(couverture / cycle 6 sem., 1).
        cov = scenario.AVIOSYS_COVERAGE_WEEKS[tour]
        rows.append(("aviosys", "inventory.flow_rate", round(100.0 * min(cov / 6.0, 1.0), 1)))
        tours[tour] = rows
    return tours


def build_milestones() -> dict[int, list[dict]]:
    """Progres/statut des jalons par tour : nominal + derives + completions."""
    out: dict[int, list[dict]] = {}
    for tour in range(0, scenario.N_TOURS + 1):
        rows: list[dict] = []
        for node, name, _kind, start_wk, deadline_wk in scenario.MILESTONES:
            done_tour = scenario.MILESTONE_DONE.get((node, name))
            if done_tour is not None and tour > done_tour:
                continue  # deja DONE, plus rien a ecrire
            if done_tour is not None and tour == done_tour:
                rows.append({"node": node, "name": name, "progress": 1.0, "status": "done"})
                continue
            drift = scenario.MILESTONE_DRIFT.get((node, name, tour))
            if drift is not None:
                progress = drift
            else:
                # L'horloge moteur a avance de (tour + 1) semaines a la cloture du tour N (T0 compte une avance) : le progres nominal suit ce temps, sinon chaque jalon serait artificiellement " en retard " d'un tour.
                span = max(deadline_wk - start_wk, 1)
                progress = min(max((tour + 1 - start_wk) / span, 0.0), 1.0)
                # Apres une derive, ne jamais " re-sauter " au nominal : reprendre la derniere valeur scriptee si elle est plus basse.
                past = [
                    v for (n, m, t), v in scenario.MILESTONE_DRIFT.items()
                    if n == node and m == name and t < tour
                ]
                if past and max(past) < progress:
                    progress = max(past)
            entry: dict = {"node": node, "name": name, "progress": round(progress, 3),
                           "status": "active"}
            replan = scenario.MILESTONE_REPLAN.get((node, name, tour))
            if replan is not None:
                entry["deadline_wk"] = replan
            rows.append(entry)
        out[tour] = rows
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tours = build_tours()
    milestones = build_milestones()

    written: list[Path] = []
    for tour in range(0, scenario.N_TOURS + 1):
        csv_path = OUT / f"tour_{tour:02d}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["node_id", "kpi_path", "valeur"])
            writer.writerows(tours.get(tour, []))
        written.append(csv_path)

        ev_path = OUT / f"events_{tour:02d}.json"
        ev_path.write_text(
            json.dumps(scenario.EVENTS.get(tour, []), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written.append(ev_path)

        ms_path = OUT / f"milestones_{tour:02d}.json"
        ms_path.write_text(
            json.dumps(milestones[tour], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written.append(ms_path)

    # Gel du pack : hash de chaque fichier (aucune retouche en campagne).
    lines = []
    for p in sorted(written):
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{h}  {p.name}")
    (OUT / "HASHES.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(written)} fichiers écrits sous {OUT}")
    print("Pack gelé : HASHES.sha256")
    return 0


if __name__ == "__main__":
    sys.exit(main())
