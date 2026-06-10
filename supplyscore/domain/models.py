"""Modèles de domaine — contrat partagé entre core math, graphe, persistance et UI.

Conventions :
- Toutes les urgences (Ud, Ur, locales ou propagées) vivent dans [0, 1]
  (Ur peut dépasser 1.0 pour une tâche en retard, voir core.ur_model).
- L'adéquation A vit dans [0, 100].
- Les KPIs optionnels valent None quand le client ne les a pas fournis ;
  le modèle Ur ignore alors le bloc correspondant.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from enum import StrEnum


class NodeKind(StrEnum):
    """Nature d'un élément du réseau : nœud physique ou arc de transport."""

    NODE = "node"  # entrepôt, usine, atelier, client...
    ARC = "arc"  # transport (camion, bateau...) — porté par SupplyArc


class TaskStatus(StrEnum):
    """Statut du cycle de vie d'une tâche ou d'un nœud."""

    ACTIVE = "active"
    DONE = "done"
    ABANDONED = "abandoned"


# --- Blocs KPI (cf. dictionnaire de données client) -------------------------


@dataclass
class NetworkKPIs:
    """KPIs réseau : produit, distance et demande."""

    product: str | None = None
    distance_km: float | None = None
    demand: float | None = None  # unit/time


@dataclass
class InventoryKPIs:
    """KPIs de stock : capacités maximales, niveaux courants et débit."""

    max_volume_m3: float | None = None
    max_weight_kg: float | None = None
    current_volume_m3: float | None = None
    current_weight_kg: float | None = None
    flow_rate: float | None = None  # unit/time

    @property
    def remaining_volume_m3(self) -> float | None:
        """Volume restant disponible (m³), ou None si non calculable."""
        if self.max_volume_m3 is None or self.current_volume_m3 is None:
            return None
        return max(self.max_volume_m3 - self.current_volume_m3, 0.0)

    @property
    def remaining_weight_kg(self) -> float | None:
        """Masse restante disponible (kg), ou None si non calculable."""
        if self.max_weight_kg is None or self.current_weight_kg is None:
            return None
        return max(self.max_weight_kg - self.current_weight_kg, 0.0)


@dataclass
class TimeKPIs:
    """KPIs temporels : vitesse, autonomie, lead time et échéance."""

    speed_kmh: float | None = None
    distance_range_km: float | None = None
    time_range_h: float | None = None
    refuel_time_h: float | None = None
    lead_time_h: float | None = None
    lead_time_std_h: float | None = None  # incertitude du lead time (loi normale)
    delay_h: float | None = None  # extension en cas de risque
    deadline_h: float | None = None  # échéance d_i (heures depuis t0 projet)


@dataclass
class CostKPIs:
    """KPIs de coût : produit, tarif, opérations, carburant, risque et stockage."""

    product_cost: float | None = None
    tariff: float | None = None  # multiplicateur sur le coût produit
    nominal_op_cost: float | None = None
    op_cost: float | None = None
    fuel_cost: float | None = None
    risk_cost: float | None = None
    storage_cost: float | None = None


@dataclass
class CO2KPIs:
    """KPIs d'émissions CO2 : carburant, opérations, mix énergétique et cibles."""

    fuel_emission_g_km: float | None = None
    op_emission_g_h: float | None = None
    energy_mix_g_h: float | None = None
    co2_target_g_h: float | None = None
    co2_max_g_h: float | None = None

    @property
    def total_g_h(self) -> float | None:
        """Émissions horaires totales (g/h), ou None si aucune composante fournie."""
        parts = [v for v in (self.op_emission_g_h, self.energy_mix_g_h) if v is not None]
        return sum(parts) if parts else None


@dataclass
class OEEKPIs:
    """KPIs de rendement synthétique (OEE) : disponibilité, performance et qualité."""

    production_time_h: float | None = None
    operating_time_h: float | None = None
    availability: float | None = None  # [0, 1]
    performance: float | None = None  # [0, 1]
    quality: float | None = None  # [0, 1]

    @property
    def oee(self) -> float | None:
        """Taux de rendement synthétique (produit des trois composantes), ou None."""
        if self.availability is None or self.performance is None or self.quality is None:
            return None
        return self.availability * self.performance * self.quality


@dataclass
class RiskKPIs:
    """KPIs de risque : défaillance, récupération, sévérité et expositions."""

    failure_probability: float | None = None  # %/time, dans [0, 1]
    recovery_time_h: float | None = None
    severity: float | None = None  # [0, 1]
    cost_volatility: float | None = None  # [0, 1]
    env_exposure: float | None = None  # [0, 1]
    political_risk: float | None = None  # [0, 1]


@dataclass
class KPIBundle:
    """Regroupe tous les blocs KPI d'un nœud ou d'un arc."""

    network: NetworkKPIs = field(default_factory=NetworkKPIs)
    inventory: InventoryKPIs = field(default_factory=InventoryKPIs)
    time: TimeKPIs = field(default_factory=TimeKPIs)
    cost: CostKPIs = field(default_factory=CostKPIs)
    co2: CO2KPIs = field(default_factory=CO2KPIs)
    oee: OEEKPIs = field(default_factory=OEEKPIs)
    risk: RiskKPIs = field(default_factory=RiskKPIs)


# --- Urgences ----------------------------------------------------------------


@dataclass
class UrgencyState:
    """État d'urgence d'un nœud à une date t."""

    ud_local: float | None = None  # questionnaire humain
    ur_local: float | None = None  # KPIs
    ud: float | None = None  # propagé (descendant, rang 0 -> N)
    ur: float | None = None  # propagé (montant, rang N -> 0)
    adequation: float | None = None  # [0, 100]
    false_urgency: float | None = None  # F = [Ud - Ur]+
    hidden_risk: float | None = None  # H = [Ur - Ud]+
    timestamp: float = field(default_factory=_time.time)


# --- Graphe ------------------------------------------------------------------


class ArcKind(StrEnum):
    """Nature d'un arc : nominal (flux réel) ou backup (secours, purement visuel)."""

    NOMINAL = "nominal"
    BACKUP = "backup"


@dataclass
class SupplyNode:
    """Nœud du réseau logistique (entrepôt, usine, atelier, client...)."""

    id: str
    name: str
    label: str = "Workshop"  # Warehouse, Factory, Workshop, Client...
    kind: NodeKind = NodeKind.NODE
    rank: int = 0  # 0 = client final, N = fournisseur profond
    project_id: str | None = None
    location: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: TaskStatus = TaskStatus.ACTIVE
    kpis: KPIBundle = field(default_factory=KPIBundle)
    urgency: UrgencyState = field(default_factory=UrgencyState)
    tags: list[str] = field(default_factory=list)  # ids de tags (domain.tags)
    onboarding_state: str = "complete"  # "draft" tant que le wizard n'est pas fini


@dataclass
class SupplyArc:
    """Arête orientée fournisseur -> client (j alimente i)."""

    source_id: str  # fournisseur (rang r+1)
    target_id: str  # client (rang r)
    label: str = "Truck"
    gamma: float = 0.5  # intensité de dépendance Ud (descendante)
    beta: float = 0.5  # coefficient de propagation Ur (montante)
    delta: float = 1.0  # criticité pour la propagation de choc
    kind_arc: ArcKind = ArcKind.NOMINAL  # backup = inerte dans tous les calculs
    kpis: KPIBundle = field(default_factory=KPIBundle)

    @property
    def id(self) -> str:
        """Identifiant dérivé de l'arc, au format ``source_id->target_id``."""
        return f"{self.source_id}->{self.target_id}"


# --- Projet / évaluation -------------------------------------------------------


@dataclass
class Project:
    """Projet d'évaluation porté par un nœud client."""

    id: str
    name: str
    owner_node_id: str  # nœud du client qui porte le projet
    description: str = ""
    created_at: float = field(default_factory=_time.time)
    t0_ts: float | None = None  # origine temporelle du projet (epoch s) ; None -> created_at

    @property
    def origin_ts(self) -> float:
        """Origine temporelle effective du projet (t0_ts, sinon created_at)."""
        return self.t0_ts if self.t0_ts is not None else self.created_at


@dataclass
class AHPAssessment:
    """Résultat d'un questionnaire AHP hebdomadaire pour un nœud."""

    node_id: str
    project_id: str
    operator_id: str
    comparisons: dict[tuple[int, int], float]  # jugements Saaty par paire
    criteria_scores: list[float]  # notes [1, 9] par critère
    weights: list[float]
    consistency_ratio: float
    is_consistent: bool
    ud: float  # [0, 1]
    notes: str = ""
    timestamp: float = field(default_factory=_time.time)
