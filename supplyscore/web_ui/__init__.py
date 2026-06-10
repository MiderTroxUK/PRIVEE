"""UI web Dash de SupplyScore.

L'instance unique de :class:`SupplyScoreService` partagée par les callbacks
est gérée ici via un setter/getter : RIEN n'est instancié à l'import du
package (pas de création de ``data_store`` tant que ``create_app`` n'est
pas appelé).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - uniquement pour les annotations
    from supplyscore.services.orchestrator import SupplyScoreService

_service: SupplyScoreService | None = None


def set_service(service: SupplyScoreService | None) -> None:
    """Enregistre l'instance de service partagée par les callbacks."""
    global _service
    _service = service


def get_service() -> SupplyScoreService:
    """Retourne le service partagé.

    Raises:
        RuntimeError: si aucun service n'a été initialisé (appeler
            ``create_app(...)`` d'abord).
    """
    if _service is None:
        raise RuntimeError(
            "Aucun service SupplyScore initialisé : appelez create_app(...) d'abord."
        )
    return _service
