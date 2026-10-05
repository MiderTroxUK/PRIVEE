"""Compare le bras temoin et le bras predict d'une meme campagne.

Trois panneaux, parce que l'effet d'AFFICHER une prevision ne se lit pas la ou
on l'attend :

  A. ce que les declarants DISENT de la prevision, tour par tour. C'est le seul
     endroit ou l'affichage laisse une trace nette ;
  B. le score de la prevision dans les deux bras. Les deux courbes se
     superposent : la boucle fermee ne degrade pas la prevision, contrairement
     a ce qu'on redoutait ;
  C. la distribution des sauts de la prevision d'un tour a l'autre, a terrain
     inchange. C'est ce que les declarants invoquent quand ils cessent de la
     croire.

Les etiquettes existent en francais (defaut) et en anglais, parce que le
BST est redige en francais et le rapport de MFE en anglais : une figure
dont les axes sont dans une autre langue que son commentaire coute au
lecteur un aller-retour a chaque lecture.

Usage :
    python graphe_bras_predict.py <sortie.png> <temoin_dir> <predict_dir> <pack>
                                  [--lang fr|en]

Chaque ``*_dir`` est un dossier de campagne contenant ``out/predictions_log.jsonl``
et, pour le bras predict, les ``answers_NN.jsonl``.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(r"C:\PRIVEE\AZURE")
sys.path.insert(0, str(REPO / "projects" / "simu_semiconducteurs" / "experiment" / "calibration"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import banc  # noqa: E402
from banc import charger, horizons_du_journal, scorer  # noqa: E402

#: Charte ALTEN : bleu marine, azur, ocre, azur clair. Aucun rouge.
MARINE, AZUR, OCRE, AZUR_CLAIR = "#043962", "#008BD2", "#FFBA00", "#7DCAED"

#: Ordre d'empilement : ce qui ne bouge pas en bas, ce qui bouge en haut.
INFLUENCES = (
    ("confirme", MARINE),
    ("aucune", "#B8C4CE"),
    ("revise_a_la_hausse", OCRE),
    ("revise_a_la_baisse", AZUR),
)

#: Toutes les chaines affichees, par langue. Rien n'est ecrit en dur ailleurs.
MOTS = {
    "fr": {
        "confirme": "confirme", "aucune": "aucune",
        "revise_a_la_hausse": "révise à la hausse",
        "revise_a_la_baisse": "révise à la baisse",
        "visible": "prévision visible",
        "titre_a": "A. Ce que les déclarants disent de la prévision\n({n} nœuds par tour)",
        "x_a": "tour", "y_a": "déclarations",
        "temoin": "bras témoin", "predict": "bras predict",
        "titre_b": "B. Le score de la prévision ne bouge pas\n(cible jalon, même pack)",
        "x_b": "horizon (semaines)", "y_b": "skill de Brier",
        "superpose": "les deux courbes se superposent",
        "titre_c": "C. Ce que la prévision fait d'un tour à l'autre\n(|Δp| à 4 semaines, même nœud)",
        "x_c": "|variation| entre deux tours consécutifs", "y_c": "occurrences",
        "sauts": "{gros} sauts sur {total}\ndépassent 0,20\n(max {pire:.2f})",
    },
    "en": {
        "confirme": "confirms", "aucune": "no effect",
        "revise_a_la_hausse": "revised upward",
        "revise_a_la_baisse": "revised downward",
        "visible": "forecast visible",
        "titre_a": "A. What declarants say the forecast did\n({n} nodes per turn)",
        "x_a": "turn", "y_a": "declarations",
        "temoin": "control arm", "predict": "treatment arm",
        "titre_b": "B. Displaying it does not change it\n(milestone target, same pack)",
        "x_b": "horizon (weeks)", "y_b": "Brier skill",
        "superpose": "the two curves overlap",
        "titre_c": "C. How far the forecast moves per turn\n(|Δp| at 4 weeks, same node)",
        "x_c": "|change| between consecutive turns", "y_c": "count",
        "sauts": "{gros} of {total} moves\nexceed 0.20\n(max {pire:.2f})",
    },
}


def influences_par_tour(campagne: Path) -> dict[int, collections.Counter]:
    """``{tour: Counter(influence)}`` lu dans les ``answers_NN.jsonl``."""
    par_tour: dict[int, collections.Counter] = {}
    for chemin in sorted(campagne.glob("answers_*.jsonl")):
        tour = int(chemin.stem.split("_")[1])
        compte: collections.Counter = collections.Counter()
        for brute in chemin.read_text(encoding="utf-8").splitlines():
            if brute.strip():
                compte[json.loads(brute).get("influence_prediction")] += 1
        par_tour[tour] = compte
    return par_tour


def sauts(journal: Path, horizon: int = 4) -> list[float]:
    """``|p(t+1) - p(t)|`` par noeud, sur des tours consecutifs."""
    par_noeud: dict[str, dict[int, float]] = collections.defaultdict(dict)
    for brute in journal.read_text(encoding="utf-8").splitlines():
        if not brute.strip():
            continue
        ligne = json.loads(brute)
        valeur = ligne.get(f"p_issue_h{horizon}")
        if valeur is not None:
            par_noeud[ligne["node_id"]][int(ligne["tour"])] = float(valeur)
    ecarts: list[float] = []
    for serie in par_noeud.values():
        tours = sorted(serie)
        ecarts += [abs(serie[b] - serie[a]) for a, b in zip(tours, tours[1:]) if b == a + 1]
    return ecarts


def scorer_bras(journal: Path, pack: Path) -> list[dict]:
    """Scores cible jalon d'un journal, verite du pack."""
    banc._PACK = pack
    banc._VERITE_PACK = None
    if (pack / "VERITE.json").is_file():
        banc.charger_verite(pack / "VERITE.json")
    lignes = charger(journal)
    return scorer(lignes, "jalon", horizons_du_journal(lignes))


def tracer(sortie: Path, temoin: Path, predict: Path, pack: Path,
           lang: str = "fr") -> None:
    """Dessine les trois panneaux et ecrit le PNG, dans la langue demandee."""
    mots = MOTS[lang]
    fig, axes = plt.subplots(1, 3, figsize=(16.0, 4.9))
    fig.patch.set_facecolor("white")

    # --- A : ce que les declarants disent de la prevision ---------------------
    ax = axes[0]
    par_tour = influences_par_tour(predict)
    tours = sorted(par_tour)
    bas = [0.0] * len(tours)
    for cle, couleur in INFLUENCES:
        hauteurs = [par_tour[t][cle] for t in tours]
        ax.bar(tours, hauteurs, bottom=bas, color=couleur, label=mots[cle], width=0.82)
        bas = [b + h for b, h in zip(bas, hauteurs)]
    premier = min((t for t in tours if any(
        par_tour[t][c] for c, _ in INFLUENCES if c != "aucune")), default=4)
    par_noeud = max((sum(c.values()) for c in par_tour.values()), default=0)
    ax.axvline(premier - 0.5, color="#444444", lw=1.4, ls="--")
    ax.text(premier - 0.35, 15.4, mots["visible"], fontsize=8.5, color="#444444")
    ax.set_title(mots["titre_a"].format(n=par_noeud), fontsize=11)
    ax.set_xlabel(mots["x_a"])
    ax.set_ylabel(mots["y_a"])
    ax.set_xticks([t for t in tours if t % 2 == 0])
    ax.set_ylim(0, 17.2)
    ax.legend(fontsize=8, loc="lower left", ncol=2, framealpha=0.95)
    ax.grid(alpha=0.2, axis="y")

    # --- B : le score, dans les deux bras -------------------------------------
    ax = axes[1]
    ax.axhline(0.0, color="#666666", lw=1.1, ls="--", zorder=1)
    for nom, dossier, couleur, style in (
        (mots["temoin"], temoin, MARINE, "-"),
        (mots["predict"], predict, OCRE, "--"),
    ):
        res = scorer_bras(dossier / "out" / "predictions_log.jsonl", pack)
        xs = [r["h"] for r in res if r.get("skill") is not None]
        ys = [r["skill"] for r in res if r.get("skill") is not None]
        ax.plot(xs, ys, marker="o", ms=5.5, lw=2.2, color=couleur, ls=style, label=nom)
    ax.set_title(mots["titre_b"], fontsize=11)
    ax.set_xlabel(mots["x_b"])
    ax.set_ylabel(mots["y_b"])
    ax.text(0.03, 0.96, mots["superpose"], transform=ax.transAxes,
            ha="left", va="top", fontsize=8, color="#444444")
    ax.legend(fontsize=8.5, loc="lower right", framealpha=0.9)
    ax.grid(alpha=0.25)

    # --- C : de combien la prevision saute d'un tour a l'autre -----------------
    ax = axes[2]
    ecarts = sauts(predict / "out" / "predictions_log.jsonl")
    ax.hist(ecarts, bins=24, color=AZUR, edgecolor="white")
    ax.axvline(0.20, color=OCRE, lw=1.8, ls="--")
    gros = sum(1 for e in ecarts if e > 0.20)
    ax.text(0.225, ax.get_ylim()[1] * 0.72,
            mots["sauts"].format(gros=gros, total=len(ecarts), pire=max(ecarts)),
            fontsize=8.5, color="#444444")
    ax.set_title(mots["titre_c"], fontsize=11)
    ax.set_xlabel(mots["x_c"])
    ax.set_ylabel(mots["y_c"])
    ax.grid(alpha=0.2, axis="y")

    fig.tight_layout()
    sortie.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(sortie, dpi=170, facecolor="white")
    print(f"-> {sortie}")


def main() -> None:
    """Lit les quatre chemins en arguments, plus la langue, et trace."""
    args = sys.argv[1:]
    lang = "fr"
    if "--lang" in args:
        i = args.index("--lang")
        lang = args[i + 1]
        del args[i:i + 2]
    if len(args) != 4 or lang not in MOTS:
        raise SystemExit(__doc__)
    tracer(Path(args[0]), Path(args[1]), Path(args[2]), Path(args[3]), lang)


if __name__ == "__main__":
    main()
