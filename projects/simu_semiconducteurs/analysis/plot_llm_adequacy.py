"""Génération de l'image de l'adéquation moyenne A pour le LLM Pilot et comparaison avec DryRun.

Produit :
- docs/BST_DISCO_JH_2026/Images/4.Operations/helios_llm_pilot_adequacy.png
- docs/BST_DISCO_JH_2026/Images/4.Operations/helios_adequacy_comparison.png
"""

from __future__ import annotations

import csv
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent.parent.parent
ANALYSIS_DIR = ROOT / "projects" / "simu_semiconducteurs" / "analysis"
DRYRUN_CSV = ANALYSIS_DIR / "resultats.csv"
LLM_CSV = ANALYSIS_DIR / "llm_pilot_run" / "resultats_pilot.csv"

OUT_DIR = ROOT / "docs" / "BST_DISCO_JH_2026" / "Images" / "4.Operations"
OUT_DIR.mkdir(parents=True, exist_ok=True)

EVENTS = [
    (3, "pic demande", -5),
    (5, "allocation", -6),
    (6, "gel Texas", -5),
    (7, "incendie + Suez", -6),
    (10, "sécheresse", -5),
    (12, "backend", -5),
    (13, "bullwhip", -6),
    (14, "congestion", -6),
    (16, "polysilicium", -5),
]

PERIODS = [
    (0.5, 4.5, "P1 Baseline"),
    (4.5, 8.5, "P2 Bascule"),
    (8.5, 12.5, "P3 Étau"),
    (12.5, 16.5, "P4 Rupture"),
    (16.5, 18.5, "P5 Décrue"),
]

def load_avg_adequacy(csv_path: Path) -> dict[int, float]:
    """Calcule l'adéquation moyenne A par tour."""
    by_tour: dict[int, list[float]] = {}
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = int(row["tour"])
            a = float(row["adequation"])
            by_tour.setdefault(t, []).append(a)
    return {t: sum(vals) / len(vals) for t, vals in sorted(by_tour.items())}

def generate_llm_adequacy_plot(llm_avg: dict[int, float]):
    fig, ax = plt.subplots(figsize=(15, 4.2), dpi=180)
    
    # Fond et bandes de période
    for idx, (x1, x2, label) in enumerate(PERIODS):
        if idx % 2 == 0:  # P1, P3, P5 ombragés
            ax.axvspan(x1, x2, color="#edf4f9", alpha=0.8, zorder=0)
        ax.text((x1 + x2) / 2, 97, label, ha="center", va="top", fontsize=11, color="#64748b")

    tours = sorted(llm_avg.keys())
    values = [llm_avg[t] for t in tours]

    # Courbe principale LLM
    ax.plot(tours, values, color="#0e6ba8", lw=2.8, marker="o", ms=6, label="Adéquation moyenne A (LLM Pilot)", zorder=3)

    # Événements annotés
    for t_ev, label_ev, offset in EVENTS:
        if t_ev in llm_avg:
            val = llm_avg[t_ev]
            # Triangle orange inversé
            ax.plot(t_ev, val, marker="v", color="#d97706", ms=9, zorder=4)
            # Annotations textuelles sous le point
            ax.text(t_ev, val + offset, label_ev, ha="center", va="top" if offset < 0 else "bottom", 
                    fontsize=9.5, color="#b45309", fontweight="normal")

    ax.set_ylabel("Adéquation moyenne A", fontsize=12, color="#1e293b", labelpad=10)
    ax.set_ylim(35, 100)
    ax.set_xlim(-0.5, 18.5)
    ax.set_xticks(tours)
    ax.set_xticklabels([f"T{t}" for t in tours], fontsize=10.5)
    ax.set_yticks([40, 50, 60, 70, 80, 90, 100])
    ax.tick_params(axis="both", which="major", labelsize=10)
    ax.grid(True, linestyle=":", alpha=0.5, color="#cbd5e1")

    # Clean borders
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color("#94a3b8")

    plt.tight_layout()
    out_path = OUT_DIR / "helios_llm_pilot_adequacy.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Graphique Adéquation LLM Pilot sauvegardé : {out_path}")

def generate_comparison_adequacy_plot(dry_avg: dict[int, float], llm_avg: dict[int, float]):
    fig, ax = plt.subplots(figsize=(15, 4.5), dpi=180)
    
    for idx, (x1, x2, label) in enumerate(PERIODS):
        if idx % 2 == 0:
            ax.axvspan(x1, x2, color="#edf4f9", alpha=0.8, zorder=0)
        ax.text((x1 + x2) / 2, 97, label, ha="center", va="top", fontsize=11, color="#64748b")

    tours = sorted(llm_avg.keys())
    val_dry = [dry_avg[t] for t in tours]
    val_llm = [llm_avg[t] for t in tours]

    ax.plot(tours, val_dry, color="#64748b", lw=2.2, ls="--", marker="s", ms=5, label="DryRun (synthétique)", zorder=3)
    ax.plot(tours, val_llm, color="#0e6ba8", lw=2.8, marker="o", ms=6, label="LLM Pilot (8 agents LLM)", zorder=4)

    for t_ev, label_ev, _ in EVENTS:
        if t_ev in llm_avg:
            ax.plot(t_ev, llm_avg[t_ev], marker="v", color="#d97706", ms=8, zorder=5)

    ax.set_ylabel("Adéquation moyenne A", fontsize=12, color="#1e293b", labelpad=10)
    ax.set_ylim(35, 100)
    ax.set_xlim(-0.5, 18.5)
    ax.set_xticks(tours)
    ax.set_xticklabels([f"T{t}" for t in tours], fontsize=10.5)
    ax.set_yticks([40, 50, 60, 70, 80, 90, 100])
    ax.grid(True, linestyle=":", alpha=0.5, color="#cbd5e1")
    ax.legend(loc="lower right", frameon=True, facecolor="white", edgecolor="#e2e8f0", fontsize=11)

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color("#94a3b8")

    plt.tight_layout()
    out_path = OUT_DIR / "helios_adequacy_comparison.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Graphique Comparatif Adéquation sauvegardé : {out_path}")

def main():
    dry_avg = load_avg_adequacy(DRYRUN_CSV)
    llm_avg = load_avg_adequacy(LLM_CSV)
    generate_llm_adequacy_plot(llm_avg)
    generate_comparison_adequacy_plot(dry_avg, llm_avg)

if __name__ == "__main__":
    main()
