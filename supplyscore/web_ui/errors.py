"""Garde-fous d'erreur de l'UI web : aucun traceback brut côté utilisateur.

Deux mécanismes complémentaires (Lot 16.1) :

* :func:`protege_callback` — décorateur qui attrape toute exception d'un
  callback Dash (sauf :class:`~dash.exceptions.PreventUpdate`, flux normal),
  journalise la trace complète sur le logger ``supplyscore.web_ui`` et
  retourne un bandeau d'erreur français DIMENSIONNÉ au nombre d'Outputs du
  callback — sinon Dash lèverait une seconde erreur (mauvais nombre de
  valeurs) qui masquerait la première.
* :func:`proteger_app` — applique la protection à TOUTE l'application sans
  toucher aux pages : ``app.callback`` est remplacé par une version qui
  compte les ``Output`` au point d'enregistrement (seul endroit où ils sont
  connus) et décore automatiquement chaque fonction enregistrée ensuite.

Heuristique de repli documentée : seul le PREMIER Output de propriété
``children`` reçoit le bandeau ; tous les autres reçoivent
``dash.no_update`` (une figure ou un store qui recevrait un ``html.Div``
casserait le rendu côté client). Sans Output ``children``, tout est
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

#: Logger dédié aux erreurs de l'UI web (enfant du logger ``supplyscore``,
#: donc journalisé dans ``logs/supplyscore.log`` via ``configure_logging``).
_LOGGER = logging.getLogger("supplyscore.web_ui")

#: Attribut posé sur l'application Dash : compteur de callbacks protégés.
_ATTR_COMPTEUR = "_supplyscore_callbacks_proteges"
#: Attribut posé sur l'application Dash : garde d'idempotence de proteger_app.
_ATTR_ACTIF = "_supplyscore_protection_active"

#: Registre (faible) des fonctions enveloppées par :func:`protege_callback`,
#: pour l'introspection des tests sans poser d'attribut sur les fonctions.
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
    """Construit le bandeau d'erreur français affiché à la place du contenu.

    Args:
        exc: exception attrapée ; seul le NOM de son type est montré à
            l'utilisateur (jamais le message brut ni la trace, qui partent
            dans ``logs/supplyscore.log``).

    Returns:
        Un ``html.Div`` stylé alerte, message entièrement en français.
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
    """Valeurs de retour dimensionnées aux Outputs du callback en échec.

    Args:
        exc: exception attrapée (pour le bandeau).
        sorties: ``Output`` du callback dans l'ordre d'enregistrement ;
            ``None`` signifie « un Output ``children`` unique » (cas du
            décorateur appliqué à la main, sans point d'enregistrement).
        multi: True si Dash attend une séquence de valeurs (plusieurs
            Outputs, ou un Output unique passé DANS une liste).

    Returns:
        Le bandeau seul (Output unique non-liste), ou un tuple de la taille
        exacte des sorties : bandeau sur le premier Output ``children``,
        ``dash.no_update`` partout ailleurs. Sans sortie ``children``,
        tout est ``no_update`` (le log est alors la seule trace).
    """
    if sorties is None:
        return composant_erreur(exc)
    if not sorties:  # callback sans Output (autorisé par Dash >= 2.17)
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
    """Enveloppe un callback : toute exception devient un message français.

    ``PreventUpdate`` traverse tel quel (flux normal de Dash, PAS une
    erreur). Toute autre exception est journalisée avec sa trace complète
    (logger ``supplyscore.web_ui``) et remplacée par les valeurs de repli
    de :func:`_valeurs_de_repli`, dimensionnées aux ``sorties``.

    Le nombre d'Outputs n'étant pas introspectable depuis ``fn`` seule,
    ``sorties``/``multi`` sont fournis par le point d'enregistrement
    (:func:`proteger_app`). Sans eux, le repli suppose un Output
    ``children`` unique.

    Args:
        fn: la fonction de callback à protéger.
        sorties: ``Output`` du callback (ordre d'enregistrement), ou None.
        multi: True si Dash attend une séquence de valeurs de retour.

    Returns:
        La fonction enveloppée (mêmes nom/doc via ``functools.wraps``).
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

    Couvre les formes utilisées par Dash : instances ``Output`` passées en
    positionnel, listes/tuples d'``Output`` (positionnels ou via le mot-clé
    ``output=``). Les groupements imbriqués (dicts) ne sont pas utilisés
    dans ce projet et ne sont pas couverts.

    Args:
        args: arguments positionnels d'``app.callback``.
        kwargs: arguments nommés d'``app.callback``.

    Returns:
        ``(sorties, multi)`` — la liste ordonnée des Outputs et le drapeau
        « Dash attend une séquence » (plusieurs Outputs, ou Output(s) en
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
    """Protège automatiquement tout callback enregistré APRÈS cet appel.

    Remplace ``app.callback`` par une version qui (1) compte les ``Output``
    dans les arguments d'enregistrement, (2) enregistre la fonction
    enveloppée par :func:`protege_callback` dimensionné. À appeler dans
    ``create_app`` AVANT tout ``register_callbacks`` (routeur compris) :
    aucune page n'a besoin d'être modifiée.

    Idempotent : un second appel sur la même application ne ré-enveloppe
    rien. Le nombre de callbacks effectivement protégés est consultable via
    :func:`nombre_callbacks_proteges` (rien d'utile n'est connu au moment
    de CET appel, d'où le retour fixe).

    Args:
        app: l'application Dash fraîchement créée.

    Returns:
        0 (toujours) — les enregistrements n'ont pas encore eu lieu.
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
    """Nombre de callbacks enregistrés sous protection sur ``app``.

    Args:
        app: application passée à :func:`proteger_app` au préalable.

    Returns:
        Le compteur d'enregistrements protégés (0 si :func:`proteger_app`
        n'a jamais été appelée sur cette application).
    """
    return int(getattr(app, _ATTR_COMPTEUR, 0))
