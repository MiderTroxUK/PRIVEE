"""Contraintes de bornes des KPIs — table de métadonnées unique.

Source de vérité consommée à la fois par la validation (légère ici, exhaustive
en phase E10) et par l'UI (bornes min/max des champs, unités affichées) afin
de ne jamais diverger.

Les chemins de KPI sont qualifiés « bloc.champ » (ex : ``risk.failure_probability``),
alignés sur :class:`supplyscore.domain.models.KPIBundle`.
"""

from __future__ import annotations

import math
from typing import Any

#: (min, max, unité) par chemin de KPI — None = pas de borne de ce côté.
KPI_CONSTRAINTS: dict[str, tuple[float | None, float | None, str]] = {
    # Réseau
    "network.distance_km": (0.0, None, "km"),
    "network.demand": (0.0, None, "unité/temps"),
    # Inventaire
    "inventory.max_volume_m3": (0.0, None, "m³"),
    "inventory.max_weight_kg": (0.0, None, "kg"),
    "inventory.current_volume_m3": (0.0, None, "m³"),
    "inventory.current_weight_kg": (0.0, None, "kg"),
    "inventory.flow_rate": (0.0, None, "unité/temps"),
    # Temps
    "time.speed_kmh": (0.0, None, "km/h"),
    "time.distance_range_km": (0.0, None, "km"),
    "time.time_range_h": (0.0, None, "h"),
    "time.refuel_time_h": (0.0, None, "h"),
    "time.lead_time_h": (0.0, None, "h"),
    "time.lead_time_std_h": (0.0, None, "h"),
    "time.lead_time_min_h": (0.0, None, "h"),  # distribution triangulaire (Monte Carlo E13)
    "time.lead_time_mode_h": (0.0, None, "h"),  # distribution triangulaire (Monte Carlo E13)
    "time.lead_time_max_h": (0.0, None, "h"),  # distribution triangulaire (Monte Carlo E13)
    "time.delay_h": (0.0, None, "h"),
    "time.deadline_h": (0.0, None, "h"),
    # Coût
    "cost.product_cost": (0.0, None, "€"),
    "cost.tariff": (1e-9, None, "multiplicateur (1 = neutre)"),
    "cost.nominal_op_cost": (0.0, None, "€"),
    "cost.op_cost": (0.0, None, "€/temps"),
    "cost.fuel_cost": (0.0, None, "€"),
    "cost.risk_cost": (0.0, None, "€"),
    "cost.storage_cost": (0.0, None, "€"),
    # CO2
    "co2.fuel_emission_g_km": (0.0, None, "gCO2/km"),
    "co2.op_emission_g_h": (0.0, None, "gCO2/h"),
    "co2.energy_mix_g_h": (0.0, None, "gCO2/h"),
    "co2.co2_target_g_h": (0.0, None, "gCO2/h"),
    "co2.co2_max_g_h": (0.0, None, "gCO2/h"),
    # OEE
    "oee.production_time_h": (0.0, None, "h"),
    "oee.operating_time_h": (0.0, None, "h"),
    "oee.availability": (0.0, 1.0, "ratio"),
    "oee.performance": (0.0, 1.0, "ratio"),
    "oee.quality": (0.0, 1.0, "ratio"),
    # Risque
    "risk.failure_probability": (0.0, 1.0, "probabilité"),
    "risk.recovery_time_h": (0.0, None, "h"),
    "risk.severity": (0.0, 1.0, "ratio"),
    "risk.cost_volatility": (0.0, 1.0, "ratio"),
    "risk.env_exposure": (0.0, 1.0, "ratio"),
    "risk.political_risk": (0.0, 1.0, "ratio"),
}


def validate_kpi_value(kpi_path: str, value: Any) -> str | None:
    """Valide une valeur de KPI contre ses bornes.

    Retourne un message d'erreur en français, ou None si la valeur est
    acceptable. ``None`` (KPI non renseigné) est toujours accepté.
    """
    if value is None:
        return None
    if kpi_path not in KPI_CONSTRAINTS:
        return f"KPI inconnu : {kpi_path}"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{kpi_path} : valeur non numérique ({value!r})"
    if not math.isfinite(number):
        return f"{kpi_path} : valeur non finie ({value!r}) — NaN et ±inf sont rejetés"
    lo, hi, unit = KPI_CONSTRAINTS[kpi_path]
    if lo is not None and number < lo:
        return f"{kpi_path} : {number} < minimum {lo} ({unit})"
    if hi is not None and number > hi:
        return f"{kpi_path} : {number} > maximum {hi} ({unit})"
    return None


def clamp_kpi_value(kpi_path: str, value: float) -> float:
    """Ramène une valeur dans les bornes de son KPI (pour les impacts calibrés)."""
    lo, hi, _unit = KPI_CONSTRAINTS.get(kpi_path, (None, None, ""))
    if lo is not None:
        value = max(value, lo)
    if hi is not None:
        value = min(value, hi)
    return value


def kpi_unit(kpi_path: str) -> str:
    """Unité d'affichage d'un KPI (chaîne vide si inconnu)."""
    entry = KPI_CONSTRAINTS.get(kpi_path)
    return entry[2] if entry is not None else ""
