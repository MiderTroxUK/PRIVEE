"""Génération du graphique des trajectoires LLM Pilot & comparaison avec DryRun.

Produit :
- docs/BST_DISCO_JH_2026/Images/4.Operations/helios_llm_pilot_trajectories.png
- docs/BST_DISCO_JH_2026/Images/4.Operations/helios_comparison_dryrun_vs_llm.png
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

NODE_SPECS = [
    ("orbitalys", "Orbitalys (client, rang 0)"),
    ("aviosys", "AvioSys (avionique, rang 1)"),
    ("electis", "Électis EMS (cartes, rang 2)"),
    ("compodis", "CompoDis (distribution, rang 3)"),
    ("transglobal", "TransGlobal (fret, rang 3)"),
    ("novafab", "NovaFab (fondeur, rang 4)"),
    ("meridian", "Meridian (fondeur 2nd, rang 4)"),
    ("silpure", "SilPure (wafers, rang 5)"),
]

def load_data(csv_path: Path) -> dict[str, dict[str, list[float]]]:
    """Charge tour, node, ud, ur depuis un resultats.csv."""
    nodes_data = {nid: {"t": [], "ud": [], "ur": []} for nid, _ in NODE_SPECS}
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nid = row["node"]
            if nid in nodes_data:
                nodes_data[nid]["t"].append(int(row["tour"]))
                nodes_data[nid]["ud"].append(float(row["ud"]))
                nodes_data[nid]["ur"].append(float(row["ur"]))
    return nodes_data

def generate_llm_trajectories_plot(llm_data: dict):
    fig, axes = plt.subplots(4, 2, figsize=(14, 13), sharex=True, sharey=True)
    
    # Styliser
    plt.rcParams["font.sans-serif"] = "DejaVu Sans"
    
    for ax, (nid, title) in zip(axes.flat, NODE_SPECS):
        # Bandes claires : P1 (1-4), P3 (9-12), P5 (17-18)
        ax.axvspan(0.5, 4.5, color="#eaf2f8", alpha=0.7, zorder=0)
        ax.axvspan(8.5, 12.5, color="#eaf2f8", alpha=0.7, zorder=0)
        ax.axvspan(16.5, 18.5, color="#eaf2f8", alpha=0.7, zorder=0)
        
        t = llm_data[nid]["t"]
        ur = llm_data[nid]["ur"]
        ud = llm_data[nid]["ud"]
        
        # Ur: bleu continu
        ax.plot(t, ur, label="Ur (réel, données)", color="#0e6ba8", lw=2.2, zorder=3)
        # Ud: orange pointillés
        ax.plot(t, ud, label="Ud (déclaré, LLM agents)", color="#d97706", lw=2.2, ls="--", zorder=4)
        
        ax.set_title(title, fontsize=11, pad=6, color="#2d3748", fontweight="bold")
        ax.set_ylim(-0.02, 1.05)
        ax.set_xlim(-0.5, 18.5)
        ax.set_xticks([0, 3, 6, 9, 12, 15, 18])
        ax.grid(True, linestyle=":", alpha=0.5, color="#cbd5e1")
        ax.tick_params(axis="both", which="major", labelsize=9.5)

    # Légende unique en haut
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.98),
               ncol=2, frameon=False, fontsize=12)

    fig.text(0.5, 0.02, 
             "Tour de jeu (T0 entraînement, T1 à T18 = sept. 2020 à févr. 2022 ; bandes claires : P1, P3, P5)",
             ha="center", fontsize=10, color="#475569")

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    out_path = OUT_DIR / "helios_llm_pilot_trajectories.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Graphique LLM Pilot sauvegardé : {out_path}")

def generate_comparison_plot(dry_data: dict, llm_data: dict):
    fig, axes = plt.subplots(4, 2, figsize=(14, 14), sharex=True, sharey=True)
    
    for ax, (nid, title) in zip(axes.flat, NODE_SPECS):
        ax.axvspan(0.5, 4.5, color="#f1f5f9", alpha=0.8, zorder=0)
        ax.axvspan(8.5, 12.5, color="#f1f5f9", alpha=0.8, zorder=0)
        ax.axvspan(16.5, 18.5, color="#f1f5f9", alpha=0.8, zorder=0)
        
        t = llm_data[nid]["t"]
        ur = llm_data[nid]["ur"]
        ud_dry = dry_data[nid]["ud"]
        ud_llm = llm_data[nid]["ud"]
        
        ax.plot(t, ur, label="Ur (réel)", color="#1e293b", lw=2.2, zorder=3)
        ax.plot(t, ud_dry, label="Ud DryRun (synthétique)", color="#64748b", lw=1.8, ls=":", zorder=4)
        ax.plot(t, ud_llm, label="Ud LLM Pilot (8 agents LLM)", color="#d97706", lw=2.2, ls="--", zorder=5)
        
        ax.set_title(title, fontsize=11, pad=6, color="#1e293b", fontweight="bold")
        ax.set_ylim(-0.02, 1.05)
        ax.set_xlim(-0.5, 18.5)
        ax.set_xticks([0, 3, 6, 9, 12, 15, 18])
        ax.grid(True, linestyle=":", alpha=0.5, color="#cbd5e1")
        ax.tick_params(axis="both", which="major", labelsize=9.5)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.98),
               ncol=3, frameon=False, fontsize=11)

    fig.text(0.5, 0.02, 
             "Comparaison DryRun (synthétique) vs LLM Pilot (agents LLM autonomes) par tour de jeu (T0–T18)",
             ha="center", fontsize=10.5, color="#334155")

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    out_path = OUT_DIR / "helios_comparison_dryrun_vs_llm.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Graphique Comparatif sauvegardé : {out_path}")

def main():
    dry_data = load_data(DRYRUN_CSV)
    llm_data = load_data(LLM_CSV)
    generate_llm_trajectories_plot(llm_data)
    generate_comparison_plot(dry_data, llm_data)

if __name__ == "__main__":
    main()
