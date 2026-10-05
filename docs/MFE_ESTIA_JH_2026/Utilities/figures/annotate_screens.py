"""Crop the two application screenshots and give each an English key.

The delivered application has a French interface, because it is operated by a
French research programme, and re-shooting it in English would misrepresent the
artefact. A full-page capture reduced to report width is also unreadable in any
language. Each capture is therefore cropped to the region the surrounding text
discusses and set beside a key that translates the interface terms in the order
they appear, which keeps the evidence authentic and the figure readable.

    C:\\PRIVEE\\AZURE\\.venv\\Scripts\\python.exe annotate_screens.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SOURCE = Path(__file__).resolve().parents[3] / "BST_DISCO_JH_2026" / "Images" / "4.Operations"
#: Les captures annotees vivent avec leurs sources : les deux rapports les
#: partagent par graphicspath, une seule copie sur le disque.
SORTIE = SOURCE

NAVY = (4, 57, 98)
AZURE = (0, 139, 210)
GREY_LINE = (205, 206, 218)
BLUE_BG = (235, 243, 249)
WHITE = (255, 255, 255)

#: Largeur de la colonne de traduction, a droite de la capture.
CLE = 620

#: Repertoires ou chercher une police de la charte.
POLICES = (
    Path("C:/Windows/Fonts"),
    Path("C:/texlive/2026/texmf-dist/fonts/truetype/public/carlito"),
)


def police(taille: int) -> ImageFont.FreeTypeFont:
    """Carlito si presente, sinon une sans-serif systeme."""
    for nom in ("Carlito-Regular.ttf", "calibri.ttf", "arial.ttf", "DejaVuSans.ttf"):
        for base in POLICES:
            if (base / nom).is_file():
                return ImageFont.truetype(str(base / nom), taille)
    return ImageFont.load_default()


def cle_anglaise(nom: str, boite: tuple[int, int, int, int],
                 titre: str, entrees: list[tuple[str, str]], sortie: str) -> None:
    """Recadre la capture et pose la cle de traduction a sa droite.

    Args:
        boite: (gauche, haut, droite, bas) dans l'image d'origine.
        entrees: paires (terme d'interface, equivalent anglais), dans l'ordre
            ou elles apparaissent a l'ecran.
    """
    image = Image.open(SOURCE / f"{nom}.png").crop(boite)
    largeur, hauteur = image.size
    toile = Image.new("RGB", (largeur + CLE, hauteur), WHITE)
    toile.paste(image, (0, 0))

    dessin = ImageDraw.Draw(toile)
    dessin.rectangle([0, 0, largeur - 1, hauteur - 1], outline=GREY_LINE, width=2)

    marge = largeur + 34
    dessin.rectangle([largeur + 18, 0, largeur + CLE - 1, hauteur - 1],
                     fill=BLUE_BG, outline=GREY_LINE, width=2)
    dessin.text((marge, 34), titre, fill=NAVY, font=police(27), anchor="lm")
    dessin.line([(marge, 58), (largeur + CLE - 34, 58)], fill=AZURE, width=2)

    fonte_fr, fonte_en = police(21), police(23)
    for index, (terme, anglais) in enumerate(entrees):
        y = 92 + index * 62
        dessin.text((marge, y), terme, fill=(120, 130, 145), font=fonte_fr, anchor="lm")
        dessin.text((marge + 16, y + 27), anglais, fill=NAVY, font=fonte_en, anchor="lm")

    toile.save(SORTIE / sortie)
    print(f"wrote {SORTIE / sortie}  ({toile.size[0]}x{toile.size[1]})")


cle_anglaise(
    "questionnaire_screenshot",
    boite=(400, 340, 1500, 926),
    titre="Interface terms",
    entrees=[
        ("Comparaisons par paires (AHP)", "Pairwise comparisons (AHP)"),
        ("Impact operationnel", "Operational impact"),
        ("Fenetre temporelle", "Time window"),
        ("Dependances aval", "Downstream dependencies"),
        ("Recuperabilite", "Recoverability"),
        ("Importance egale", "Equal importance"),
        ("Curseur a gauche / a droite", "Slider left / right: which side dominates"),
    ],
    sortie="questionnaire_annotated.png",
)

cle_anglaise(
    "hebdo",
    boite=(400, 160, 1500, 900),
    titre="Interface terms",
    entrees=[
        ("Revue hebdomadaire", "Weekly review"),
        ("Noeud en revue", "Node under review"),
        ("Volet 1 - Evaluation AHP", "Panel 1: AHP assessment"),
        ("Volet 2 - KPIs de la semaine", "Panel 2: this week's indicators"),
        ("Volet 3 - Jalons", "Panel 3: milestone progress"),
        ("Volet 4 - Evenements & decision", "Panel 4: events and decision"),
        ("Cloture", "Close: commits as one signed transaction"),
    ],
    sortie="weekly_review_annotated.png",
)

cle_anglaise(
    "criticite",
    boite=(399, 2105, 1535, 2758),
    titre="Interface terms",
    entrees=[
        ("Criticite systematique", "Systematic criticality"),
        ("Pour chaque noeud actif", "For every active node of the project"),
        ("Analyser la criticite (top 15)", "Rank nodes by criticality"),
        ("Pire choc local par noeud", "Worst local shock, node by node"),
        ("dUr du client final si le noeud tombait",
         "Rise in the final customer's real urgency if this node failed"),
        ("Assemblage final", "Final assembly"),
        ("Nacelles & structures", "Nacelles and structures"),
        ("Propulsion electrique", "Electric propulsion"),
        ("Cellules de secours", "Backup cells"),
    ],
    sortie="criticality_annotated.png",
)
