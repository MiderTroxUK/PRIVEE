"""Cœur mathématique de SupplyScore : AHP (Ud), modèle Ur et adéquation."""

from supplyscore.core.adequation import AdequationEngine
from supplyscore.core.ahp import (
    CONSISTENCY_THRESHOLD,
    CRITERIA,
    AHPResult,
    bipolar_to_saaty,
    build_matrix,
    compute_ud,
    consistency_ratio,
    priority_vector,
    run_ahp,
    score_6_to_9,
    ud_smoothed,
)
from supplyscore.core.ur_model import (
    BLOCKS,
    UrModel,
    filtered_error,
    ud_hyperbolic,
    ur_singularity,
)

__all__ = [
    # AHP — urgence déclarée
    "CRITERIA",
    "CONSISTENCY_THRESHOLD",
    "AHPResult",
    "build_matrix",
    "priority_vector",
    "consistency_ratio",
    "run_ahp",
    "compute_ud",
    "bipolar_to_saaty",
    "score_6_to_9",
    "ud_smoothed",
    # Ur — urgence réelle
    "BLOCKS",
    "UrModel",
    "ur_singularity",
    "ud_hyperbolic",
    "filtered_error",
    # Adéquation
    "AdequationEngine",
]
