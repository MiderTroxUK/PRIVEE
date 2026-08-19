"""UI web Dash de SupplyScore.

L'instance unique de :class:`SupplyScoreService` partagee par les callbacks
est geree ici via un setter/getter : RIEN n'est instancie a l'import du
package (pas de creation de ``data_store`` tant que ``create_app`` n'est
pas appele).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - uniquement pour les annotations
    from supplyscore.services.orchestrator import SupplyScoreService

_service: SupplyScoreService | None = None


def set_service(service: SupplyScoreService | None) -> None:
    """Enregistre l'instance de service partagee par les callbacks."""
    global _service
    _service = service


def get_service() -> SupplyScoreService:
    """Retourne le service partage.

    Raises:
        RuntimeError: si aucun service n'a ete initialise (appeler
            ``create_app(...)`` d'abord).
    """
    if _service is None:
        raise RuntimeError(
            "Aucun service SupplyScore initialisé : appelez create_app(...) d'abord."
        )
    return _service
