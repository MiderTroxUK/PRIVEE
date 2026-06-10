"""Générateur de données de TEST aléatoires pour supplyscore.

ATTENTION : ce module produit des données SIMULÉES, destinées uniquement aux
tests, démos et environnements de développement. Il ne doit JAMAIS être
utilisé en production pour alimenter de vraies décisions logistiques.

Le générateur construit des chaînes d'approvisionnement plausibles (DAG par
rangs, KPIs réalistes) et des questionnaires AHP simulés cohérents (CR < 0.10).
"""

from __future__ import annotations

import random
import uuid

from supplyscore.domain.models import (
    AHPAssessment,
    CO2KPIs,
    CostKPIs,
    InventoryKPIs,
    KPIBundle,
    NetworkKPIs,
    OEEKPIs,
    Project,
    RiskKPIs,
    SupplyArc,
    SupplyNode,
    TimeKPIs,
    UrgencyState,
)

# Échelle de Saaty (jugements admissibles dans une matrice de comparaison).
_SAATY_SCALE: tuple[float, ...] = tuple(
    [1.0 / k for k in range(9, 1, -1)] + [float(k) for k in range(1, 10)]
)

# Indice aléatoire de Saaty (Random Index) pour le calcul du CR.
_RANDOM_INDEX: dict[int, float] = {
    1: 0.0,
    2: 0.0,
    3: 0.58,
    4: 0.90,
    5: 1.12,
    6: 1.24,
    7: 1.32,
    8: 1.41,
    9: 1.45,
    10: 1.49,
}

_SUPPLIER_LABELS: tuple[str, ...] = ("Factory", "Warehouse", "Workshop", "Supplier")

_PRODUCTS: tuple[str, ...] = (
    "Steel coil",
    "Gearbox",
    "PCB board",
    "Plastic casing",
    "Bearing",
    "Copper wire",
    "Aluminium sheet",
    "Sensor module",
    "Battery pack",
    "Valve",
)

_LOCATIONS: tuple[tuple[str, float, float], ...] = (
    ("Lyon", 45.7640, 4.8357),
    ("Hamburg", 53.5511, 9.9937),
    ("Rotterdam", 51.9244, 4.4777),
    ("Barcelona", 41.3874, 2.1686),
    ("Milan", 45.4642, 9.1900),
    ("Gdansk", 54.3520, 18.6466),
    ("Shenzhen", 22.5431, 114.0579),
    ("Casablanca", 33.5731, -7.5898),
    ("Detroit", 42.3314, -83.0458),
    ("Osaka", 34.6937, 135.5023),
)

_TRANSPORT_LABELS: tuple[str, ...] = ("Truck", "Train", "Ship", "Barge")


class RandomSupplyChainGenerator:
    """Générateur reproductible de chaînes d'approvisionnement de TEST.

    Même ``seed`` -> même sortie. Toutes les valeurs aléatoires passent par
    l'instance :class:`random.Random` interne (y compris les UUID).
    """

    def __init__(self, seed: int | None = None) -> None:
        """Initialise le PRNG interne avec ``seed`` (même seed -> même sortie)."""
        self._rng = random.Random(seed)

    # -- helpers internes -------------------------------------------------------

    def _uuid(self) -> str:
        """UUID déterministe (dérivé du PRNG seedé, pas de uuid4 global)."""
        return str(uuid.UUID(int=self._rng.getrandbits(128), version=4))

    def _node_kpis(self) -> KPIBundle:
        """KPIs aléatoires plausibles pour un nœud (tous les blocs remplis)."""
        rng = self._rng

        demand = rng.uniform(10.0, 500.0)
        distance_km = rng.uniform(5.0, 2000.0)
        network = NetworkKPIs(
            product=rng.choice(_PRODUCTS),
            distance_km=distance_km,
            demand=demand,
        )

        max_volume = rng.uniform(200.0, 20000.0)
        max_weight = rng.uniform(1000.0, 100000.0)
        inventory = InventoryKPIs(
            max_volume_m3=max_volume,
            max_weight_kg=max_weight,
            current_volume_m3=max_volume * rng.uniform(0.05, 0.95),
            current_weight_kg=max_weight * rng.uniform(0.05, 0.95),
            flow_rate=demand * rng.uniform(0.85, 1.15),  # proche de la demande
        )

        lead_time_h = rng.uniform(24.0, 720.0)
        time_kpis = TimeKPIs(
            speed_kmh=rng.uniform(40.0, 90.0),
            distance_range_km=distance_km * rng.uniform(1.0, 1.5),
            time_range_h=lead_time_h * rng.uniform(1.0, 1.4),
            refuel_time_h=rng.uniform(0.25, 4.0),
            lead_time_h=lead_time_h,
            lead_time_std_h=lead_time_h * rng.uniform(0.03, 0.20),
            delay_h=rng.uniform(0.0, 72.0),
            deadline_h=lead_time_h * rng.uniform(1.1, 2.5),  # toujours > lead time
        )

        cost_volatility = rng.uniform(0.0, 0.5)
        nominal_op_cost = rng.uniform(1_000.0, 50_000.0)
        product_cost = rng.uniform(5.0, 2_000.0)
        cost = CostKPIs(
            product_cost=product_cost,
            tariff=rng.uniform(1.0, 1.35),
            nominal_op_cost=nominal_op_cost,
            op_cost=nominal_op_cost * (1.0 + cost_volatility),  # cohérent
            fuel_cost=rng.uniform(100.0, 5_000.0),
            risk_cost=nominal_op_cost * rng.uniform(0.01, 0.15),
            storage_cost=rng.uniform(50.0, 2_000.0),
        )

        op_emission = rng.uniform(500.0, 5_000.0)
        energy_mix = rng.uniform(100.0, 2_000.0)
        total = op_emission + energy_mix
        co2 = CO2KPIs(
            fuel_emission_g_km=rng.uniform(50.0, 900.0),
            op_emission_g_h=op_emission,
            energy_mix_g_h=energy_mix,
            co2_target_g_h=total * rng.uniform(0.5, 0.9),  # target < total
            co2_max_g_h=total * rng.uniform(1.1, 1.6),  # total < max
        )

        availability = rng.uniform(0.7, 0.99)
        operating_time = rng.uniform(80.0, 168.0)
        oee = OEEKPIs(
            production_time_h=operating_time * availability,
            operating_time_h=operating_time,
            availability=availability,
            performance=rng.uniform(0.7, 0.99),
            quality=rng.uniform(0.7, 0.99),
        )

        risk = RiskKPIs(
            failure_probability=rng.uniform(0.001, 0.1),
            recovery_time_h=rng.uniform(4.0, 240.0),
            severity=rng.uniform(0.1, 0.9),
            cost_volatility=cost_volatility,
            env_exposure=rng.uniform(0.0, 0.3),
            political_risk=rng.uniform(0.0, 0.3),
        )

        return KPIBundle(
            network=network,
            inventory=inventory,
            time=time_kpis,
            cost=cost,
            co2=co2,
            oee=oee,
            risk=risk,
        )

    def _arc_kpis(self) -> KPIBundle:
        """KPIs transport pour un arc (vitesse, distance, carburant)."""
        rng = self._rng
        distance = rng.uniform(10.0, 2_000.0)
        speed = rng.uniform(30.0, 90.0)
        kpis = KPIBundle()
        kpis.network.distance_km = distance
        kpis.time.speed_kmh = speed
        kpis.time.distance_range_km = distance * rng.uniform(1.05, 1.6)
        kpis.time.lead_time_h = distance / speed
        kpis.time.refuel_time_h = rng.uniform(0.25, 2.0)
        kpis.cost.fuel_cost = distance * rng.uniform(0.4, 2.5)
        kpis.co2.fuel_emission_g_km = rng.uniform(60.0, 1_000.0)
        return kpis

    def _make_node(
        self, rank: int, index: int, project_id: str, label: str | None = None
    ) -> SupplyNode:
        rng = self._rng
        node_label = label if label is not None else rng.choice(_SUPPLIER_LABELS)
        city, lat, lon = rng.choice(_LOCATIONS)
        return SupplyNode(
            id=self._uuid(),
            name=f"{node_label} {city} R{rank}-{index}",
            label=node_label,
            rank=rank,
            project_id=project_id,
            location=city,
            latitude=lat + rng.uniform(-0.5, 0.5),
            longitude=lon + rng.uniform(-0.5, 0.5),
            kpis=self._node_kpis(),
            # timestamp déterministe : garantit la reproductibilité à seed égal
            urgency=UrgencyState(timestamp=0.0),
        )

    def _make_arc(self, source: SupplyNode, target: SupplyNode) -> SupplyArc:
        rng = self._rng
        return SupplyArc(
            source_id=source.id,
            target_id=target.id,
            label=rng.choice(_TRANSPORT_LABELS),
            gamma=rng.uniform(0.3, 0.9),
            beta=rng.uniform(0.3, 0.9),
            delta=rng.uniform(0.5, 1.5),
            kpis=self._arc_kpis(),
        )

    # -- API publique -----------------------------------------------------------

    def generate(
        self,
        n_ranks: int = 3,
        breadth: tuple[int, int] = (1, 3),
    ) -> tuple[Project, list[SupplyNode], list[SupplyArc]]:
        """Construit un DAG de chaîne d'approvisionnement de TEST.

        - 1 client final au rang 0 (label "Client"), porteur du :class:`Project` ;
        - à chaque rang ``r`` de 1 à ``n_ranks``, chaque nœud du rang ``r-1``
          reçoit entre ``breadth[0]`` et ``breadth[1]`` fournisseurs dédiés ;
        - ~20 % des fournisseurs servent en plus un second client du rang
          inférieur (arcs croisés), toujours orientés rang r -> rang r-1 :
          aucun cycle possible.
        """
        if n_ranks < 1:
            raise ValueError("n_ranks doit être >= 1")
        lo, hi = breadth
        if not (1 <= lo <= hi):
            raise ValueError("breadth doit vérifier 1 <= min <= max")

        rng = self._rng
        project_id = self._uuid()

        client = self._make_node(rank=0, index=0, project_id=project_id, label="Client")
        project = Project(
            id=project_id,
            name=f"Project {client.location} {rng.randint(1000, 9999)}",
            owner_node_id=client.id,
            description="Donnees de test generees aleatoirement (simulation).",
            created_at=rng.uniform(1.6e9, 1.8e9),
        )

        nodes: list[SupplyNode] = [client]
        arcs: list[SupplyArc] = []
        previous_rank: list[SupplyNode] = [client]

        for rank in range(1, n_ranks + 1):
            current_rank: list[SupplyNode] = []
            for consumer in previous_rank:
                n_suppliers = rng.randint(lo, hi)
                for _ in range(n_suppliers):
                    supplier = self._make_node(
                        rank=rank, index=len(current_rank), project_id=project_id
                    )
                    current_rank.append(supplier)
                    arcs.append(self._make_arc(supplier, consumer))

            # Arcs croisés : un fournisseur peut servir un 2e client du rang
            # inférieur (~20 % de chance), toujours rang r -> rang r-1.
            if len(previous_rank) >= 2:
                existing = {(a.source_id, a.target_id) for a in arcs}
                for supplier in current_rank:
                    if rng.random() < 0.20:
                        candidates = [
                            c for c in previous_rank if (supplier.id, c.id) not in existing
                        ]
                        if candidates:
                            extra_client = rng.choice(candidates)
                            arc = self._make_arc(supplier, extra_client)
                            arcs.append(arc)
                            existing.add((arc.source_id, arc.target_id))

            nodes.extend(current_rank)
            previous_rank = current_rank

        return project, nodes, arcs

    def generate_assessment(
        self,
        node_id: str,
        project_id: str,
        operator_id: str = "sim",
        urgency_bias: float = 0.5,
        n_criteria: int = 4,
        notes: str = "",
    ) -> AHPAssessment:
        """Questionnaire AHP simulé COHÉRENT (CR < 0.10 garanti).

        Tire des poids cibles aléatoires, construit les comparaisons par paires
        à partir des ratios ``w_i / w_j`` arrondis à l'échelle de Saaty, puis
        recalcule les poids par moyenne des lignes normalisées (AHP standard)
        et le ratio de cohérence — sans dépendre de ``supplyscore.core``.

        ``urgency_bias`` dans [0, 1] décale les scores critères : 0 -> scores
        proches de 1 (pas urgent), 1 -> proches de 9 (très urgent).

        Le défaut ``n_criteria=4`` est aligné sur les 4 critères de l'UI du
        questionnaire (``CRITERIA`` de :mod:`supplyscore.core.ahp`).
        """
        rng = self._rng
        n = n_criteria
        if n < 2:
            raise ValueError("n_criteria doit être >= 2")

        # Boucle de sécurité : l'arrondi Saaty d'une matrice issue de vrais
        # ratios donne quasi toujours CR < 0.10 ; on retire au cas où.
        for _ in range(100):
            target = [rng.uniform(1.0, 4.0) for _ in range(n)]
            total = sum(target)
            target = [w / total for w in target]

            comparisons: dict[tuple[int, int], float] = {}
            for i in range(n):
                for j in range(i + 1, n):
                    ratio = target[i] / target[j]
                    comparisons[(i, j)] = min(_SAATY_SCALE, key=lambda s: abs(s - ratio))

            weights, cr = self._solve_ahp(comparisons, n)
            if cr < 0.10:
                break

        # Scores critères [1, 9] centrés selon urgency_bias.
        center = 1.0 + 8.0 * min(max(urgency_bias, 0.0), 1.0)
        criteria_scores = [min(max(rng.gauss(center, 1.2), 1.0), 9.0) for _ in range(n)]

        # Ud = (somme pondérée des scores - 1) / 8, dans [0, 1].
        weighted = sum(w * s for w, s in zip(weights, criteria_scores, strict=True))
        ud = (weighted - 1.0) / 8.0

        return AHPAssessment(
            node_id=node_id,
            project_id=project_id,
            operator_id=operator_id,
            comparisons=comparisons,
            criteria_scores=criteria_scores,
            weights=weights,
            consistency_ratio=cr,
            is_consistent=cr < 0.10,
            ud=ud,
            notes=notes,
        )

    @staticmethod
    def _solve_ahp(comparisons: dict[tuple[int, int], float], n: int) -> tuple[list[float], float]:
        """Poids AHP (moyenne des lignes normalisées) + ratio de cohérence."""
        # Matrice complète réciproque.
        matrix = [[1.0] * n for _ in range(n)]
        for (i, j), value in comparisons.items():
            matrix[i][j] = value
            matrix[j][i] = 1.0 / value

        # Normalisation par colonne puis moyenne par ligne.
        col_sums = [sum(matrix[i][j] for i in range(n)) for j in range(n)]
        weights = [sum(matrix[i][j] / col_sums[j] for j in range(n)) / n for i in range(n)]

        # lambda_max approché : moyenne de (A.w)_i / w_i.
        aw = [sum(matrix[i][j] * weights[j] for j in range(n)) for i in range(n)]
        lambda_max = sum(aw[i] / weights[i] for i in range(n)) / n

        ci = (lambda_max - n) / (n - 1)
        ri = _RANDOM_INDEX.get(n, 1.49)
        cr = 0.0 if ri == 0.0 else ci / ri
        return weights, cr
