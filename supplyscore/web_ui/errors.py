"""Garde-fous d'erreur de l'UI web : aucun traceback brut cote utilisateur.

Deux mecanismes complementaires (Lot 16.1) :

* :func:`protege_callback` - decorateur qui attrape toute exception d'un
  callback Dash (sauf :class:`~dash.exceptions.PreventUpdate`, flux normal),
  journalise la trace complete sur le logger ``supplyscore.web_ui`` et
  retourne un bandeau d'erreur francais DIMENSIONNE au nombre d'Outputs du
  callback - sinon Dash leverait une seconde erreur (mauvais nombre de
  valeurs) qui masquerait la premiere.
* :func:`proteger_app` - applique la protection a TOUTE l'application sans
  toucher aux pages : ``app.callback`` est remplace par une version qui
  compte les ``Output`` au point d'enregistrement (seul endroit ou ils sont
  connus) et decore automatiquement chaque fonction enregistree ensuite.

Heuristique de repli documentee : seul le PREMIER Output de propriete
``children`` recoit le bandeau ; tous les autres recoivent
``dash.no_update`` (une figure ou un store qui recevrait un ``html.Div``
casserait le rendu cote client). Sans Output ``children``, tout est
``no_update`` et le log reste la seule trace.
"""

from __future__ import annotations

import functools
import logging
import weakref
from collections.abc import Callable, Sequence
from typing import Any

import dash
from dash import html
from dash.dependencies import Output
from dash.exceptions import PreventUpdate

from supplyscore.web_ui.components.layout import COLORS

#: Logger dedie aux erreurs de l'UI web (enfant du logger ``supplyscore``, donc journalise dans ``logs/supplyscore.log`` via ``configure_logging``).
_LOGGER = logging.getLogger("supplyscore.web_ui")

#: Attribut pose sur l'application Dash : compteur de callbacks proteges.
_ATTR_COMPTEUR = "_supplyscore_callbacks_proteges"
#: Attribut pose sur l'application Dash : garde d'idempotence de proteger_app.
_ATTR_ACTIF = "_supplyscore_protection_active"

#: Registre (faible) des fonctions enveloppees par :func:`protege_callback`, pour l'introspection des tests sans poser d'attribut sur les fonctions.
_PROTEGES: weakref.WeakSet[Callable[..., Any]] = weakref.WeakSet()

#: Style du bandeau d'erreur (alerte rouge sur fond clair, lisible partout).
ERROR_STYLE = {
    "backgroundColor": "#fdecea",
    "border": f"1px solid {COLORS['alert']}",
    "borderRadius": "6px",
    "color": COLORS["alert"],
    "padding": "12px 16px",
    "margin": "12px 0",
    "fontSize": "14px",
    "fontWeight": "600",
}


def composant_erreur(exc: BaseException) -> html.Div:
    """Construit le bandeau d'erreur francais affiche a la place du contenu.

    Args:
        exc: exception attrapee ; seul le NOM de son type est montre a
            l'utilisateur (jamais le message brut ni la trace, qui partent
            dans ``logs/supplyscore.log``).

    Returns:
        Un ``html.Div`` style alerte, message entierement en francais.
    """
    return html.Div(
        f"⚠ Une erreur est survenue : {type(exc).__name__}. Consultez logs/supplyscore.log.",
        style=ERROR_STYLE,
        className="supplyscore-erreur",
    )


def _valeurs_de_repli(
    exc: BaseException,
    sorties: Sequence[Output] | None,
    multi: bool,
) -> Any:
    """Valeurs de retour dimensionnees aux Outputs du callback en echec.

    Args:
        exc: exception attrapee (pour le bandeau).
        sorties: ``Output`` du callback dans l'ordre d'enregistrement ;
            ``None`` signifie " un Output ``children`` unique " (cas du
            decorateur applique a la main, sans point d'enregistrement).
        multi: True si Dash attend une sequence de valeurs (plusieurs
            Outputs, ou un Output unique passe DANS une liste).

    Returns:
        Le bandeau seul (Output unique non-liste), ou un tuple de la taille
        exacte des sorties : bandeau sur le premier Output ``children``,
        ``dash.no_update`` partout ailleurs. Sans sortie ``children``,
        tout est ``no_update`` (le log est alors la seule trace).
    """
    if sorties is None:
        return composant_erreur(exc)
    if not sorties:  # callback sans Output (autorise par Dash >= 2.17)
        return dash.no_update
    valeurs: list[Any] = [dash.no_update] * len(sorties)
    for i, sortie in enumerate(sorties):
        if sortie.component_property == "children":
            valeurs[i] = composant_erreur(exc)
            break
    if len(valeurs) == 1 and not multi:
        return valeurs[0]
    return tuple(valeurs)


def protege_callback(
    fn: Callable[..., Any],
    sorties: Sequence[Output] | None = None,
    multi: bool = False,
) -> Callable[..., Any]:
    """Enveloppe un callback : toute exception devient un message francais.

    ``PreventUpdate`` traverse tel quel (flux normal de Dash, PAS une
    erreur). Toute autre exception est journalisee avec sa trace complete
    (logger ``supplyscore.web_ui``) et remplacee par les valeurs de repli
    de :func:`_valeurs_de_repli`, dimensionnees aux ``sorties``.

    Le nombre d'Outputs n'etant pas introspectable depuis ``fn`` seule,
    ``sorties``/``multi`` sont fournis par le point d'enregistrement
    (:func:`proteger_app`). Sans eux, le repli suppose un Output
    ``children`` unique.

    Args:
        fn: la fonction de callback a proteger.
        sorties: ``Output`` du callback (ordre d'enregistrement), ou None.
        multi: True si Dash attend une sequence de valeurs de retour.

    Returns:
        La fonction enveloppee (memes nom/doc via ``functools.wraps``).
    """

    @functools.wraps(fn)
    def enveloppe(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except PreventUpdate:
            raise
        except Exception as exc:
            _LOGGER.error(
                "Erreur non gérée dans le callback « %s » : %s",
                getattr(fn, "__name__", repr(fn)),
                exc,
                exc_info=True,
            )
            return _valeurs_de_repli(exc, sorties, multi)

    _PROTEGES.add(enveloppe)
    return enveloppe


def est_protege(fn: Callable[..., Any]) -> bool:
    """True si ``fn`` est une enveloppe produite par :func:`protege_callback`."""
    return fn in _PROTEGES


def _extraire_sorties(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[list[Output], bool]:
    """Extrait les ``Output`` des arguments d'un appel ``app.callback(...)``.

    Couvre les formes utilisees par Dash : instances ``Output`` passees en
    positionnel, listes/tuples d'``Output`` (positionnels ou via le mot-cle
    ``output=``). Les groupements imbriques (dicts) ne sont pas utilises
    dans ce projet et ne sont pas couverts.

    Args:
        args: arguments positionnels d'``app.callback``.
        kwargs: arguments nommes d'``app.callback``.

    Returns:
        ``(sorties, multi)`` - la liste ordonnee des Outputs et le drapeau
        " Dash attend une sequence " (plusieurs Outputs, ou Output(s) en
        liste, y compris une liste d'UN seul Output).
    """
    sorties: list[Output] = []
    multi = False
    candidats: list[Any] = list(args)
    if "output" in kwargs:
        candidats.insert(0, kwargs["output"])
    for candidat in candidats:
        if isinstance(candidat, Output):
            sorties.append(candidat)
        elif isinstance(candidat, list | tuple):
            elements = [el for el in candidat if isinstance(el, Output)]
            if elements:
                multi = True
                sorties.extend(elements)
    if len(sorties) > 1:
        multi = True
    return sorties, multi


def proteger_app(app: dash.Dash) -> int:
    """Protege automatiquement tout callback enregistre APRES cet appel.

    Remplace ``app.callback`` par une version qui (1) compte les ``Output``
    dans les arguments d'enregistrement, (2) enregistre la fonction
    enveloppee par :func:`protege_callback` dimensionne. A appeler dans
    ``create_app`` AVANT tout ``register_callbacks`` (routeur compris) :
    aucune page n'a besoin d'etre modifiee.

    Idempotent : un second appel sur la meme application ne re-enveloppe
    rien. Le nombre de callbacks effectivement proteges est consultable via
    :func:`nombre_callbacks_proteges` (rien d'utile n'est connu au moment
    de CET appel, d'ou le retour fixe).

    Args:
        app: l'application Dash fraichement creee.

    Returns:
        0 (toujours) - les enregistrements n'ont pas encore eu lieu.
    """
    if getattr(app, _ATTR_ACTIF, False):
        return 0
    callback_original = app.callback
    setattr(app, _ATTR_COMPTEUR, 0)

    def callback_protege(*args: Any, **kwargs: Any) -> Callable[..., Any]:
        sorties, multi = _extraire_sorties(args, kwargs)
        enregistrer = callback_original(*args, **kwargs)

        def decorateur(fn: Callable[..., Any]) -> Callable[..., Any]:
            fn_protegee = protege_callback(fn, sorties=sorties, multi=multi)
            enregistrer(fn_protegee)
            setattr(app, _ATTR_COMPTEUR, getattr(app, _ATTR_COMPTEUR, 0) + 1)
            return fn_protegee

        return decorateur

    app.callback = callback_protege  # type: ignore[method-assign]
    setattr(app, _ATTR_ACTIF, True)
    return 0


def nombre_callbacks_proteges(app: dash.Dash) -> int:
    """Nombre de callbacks enregistres sous protection sur ``app``.

    Args:
        app: application passee a :func:`proteger_app` au prealable.

    Returns:
        Le compteur d'enregistrements proteges (0 si :func:`proteger_app`
        n'a jamais ete appelee sur cette application).
    """
    return int(getattr(app, _ATTR_COMPTEUR, 0))
