"""Pilote de campagne BRAS C avec personas LLM.

Le harnais ``run_experiment.py`` ne fait aucun appel LLM : il lit et ecrit des
fichiers. Ce pilote decoupe la campagne pour laisser le coordinateur intercaler
les agents :

    python campagne_bras_c.py init      <travail>
    python campagne_bras_c.py preparer  <travail> <tour>   # -> fiches
    ... le coordinateur fait tourner les agents ...
    python campagne_bras_c.py verifier  <travail> <tour>   # -> qui doit reprendre
    ... le coordinateur relance UNIQUEMENT ceux-la ...
    python campagne_bras_c.py cloturer  <travail> <tour>   # -> collecte + cloture

Chaque agent ne voit QUE son dossier ``out/sandbox_<node>/`` (protocole
anti-fuite herite du pilote) et y depose sa reponse dans ``results.jsonl``.

## Deux regles de protocole, et pourquoi

**1. Rien ne parvient au declarant hors de son bac a sable.** Un retour du type
« bien joue », « ton action a ete appliquee » ou « vise CR < 0.10 » envoye par le
canal de coordination est une information qu'aucun operateur reel n'aurait recue
au meme moment : elle teinte toutes ses decisions posterieures. Tout retour
legitime passe donc par un fichier ECRIT PAR L'OUTIL dans le bac a sable
(``tours/retour_tour_NN.md``), jamais par le message de relance.

**2. Une seconde chance avant de reconduire.** L'outil reel guide l'utilisateur
vers sa comparaison la plus contradictoire et lui laisse corriger. Reconduire
directement la declaration precedente sur un CR >= 0.10, comme le fait le
harnais, coupe cette etape. ``verifier`` calcule donc le CR AVANT soumission,
ecrit le retour de l'outil, et signale qui doit reprendre. Ce n'est qu'apres ce
second refus que la reconduction s'applique.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from supplyscore.core.ahp import bipolar_to_saaty, run_ahp

# La console Windows est en cp1252 : la sortie du harnais ne s'y encode pas.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(r"C:\PRIVEE\AZURE")
PY = REPO / ".venv" / "Scripts" / "python.exe"
CLI = REPO / "projects" / "simu_semiconducteurs" / "experiment" / "run_experiment.py"
ARM = "act"

NODES = [
    "orbitalys", "aviosys", "electis", "compodis",
    "transglobal", "novafab", "meridian", "silpure",
]

#: Champs obligatoires d'une reponse de persona en bras act.
CHAMPS_REQUIS = ("bipolar", "scores_ui", "note", "influence_prediction", "action_id")

#: Les 6 paires comparees, dans l'ordre du questionnaire.
PAIRES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))

#: Libelles des criteres, pour le retour de l'outil.
CRITERES = ("Impact operationnel", "Fenetre temporelle", "Dependances aval", "Recuperabilite")

#: Seuil de coherence de l'AHP (Saaty).
SEUIL_CR = 0.10


def run(travail: Path, *args: str) -> str:
    """Lance une sous-commande du harnais ; sort en erreur si elle echoue."""
    proc = subprocess.run(
        [str(PY), str(CLI), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        (travail / "erreur.txt").write_text(
            f"COMMANDE: {' '.join(args)}\n\n--- STDOUT ---\n{proc.stdout}\n"
            f"--- STDERR ---\n{proc.stderr}",
            encoding="utf-8",
        )
        print(f"ECHEC : {' '.join(args[:2])}\n{(proc.stderr or proc.stdout)[-1500:]}")
        sys.exit(1)
    print(proc.stdout.rstrip())
    return proc.stdout


def _ligne_du_tour(chemin: Path, tour: int) -> tuple[dict | None, list[str]]:
    """Derniere ligne de ``results.jsonl`` portant ce numero de tour.

    Lu en ``utf-8-sig`` : les personas ecrivent depuis des outils Windows qui
    prefixent volontiers un BOM, et un BOM fait echouer ``json.loads`` sur la
    PREMIERE ligne — donc justement sur le tour 0.

    Returns:
        La ligne trouvee (ou None) et la liste des anomalies, pour que
        l'appelant DISE pourquoi il refuse au lieu de compter un fichier
        illisible comme une reponse absente.
    """
    if not chemin.is_file():
        return None, [f"{chemin.name} absent"]
    anomalies: list[str] = []
    trouvee: dict | None = None
    for numero, brute in enumerate(chemin.read_text(encoding="utf-8-sig").splitlines(), 1):
        brute = brute.strip().lstrip("\ufeff")
        if not brute:
            continue
        try:
            ligne = json.loads(brute)
        except json.JSONDecodeError as err:
            anomalies.append(f"ligne {numero} illisible ({err.msg})")
            continue
        if ligne.get("tour") == tour:
            trouvee = ligne  # la DERNIERE gagne : le persona a pu se corriger
    if trouvee is None and not anomalies:
        anomalies.append(f"aucune ligne au tour {tour}")
    return trouvee, anomalies


def _coherence(bipolar: list[int]) -> tuple[float, tuple[int, int] | None]:
    """Ratio de coherence AHP et paire la plus contradictoire.

    Reproduit le guidage de l'outil reel : la paire (i, j) dont le jugement
    s'ecarte le plus du rapport de poids implicite, soit le plus grand
    ``|ln(A[i,j]) - ln(w_i/w_j)|``.

    Args:
        bipolar: les 6 curseurs bipolaires entiers, dans l'ordre de PAIRES.

    Returns:
        Le CR, et la paire a revoir (None si le CR est acceptable).
    """
    comparisons = {
        paire: bipolar_to_saaty(v) for paire, v in zip(PAIRES, bipolar, strict=True)
    }
    resultat = run_ahp(comparisons, n=4)
    if resultat.consistency_ratio < SEUIL_CR:
        return resultat.consistency_ratio, None
    poids = resultat.weights
    pire, ecart_max = None, -1.0
    for (i, j), valeur in comparisons.items():
        ecart = abs(np.log(valeur) - np.log(poids[i] / poids[j]))
        if ecart > ecart_max:
            pire, ecart_max = (i, j), ecart
    return resultat.consistency_ratio, pire


def _ecrire_retour(sandbox: Path, tour: int, cr: float, paire: tuple[int, int]) -> Path:
    """Ecrit le retour de l'outil dans le bac a sable du declarant.

    C'est l'outil qui parle, pas le coordinateur : le texte reprend ce que
    l'interface reelle affiche a un utilisateur dont le questionnaire est
    incoherent.
    """
    i, j = paire
    rang = PAIRES.index(paire) + 1
    texte = f"""# Retour de l'outil — tour {tour}

Votre questionnaire n'a pas passe le controle de coherence.

**Ratio de coherence : CR = {cr:.3f}** (seuil d'acceptation : {SEUIL_CR:.2f}).

Un CR au-dessus du seuil signifie que vos six jugements se contredisent entre
eux : pris deux a deux ils decrivent des priorites qui ne peuvent pas coexister.
Ce n'est pas une erreur de fond, c'est une question d'echelle — vos ecarts sont
probablement plus tranches que ce que l'ensemble supporte.

## La comparaison a revoir en priorite

**Comparaison n°{rang} — « {CRITERES[i]} » contre « {CRITERES[j]} »**

C'est celle dont le jugement s'ecarte le plus du reste de vos reponses. Si vous
maintenez les cinq autres, c'est celle-ci qui doit bouger.

## Ce que vous pouvez faire

- Reduire l'amplitude de cette comparaison (un 6 devient un 3, un -8 un -4) ;
- ou verifier la transitivite : si A compte plus que B et B plus que C, alors A
  doit dominer C d'autant plus, pas moins.

Reprenez votre declaration du tour {tour} et **ajoutez une nouvelle ligne** a
`results.jsonl` avec `"attempts": 2`. La derniere ligne du tour fait foi.

Sans nouvelle declaration acceptable, votre declaration du tour precedent sera
reconduite a votre place.
"""
    chemin = sandbox / "tours" / f"retour_tour_{tour:02d}.md"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8")
    return chemin


def cmd_init(travail: Path) -> None:
    """Cree la base du bras act et les huit bacs a sable persona."""
    travail.mkdir(parents=True, exist_ok=True)
    run(travail, "init", "--arm", ARM, "--db-dir", str(travail / "db"))
    run(travail, "make-sandboxes", "--arm", ARM, "--out", str(travail / "out"))
    print(f"\nBacs a sable prets : {travail / 'out'}")


def cmd_preparer(travail: Path, tour: int) -> None:
    """Injecte le tour et produit les fiches (analyse predictive et leviers)."""
    run(travail, "prepare-tour", "--arm", ARM, "--db-dir", str(travail / "db"),
        "--out", str(travail / "out"), "--tour", str(tour))
    print(f"\nTour {tour} pret. Chaque agent lit son dossier et AJOUTE sa ligne "
          f"tour={tour} a results.jsonl.")


def cmd_verifier(travail: Path, tour: int) -> None:
    """Controle la coherence AVANT soumission et ecrit les retours de l'outil.

    N'ecrit rien en base. Affiche la liste des noeuds qui doivent reprendre —
    le coordinateur ne relance QUE ceux-la, et sans rien leur expliquer : le
    retour est deja dans leur bac a sable.
    """
    out = travail / "out"
    a_reprendre: list[str] = []
    absents: list[str] = []
    for node in NODES:
        brut, anomalies = _ligne_du_tour(out / f"sandbox_{node}" / "results.jsonl", tour)
        if brut is None:
            absents.append(f"{node} ({' ; '.join(anomalies)})")
            continue
        bipolar = brut.get("bipolar")
        if not isinstance(bipolar, list) or len(bipolar) != 6:
            absents.append(f"{node} (bipolar invalide)")
            continue
        cr, paire = _coherence([int(v) for v in bipolar])
        tentative = int(brut.get("attempts", 1) or 1)
        if paire is None:
            print(f"  {node:<13} CR = {cr:.3f}  OK")
        elif tentative >= 2:
            print(f"  {node:<13} CR = {cr:.3f}  >= {SEUIL_CR} — 2e tentative deja faite, "
                  f"le harnais reconduira")
        else:
            chemin = _ecrire_retour(out / f"sandbox_{node}", tour, cr, paire)
            a_reprendre.append(node)
            print(f"  {node:<13} CR = {cr:.3f}  >= {SEUIL_CR} — retour ecrit : {chemin.name}")

    if absents:
        print("\nREPONSES MANQUANTES :")
        for detail in absents:
            print(f"  {detail}")
    print(f"\nA RELANCER : {' '.join(a_reprendre) if a_reprendre else '(personne)'}")


def cmd_cloturer(travail: Path, tour: int) -> None:
    """Rassemble les huit reponses, collecte le tour et le clot."""
    out = travail / "out"
    lignes: list[str] = []
    manquants: list[str] = []
    for node in NODES:
        brut, anomalies = _ligne_du_tour(out / f"sandbox_{node}" / "results.jsonl", tour)
        if brut is None:
            manquants.append(f"{node} ({' ; '.join(anomalies)})")
            continue
        if anomalies:
            print(f"  [avertissement] {node} : {' ; '.join(anomalies)}")
        absents = [c for c in CHAMPS_REQUIS if c not in brut]
        if absents:
            print(f"REFUS : {node} — champs manquants {absents} au tour {tour}")
            sys.exit(1)
        brut["node_id"] = node
        lignes.append(json.dumps(brut, ensure_ascii=False))
    if manquants:
        print(f"REFUS : reponses inexploitables au tour {tour} —")
        for detail in manquants:
            print(f"  {detail}")
        sys.exit(1)

    answers = travail / f"answers_{tour:02d}.jsonl"
    answers.write_text("\n".join(lignes), encoding="utf-8")
    run(travail, "collect-tour", "--arm", ARM, "--db-dir", str(travail / "db"),
        "--tour", str(tour), "--answers", str(answers), "--out", str(out))
    run(travail, "close-tour", "--arm", ARM, "--db-dir", str(travail / "db"),
        "--out", str(out), "--tour", str(tour))


def main() -> None:
    """Aiguille vers init / preparer / verifier / cloturer."""
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    commande, travail = sys.argv[1], Path(sys.argv[2])
    if commande == "init":
        cmd_init(travail)
    elif commande == "preparer":
        cmd_preparer(travail, int(sys.argv[3]))
    elif commande == "verifier":
        cmd_verifier(travail, int(sys.argv[3]))
    elif commande == "cloturer":
        cmd_cloturer(travail, int(sys.argv[3]))
    else:
        print(f"Commande inconnue : {commande!r}")
        sys.exit(2)


if __name__ == "__main__":
    main()
