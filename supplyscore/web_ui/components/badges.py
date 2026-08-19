"""Badges de statut hebdomadaire et de completude d'onboarding.

Les statuts hebdo arrivent en chaines (``"a_jour"`` / ``"en_retard"`` /
``"manquant"``) : cote services c'est un ``StrEnum``, volontairement PAS
importe ici (duck-typing - toute chaine, y compris un membre de StrEnum,
convient ; une valeur inconnue donne le badge gris " - ").

Piege Dash documente : une cellule de ``dash_table.DataTable`` n'accepte PAS
de composant (le rendu afficherait la representation texte du composant).
Pour les tableaux, utiliser :func:`texte_hebdo` (libelle brut dans la cellule)
combine a :func:`style_hebdo_conditionnel` (``style_data_conditional`` qui
colore la cellule selon ce texte). Le badge riche :func:`badge_hebdo` est
reserve aux cartes et listes.
"""

from __future__ import annotations

from dash import html

from supplyscore.web_ui.components.layout import COLORS, FONT_FAMILY

#: Style commun des pilules : fond pale, texte fonce, coins arrondis.
_PILL_BASE: dict[str, str] = {
    "display": "inline-block",
    "padding": "2px 10px",
    "borderRadius": "10px",
    "fontSize": "12px",
    "fontWeight": "600",
    "fontFamily": FONT_FAMILY,
    "whiteSpace": "nowrap",
}

#: Couples (fond pale, texte fonce) par teinte - les textes reprennent COLORS.
_HUES: dict[str, dict[str, str]] = {
    "ok": {"backgroundColor": "#e2f2e7", "color": COLORS["ok"]},
    "warn": {"backgroundColor": "#f8ecdb", "color": COLORS["warn"]},
    "alert": {"backgroundColor": "#fae5e3", "color": COLORS["alert"]},
    "muted": {"backgroundColor": "#ebeef1", "color": COLORS["muted"]},
}

#: Teinte associee a chaque statut hebdo connu (inconnu -> " muted ").
_STATUT_HUE: dict[str, str] = {
    "a_jour": "ok",
    "en_retard": "warn",
    "manquant": "alert",
}


def _pill(label: str, hue: str) -> html.Span:
    """Pilule coloree : libelle sur fond pale, texte fonce de la meme teinte."""
    return html.Span(label, style={**_PILL_BASE, **_HUES[hue]})


def texte_hebdo(statut: str, semaines_de_retard: int = 0) -> str:
    """Libelle texte brut d'un statut hebdo (cellules de DataTable).

    Une cellule de DataTable n'accepte pas de composant : ce texte y est
    inscrit tel quel, et :func:`style_hebdo_conditionnel` colore la cellule
    selon sa valeur. Meme libelle que :func:`badge_hebdo`.

    Args:
        statut: ``"a_jour"`` / ``"en_retard"`` / ``"manquant"`` (chaine ou
            membre de StrEnum) ; toute autre valeur donne " - ".
        semaines_de_retard: nombre de semaines de retard, repris dans le
            libelle " En retard (n sem.) ".
    """
    if statut == "a_jour":
        return "À jour"
    if statut == "en_retard":
        return f"En retard ({semaines_de_retard} sem.)"
    if statut == "manquant":
        return "Manquant"
    return "—"


def badge_hebdo(statut: str, semaines_de_retard: int = 0) -> html.Span:
    """Badge pilule d'un statut hebdo (cartes et listes, PAS les DataTable).

    Vert " A jour ", orange " En retard (n sem.) ", rouge " Manquant " ;
    statut inconnu -> badge gris " - ".

    Args:
        statut: ``"a_jour"`` / ``"en_retard"`` / ``"manquant"`` (chaine ou
            membre de StrEnum).
        semaines_de_retard: nombre de semaines de retard (statut
            ``"en_retard"``).
    """
    return _pill(texte_hebdo(statut, semaines_de_retard), _STATUT_HUE.get(statut, "muted"))


def completeness_badge(done: int, total: int) -> html.Span:
    """Badge " x/4 sections " : vert si complet, orange sinon (wizard E5).

    Args:
        done: nombre de sections validees.
        total: nombre total de sections attendues.
    """
    return _pill(f"{done}/{total} sections", "ok" if done >= total else "warn")


def draft_badge() -> html.Span:
    """Badge gris " Incomplet " (noeud en cours d'onboarding)."""
    return _pill("Incomplet", "muted")


def style_hebdo_conditionnel(column_id: str) -> list[dict]:
    """Regles ``style_data_conditional`` pour une colonne de statuts hebdo.

    Trois regles colorent la cellule selon le texte produit par
    :func:`texte_hebdo` : vert si le libelle commence par " A jour ", orange
    par " En retard ", rouge par " Manquant ". La grammaire ``filter_query``
    de Dash n'a pas d'operateur " commence par " generique : on utilise
    ``contains``, sans risque de collision (aucun libelle n'en contient un
    autre).

    Args:
        column_id: identifiant de la colonne DataTable contenant les libelles.
    """
    prefixes = [("À jour", "ok"), ("En retard", "warn"), ("Manquant", "alert")]
    return [
        {
            "if": {
                "column_id": column_id,
                "filter_query": f'{{{column_id}}} contains "{prefix}"',
            },
            "backgroundColor": _HUES[hue]["backgroundColor"],
            "color": _HUES[hue]["color"],
            "fontWeight": "600",
        }
        for prefix, hue in prefixes
    ]
