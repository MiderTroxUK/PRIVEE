"""Relabel the equipped-facade evidence in English.

The pipeline writes its banner in French, because it is a French research
tool, and it pads each strip to a common width with black. In an English
thesis the banner reads as a foreign body and the padding wastes half the
figure. This script keeps the imagery byte for byte, trims the padding, and
re-letters the banner in the document's language and palette. The site names
are the real ones and are left as they are.

    C:\\PRIVEE\\AZURE\\.venv\\Scripts\\python.exe make_facade_proof.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

IMAGES = Path(__file__).resolve().parents[1].parent / "Images" / "5.Volume"
SOURCE = IMAGES / "preuve_facade_sans_camion.png"
SORTIE = IMAGES / "facade_proof_en.png"

NAVY = (4, 57, 98)
GREY_LINE = (205, 206, 218)
WHITE = (255, 255, 255)

#: Les trois bandeaux, dans l'ordre, traduits.
BANDEAUX = [
    "DERET LOGISTIQUE (Chataigniers), edge 2, 135 m \u2014 no trailer detected",
    "ENTREPOTS CLESUD II (G9), edge 12, 105 m \u2014 no trailer detected",
    "DERET LOGISTIQUE (Vergers), edge 2, 15 m \u2014 no trailer detected",
]

HAUTEUR_BANDEAU = 26
ECART = 10

POLICES = (
    Path("C:/Windows/Fonts"),
    Path("C:/texlive/2026/texmf-dist/fonts/truetype/public/carlito"),
)


def police(taille: int) -> ImageFont.FreeTypeFont:
    for nom in ("Carlito-Regular.ttf", "calibri.ttf", "arial.ttf", "DejaVuSans.ttf"):
        for base in POLICES:
            if (base / nom).is_file():
                return ImageFont.truetype(str(base / nom), taille)
    return ImageFont.load_default()


def lignes_noires(image: Image.Image) -> list[bool]:
    """Vrai pour chaque ligne entierement tres sombre : bandeau ou remplissage."""
    gris = image.convert("L")
    largeur, hauteur = gris.size
    plat = list(gris.getdata())
    return [max(plat[y * largeur:(y + 1) * largeur]) < 90 for y in range(hauteur)]


def bandes(image: Image.Image) -> list[tuple[int, int]]:
    """Les trois bandes d'imagerie, entre les bandeaux noirs."""
    noires = lignes_noires(image)
    sortie, debut = [], None
    for y, noire in enumerate(noires + [True]):
        if not noire and debut is None:
            debut = y
        elif noire and debut is not None:
            if y - debut > 40:
                sortie.append((debut, y))
            debut = None
    return sortie


def largeur_utile(image: Image.Image, haut: int, bas: int) -> int:
    """Derniere colonne non noire de la bande : le reste est du remplissage."""
    gris = image.convert("L").crop((0, haut, image.width, bas))
    plat = list(gris.getdata())
    largeur = gris.width
    for x in range(largeur - 1, -1, -1):
        if max(plat[y * largeur + x] for y in range(gris.height)) >= 90:
            return x + 1
    return largeur


def composer() -> None:
    source = Image.open(SOURCE)
    zones = bandes(source)
    if len(zones) != 3:
        raise SystemExit(f"trois bandes attendues, {len(zones)} trouvees")

    morceaux = [(source.crop((0, h, largeur_utile(source, h, b), b)), texte)
                for (h, b), texte in zip(zones, BANDEAUX)]

    largeur = max(m.width for m, _ in morceaux)
    hauteur = sum(m.height + HAUTEUR_BANDEAU for m, _ in morceaux) + ECART * 2
    toile = Image.new("RGB", (largeur, hauteur), WHITE)
    dessin = ImageDraw.Draw(toile)
    fonte = police(15)

    y = 0
    for morceau, texte in morceaux:
        # Une bande deux fois plus etroite que la toile porte son intitule a
        # cote plutot qu'au-dessus : sinon les trois quarts de sa ligne sont
        # du blanc.
        a_cote = morceau.width * 2 < largeur
        if not a_cote:
            dessin.text((2, y + HAUTEUR_BANDEAU // 2), texte, fill=NAVY, font=fonte,
                        anchor="lm")
            y += HAUTEUR_BANDEAU
        toile.paste(morceau, (0, y))
        dessin.rectangle([0, y, morceau.width - 1, y + morceau.height - 1],
                         outline=GREY_LINE, width=1)
        if a_cote:
            dessin.text((morceau.width + 14, y + morceau.height // 2), texte,
                        fill=NAVY, font=fonte, anchor="lm")
        y += morceau.height + ECART

    toile.save(SORTIE)
    print(f"-> {SORTIE}  ({toile.size[0]}x{toile.size[1]})")


if __name__ == "__main__":
    composer()
