"""Analyse de campagne HÉLIOS (U10) — tests pré-enregistrés HA1-HA6.

Consomme les snapshots ``analysis/snapshots/tour_NN.json`` produits par la
campagne (réelle ou dry run) et produit :
    - ``analysis/resultats.csv``   : table agrégée (nœud, tour, Ud, Ur, A, F, H) ;
    - ``analysis/rapport.md``      : verdict de chaque hypothèse pré-enregistrée ;
    - ``analysis/figures/*.png``   : séries Ud/Ur/A par nœud, heatmap H, criticité.

Registre pré-enregistré (verrouillé à J5 — voir PROTOCOLE.md §5) :
    HA1 latence     : corrélation croisée Ud/Ur maximale à lag >= 1 pour >= 5 nœuds/8.
    HA2 précocité   : H > 0.3 sur novafab à au moins un tour de T6-T12.
    HA3 criticité   : novafab top-1 par delta_ur_final PARMI LES FOURNISSEURS
                      PROFONDS (rang >= 4 : novafab, meridian, silpure) sur
                      >= 80 % des tours INFORMATIFS (ceux où le réseau n'est
                      pas saturé, c.-à-d. max(delta_ur_final) > 0). Reformulé
                      au dry run v5 AVANT gel : (a) la proximité du rang 0
                      amplifie mécaniquement delta_ur_final (produit fuyant) —
                      comparer novafab à compodis mesure la topologie, pas la
                      criticité intrinsèque ; (b) en réseau saturé l'indice
                      dégénère (le risque déjà réalisé n'est plus « choquable »,
                      comportement documenté du service) — constat consigné
                      pour le BST, tours saturés exclus du test.
    HA4 calibration : précision ET rappel > 0.5 (seuil H >= 0.5, horizon 4 tours),
                      incidents de référence = événements du scénario (fenêtre
                      de vérité tirée de scenario.EVENTS).
    HA5 contagion   : ΔUd moyen des nœuds NON touchés positif et supérieur aux
                      tours sans événement, aux tours de presse T6, T7, T13.
    HA6 hystérésis  : pente de décroissance Ud < 50 % de celle de Ur sur T17-T18.
Baseline naïve (hypothèse nulle) : détecteur « un KPI dépasse son seuil » rejoué
sur les mêmes tours — la valeur ajoutée de H se mesure CONTRE cette baseline.
Toute autre analyse est étiquetée EXPLORATOIRE.
"""

from __future__ import annotations

import csv
import json
import statistics as st
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "scenario"))
import scenario  # noqa: E402

SNAPSHOTS = _HERE / "snapshots"
FIGURES = _HERE / "figures"

NODE_IDS = [n["id"] for n in scenario.NODES]

#: Tours « à événement de presse » pour HA5 et nœuds touchés à ces tours.
PRESS_TOURS: dict[int, set[str]] = {
    6: {"novafab"},
    7: {"novafab", "transglobal"},
    13: {"compodis", "orbitalys", "aviosys"},  # annonce -40 % + jalons en dérive
}

#: Fenêtre de décrue (HA6).
DECRUE = (17, 18)


def load() -> dict[int, dict]:
    data: dict[int, dict] = {}
    for path in sorted(SNAPSHOTS.glob("tour_*.json")):
        snap = json.loads(path.read_text(encoding="utf-8"))
        if snap.get("tour") is not None:
            data[snap["tour"]] = snap
    if not data:
        raise SystemExit(f"Aucun snapshot dans {SNAPSHOTS}")
    return data


def series(data: dict[int, dict], node: str, field: str) -> list[tuple[int, float]]:
    out = []
    for t in sorted(data):
        v = data[t]["nodes"].get(node, {}).get(field)
        if v is not None:
            out.append((t, float(v)))
    return out


def spearman(xs: list[float], ys: list[float]) -> float:
    """Corrélation de Spearman sans dépendance externe (rangs + Pearson)."""
    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    dx = (sum((a - mx) ** 2 for a in rx)) ** 0.5
    dy = (sum((b - my) ** 2 for b in ry)) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx / 1 * dy)


def cross_correlation_lag(ud: list[float], ur: list[float], max_lag: int = 3) -> int:
    """Lag (en tours) qui maximise Spearman(Ud décalé de +lag, Ur)."""
    best_lag, best_rho = 0, -2.0
    for lag in range(0, max_lag + 1):
        if lag >= len(ud) - 2:
            break
        rho = spearman(ud[lag:], ur[: len(ur) - lag])
        if rho > best_rho:
            best_lag, best_rho = lag, rho
    return best_lag


def ha1(data: dict[int, dict]) -> tuple[bool, str]:
    lags = {}
    for node in NODE_IDS:
        ud = [v for _, v in series(data, node, "ud")]
        ur = [v for _, v in series(data, node, "ur")]
        if len(ud) >= 6:
            lags[node] = cross_correlation_lag(ud, ur)
    n_lagged = sum(1 for v in lags.values() if v >= 1)
    ok = n_lagged >= 5
    return ok, f"lags par nœud : {lags} — {n_lagged}/8 à lag >= 1 (seuil : 5)"


def ha2(data: dict[int, dict]) -> tuple[bool, str]:
    h = dict(series(data, "novafab", "hidden_risk"))
    window = {t: h.get(t, 0.0) for t in range(6, 13)}
    peak = max(window.values()) if window else 0.0
    ok = peak > 0.3
    return ok, f"H(novafab) sur T6-T12 : max = {peak:.3f} (seuil : 0.3) — {window}"


def ha3(data: dict[int, dict]) -> tuple[bool, str]:
    deep = {"novafab", "meridian", "silpure"}  # fournisseurs profonds (rang >= 4)
    verdicts: dict[int, str] = {}
    informative = 0
    top1 = 0
    for t in sorted(data):
        crit = [c for c in data[t].get("criticite", []) if "erreur" not in c]
        if not crit:
            continue
        if max(c.get("delta_ur_final", 0.0) for c in crit) < 1e-9:
            verdicts[t] = "saturé"  # réseau saturé : indice non informatif, exclu
            continue
        informative += 1
        deep_sorted = sorted(
            (c for c in crit if c["node_id"] in deep),
            key=lambda c: -c.get("delta_ur_final", 0.0),
        )
        leader = deep_sorted[0]["node_id"] if deep_sorted else "?"
        verdicts[t] = leader
        if leader == "novafab":
            top1 += 1
    share = top1 / informative if informative else 0.0
    ok = informative > 0 and share >= 0.8
    return ok, (f"leader profond par tour : {verdicts} — novafab top-1 sur "
                f"{share:.0%} des {informative} tours informatifs (seuil : 80 % ; "
                f"tours saturés exclus, dégénérescence documentée)")


def ha4(data: dict[int, dict]) -> tuple[bool, str]:
    horizon, seuil = 4, 0.5
    event_tours_by_node: dict[str, set[int]] = {}
    for t, evs in scenario.EVENTS.items():
        for ev in evs:
            event_tours_by_node.setdefault(ev["node"], set()).add(t)
    tp = fp = tn = fn = 0
    for node in NODE_IDS:
        h = dict(series(data, node, "hidden_risk"))
        for t in sorted(data):
            if t + 1 > max(data):
                continue
            predicted = h.get(t, 0.0) >= seuil
            actual = any(
                t < et <= t + horizon for et in event_tours_by_node.get(node, set())
            )
            tp += predicted and actual
            fp += predicted and not actual
            tn += (not predicted) and (not actual)
            fn += (not predicted) and actual
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    n = tp + fp + tn + fn
    ok = prec > 0.5 and rec > 0.5
    note = "" if n >= 30 else f" [ATTENTION n={n} < 30 : non conclusif]"
    return ok, f"TP={tp} FP={fp} TN={tn} FN={fn} précision={prec:.2f} rappel={rec:.2f} (seuils : 0.5){note}"


def ha5(data: dict[int, dict]) -> tuple[bool, str]:
    def dud(node: str, t: int) -> float | None:
        ud = dict(series(data, node, "ud"))
        if t in ud and (t - 1) in ud:
            return ud[t] - ud[t - 1]
        return None

    press_deltas, calm_deltas = [], []
    calm_tours = [t for t in sorted(data) if t >= 2 and t not in PRESS_TOURS
                  and not scenario.EVENTS.get(t)]
    for t, touched in PRESS_TOURS.items():
        for node in NODE_IDS:
            if node not in touched:
                d = dud(node, t)
                if d is not None:
                    press_deltas.append(d)
    for t in calm_tours:
        for node in NODE_IDS:
            d = dud(node, t)
            if d is not None:
                calm_deltas.append(d)
    m_press = st.mean(press_deltas) if press_deltas else 0.0
    m_calm = st.mean(calm_deltas) if calm_deltas else 0.0
    ok = m_press > 0 and m_press > m_calm
    return ok, (f"ΔUd moyen nœuds non touchés aux tours de presse : {m_press:+.4f} ; "
                f"tours calmes : {m_calm:+.4f} (prédiction : presse > 0 et > calme)")


def ha6(data: dict[int, dict]) -> tuple[bool, str]:
    t1, t2 = DECRUE
    slopes_ud, slopes_ur = [], []
    for node in NODE_IDS:
        ud = dict(series(data, node, "ud"))
        ur = dict(series(data, node, "ur"))
        if t1 in ud and t2 in ud:
            slopes_ud.append(ud[t2] - ud[t1])
            slopes_ur.append(ur[t2] - ur[t1])
    m_ud, m_ur = st.mean(slopes_ud), st.mean(slopes_ur)
    # Prédiction : le Ud redescend MOINS vite que le Ur (|pente Ud| < 0.5 |pente Ur|
    # quand les deux décroissent). Si le Ur ne décroît pas (décrue faible,
    # constaté au dry run §6.8), le test est non applicable — consigné tel quel.
    if m_ur >= 0:
        return False, (f"pente Ur moyenne {m_ur:+.4f} >= 0 : pas de décrue mesurable "
                       f"du Ur sur T{t1}-T{t2} — HA6 NON APPLICABLE (pente Ud {m_ud:+.4f})")
    ok = abs(m_ud) < 0.5 * abs(m_ur)
    return ok, f"pente Ud {m_ud:+.4f} vs pente Ur {m_ur:+.4f} (seuil : |Ud| < 0.5·|Ur|)"


def baseline_naive(data: dict[int, dict]) -> str:
    """Détecteur nul : « le Ur local dépasse 0.5 » — même grille que HA4."""
    horizon, seuil = 4, 0.5
    event_tours_by_node: dict[str, set[int]] = {}
    for t, evs in scenario.EVENTS.items():
        for ev in evs:
            event_tours_by_node.setdefault(ev["node"], set()).add(t)
    tp = fp = tn = fn = 0
    for node in NODE_IDS:
        url = dict(series(data, node, "ur_local"))
        for t in sorted(data):
            predicted = url.get(t, 0.0) >= seuil
            actual = any(t < et <= t + horizon for et in event_tours_by_node.get(node, set()))
            tp += predicted and actual
            fp += predicted and not actual
            tn += (not predicted) and (not actual)
            fn += (not predicted) and actual
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return f"baseline naïve (Ur_local >= 0.5) : précision={prec:.2f} rappel={rec:.2f}"


def write_outputs(data: dict[int, dict], results: dict[str, tuple[bool, str]]) -> None:
    # CSV agrégé.
    with (_HERE / "resultats.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tour", "node", "ud", "ur", "ud_local", "ur_local",
                    "adequation", "false_urgency", "hidden_risk"])
        for t in sorted(data):
            for node, n in data[t]["nodes"].items():
                w.writerow([t, node, n["ud"], n["ur"], n["ud_local"], n["ur_local"],
                            n["adequation"], n["false_urgency"], n["hidden_risk"]])

    # Figures (matplotlib si disponible — best effort).
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        FIGURES.mkdir(exist_ok=True)
        fig, axes = plt.subplots(4, 2, figsize=(14, 16), sharex=True)
        for ax, node in zip(axes.flat, NODE_IDS, strict=False):
            ts_ur = series(data, node, "ur")
            ts_ud = series(data, node, "ud")
            ax.plot([t for t, _ in ts_ur], [v for _, v in ts_ur], label="Ur", lw=2)
            ax.plot([t for t, _ in ts_ud], [v for _, v in ts_ud], label="Ud", lw=2, ls="--")
            ax.set_title(node)
            ax.set_ylim(0, 1.05)
            ax.legend()
        fig.suptitle("Ud vs Ur par nœud — campagne HÉLIOS")
        fig.savefig(FIGURES / "ud_ur_par_noeud.png", dpi=120, bbox_inches="tight")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 5))
        import numpy as np

        tours = sorted(data)
        mat = np.array([
            [data[t]["nodes"][n]["hidden_risk"] or 0.0 for t in tours] for n in NODE_IDS
        ])
        im = ax.imshow(mat, aspect="auto", cmap="Reds", vmin=0, vmax=0.5)
        ax.set_yticks(range(len(NODE_IDS)), NODE_IDS)
        ax.set_xticks(range(len(tours)), [f"T{t}" for t in tours])
        ax.set_title("Risque caché H par nœud et par tour")
        fig.colorbar(im)
        fig.savefig(FIGURES / "heatmap_risque_cache.png", dpi=120, bbox_inches="tight")
        plt.close(fig)
        fig_note = "figures écrites sous analysis/figures/"
    except ImportError:
        fig_note = "matplotlib indisponible : figures non générées (CSV complet dispo)"

    # Rapport.
    lines = ["# Rapport d'analyse — campagne HÉLIOS", "",
             f"Snapshots analysés : tours {min(data)}-{max(data)} "
             f"({len(data)} tours, {len(NODE_IDS)} nœuds).", "",
             "## Hypothèses pré-enregistrées", ""]
    for name, (ok, detail) in results.items():
        verdict = "CONFIRMÉE" if ok else "NON CONFIRMÉE"
        lines += [f"### {name} — {verdict}", "", detail, ""]
    lines += ["## Baseline nulle", "", baseline_naive(data), "",
              "## Notes", "",
              "- Analyses hors registre : à étiqueter EXPLORATOIRE.",
              f"- {fig_note}",
              "- Sur un dry run (Ud synthétique), HA1/HA5/HA6 ne sont PAS "
              "interprétables — seule la mécanique est validée."]
    (_HERE / "rapport.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows cp1252
    data = load()
    results = {
        "HA1 — latence cognitive": ha1(data),
        "HA2 — détection précoce (risque caché)": ha2(data),
        "HA3 — criticité structurelle": ha3(data),
        "HA4 — validité prédictive": ha4(data),
        "HA5 — effet de simple urgence (contagion)": ha5(data),
        "HA6 — hystérésis de la redescente": ha6(data),
    }
    write_outputs(data, results)
    for name, (ok, detail) in results.items():
        print(f"[{'OK ' if ok else 'NON'}] {name}")
        print(f"      {detail}")
    print(f"\nRapport : {_HERE / 'rapport.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
