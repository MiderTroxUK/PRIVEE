"""Generateur de donnees de TEST aleatoires pour supplyscore.

ATTENTION : ce module produit des donnees SIMULEES, destinees uniquement aux
tests, demos et environnements de developpement. Il ne doit JAMAIS etre
utilise en production pour alimenter de vraies decisions logistiques.

Le generateur construit des chaines d'approvisionnement plausibles (DAG par
rangs, KPIs realistes) et des questionnaires AHP simules coherents (CR < 0.10).
"""

from __future__ import annotations

import random
import uuid

from supplyscore.domain.milestones import Milestone, MilestoneStatus
from supplyscore.domain.models import (
    AHPAssessment,
    ArcKind,
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
from supplyscore.domain.tags import Tag, TagCategory

# Echelle de Saaty (jugements admissibles dans une matrice de comparaison).
_SAATY_SCALE: tuple[float, ...] = tuple(
    [1.0 / k for k in range(9, 1, -1)] + [float(k) for k in range(1, 10)]
)

# Indice aleatoire de Saaty (Random Index) pour le calcul du CR.
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
    """Generateur reproductible de chaines d'approvisionnement de TEST.

    Meme ``seed`` -> meme sortie. Toutes les valeurs aleatoires passent par
    l'instance :class:`random.Random` interne (y compris les UUID).
    """

    def __init__(self, seed: int | None = None) -> None:
        """Initialise le PRNG interne avec ``seed`` (meme seed -> meme sortie)."""
        self._rng = random.Random(seed)

    # helpers internes

    def _uuid(self) -> str:
        """UUID deterministe (derive du PRNG seede, pas de uuid4 global)."""
        return str(uuid.UUID(int=self._rng.getrandbits(128), version=4))

    def _node_kpis(self) -> KPIBundle:
        """KPIs aleatoires plausibles pour un noeud (tous les blocs remplis)."""
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
        # CRENEAU DE FLUX RESERVE - ne pas supprimer. Ce tirage alimentait ``delay_h`` ; sa valeur est desormais ignoree (cf. ``delay_h=0.0`` ci-dessous), mais le TIRAGE lui-meme est conserve parce que le generateur est seede et que toute la reproductibilite du depot en depend : usine synthetique de ``projects/factory/dgp.py``, jeu d'entrainement de la couche de calibration, fixtures de demo et de test. Retirer l'appel decale tout le flux aleatoire en aval et change SILENCIEUSEMENT chaque scenario genere a seed egal - constate sur trois tests (rapport de session, figures du tableau de bord, heatmap PROMETHEE) qui decrivaient soudain un autre graphe.
        rng.uniform(0.0, 72.0)
        time_kpis = TimeKPIs(
            speed_kmh=rng.uniform(40.0, 90.0),
            distance_range_km=distance_km * rng.uniform(1.0, 1.5),
            time_range_h=lead_time_h * rng.uniform(1.0, 1.4),
            refuel_time_h=rng.uniform(0.25, 4.0),
            lead_time_h=lead_time_h,
            lead_time_std_h=lead_time_h * rng.uniform(0.03, 0.20),
            # delay_h est un ETAT ACCUMULE - " combien de production a reellement ete perdue a ce jour " - et il DEMARRE A ZERO : un noeud qu'on vient de generer n'a subi aucun incident. Le tirage aleatoire qui figurait ici datait de l'epoque ou le champ etait dormant (ecrit, jamais lu) ; depuis qu'il alimente additivement les trois estimateurs de P(jalon rate), il injectait sur chaque noeud une penalite que personne n'avait declaree. Mesure sur un cas serre (lead 200 h, sigma 30 h, marge 260 h, avancement 0) : u_time = 0,023 a delay = 0 contre 0,282 EN MOYENNE sous le tirage uniforme 0-72 h, et jusqu'a 0,655 en haut du tirage. Un choc qui doit peser passe par ``domain.events._arret_impact``, jamais par le generateur. (Le tirage correspondant reste consomme plus haut - cf. le creneau de flux reserve, indispensable a la reproductibilite seedee.)
            delay_h=0.0,
            deadline_h=lead_time_h * rng.uniform(1.1, 2.5),  # toujours > lead time
        )

        cost_volatility = rng.uniform(0.0, 0.5)
        nominal_op_cost = rng.uniform(1_000.0, 50_000.0)
        product_cost = rng.uniform(5.0, 2_000.0)
        cost = CostKPIs(
            product_cost=product_cost,
            tariff=rng.uniform(1.0, 1.35),
            nominal_op_cost=nominal_op_cost,
            op_cost=nominal_op_cost * (1.0 + cost_volatility),  # coherent
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
            # timestamp deterministe : garantit la reproductibilite a seed egal
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

    # API publique

    def generate(
        self,
        n_ranks: int = 3,
        breadth: tuple[int, int] = (1, 3),
    ) -> tuple[Project, list[SupplyNode], list[SupplyArc]]:
        """Construit un DAG de chaine d'approvisionnement de TEST.

        - 1 client final au rang 0 (label "Client"), porteur du :class:`Project` ;
        - a chaque rang ``r`` de 1 a ``n_ranks``, chaque noeud du rang ``r-1``
          recoit entre ``breadth[0]`` et ``breadth[1]`` fournisseurs dedies ;
        - ~20 % des fournisseurs servent en plus un second client du rang
          inferieur (arcs croises), toujours orientes rang r -> rang r-1 :
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

            # Arcs croises : un fournisseur peut servir un 2e client du rang inferieur (~20 % de chance), toujours rang r -> rang r-1.
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

    def generate_stress(
        self,
        n_nodes: int = 1000,
        largeur_rang: int = 40,
        p_arc_croise: float = 0.25,
        enrich: bool = False,
    ) -> tuple[Project, list[SupplyNode], list[SupplyArc]]:
        """DAG de stress pour les bancs de performance (E14) - large ET profond.

        Topologie : 1 client final au rang 0 (porteur du :class:`Project`),
        puis des rangs successifs de ``largeur_rang`` noeuds (le dernier rang
        complete a ``n_nodes``). Chaque noeud du rang ``r`` alimente exactement
        1 noeud du rang ``r-1`` (cible tiree au hasard), plus, avec probabilite
        ``p_arc_croise``, un arc croise vers un AUTRE noeud du rang inferieur.
        Tous les arcs sont orientes rang ``r`` -> rang ``r-1`` : aucun cycle
        possible par construction. KPIs complets sur chaque noeud
        (:meth:`_node_kpis`), reproductible a seed egal (tout l'alea passe par
        ``self._rng``).

        STRICT NECESSAIRE POUR MESURER : par defaut, PAS de jalons ni de tags
        - les bancs E14 chronometrent propagation, persistance, Monte Carlo et
        rendu, qui n'en dependent pas. Avec ``enrich=True``, les tags de TEST
        sont poses sur les noeuds (``node.tags``) et des arcs de secours sont
        ajoutes ; les jalons, persistes par noeud cote service, restent a
        generer par l'appelant via :meth:`generate_milestones` (la signature
        de retour ne les transporte pas).

        Args:
            n_nodes: nombre total de noeuds (client final inclus), >= 2.
            largeur_rang: largeur cible de chaque rang (>= 1).
            p_arc_croise: probabilite d'un arc croise par noeud, dans [0, 1].
            enrich: ajoute tags (sur les noeuds) et arcs de secours.

        Returns:
            ``(project, nodes, arcs)`` - memes types que :meth:`generate`.

        Raises:
            ValueError: ``n_nodes < 2``, ``largeur_rang < 1`` ou
                ``p_arc_croise`` hors [0, 1].
        """
        if n_nodes < 2:
            raise ValueError("n_nodes doit être >= 2")
        if largeur_rang < 1:
            raise ValueError("largeur_rang doit être >= 1")
        if not 0.0 <= p_arc_croise <= 1.0:
            raise ValueError("p_arc_croise doit être dans [0, 1]")

        rng = self._rng
        project_id = self._uuid()
        client = self._make_node(rank=0, index=0, project_id=project_id, label="Client")
        project = Project(
            id=project_id,
            name=f"Stress {n_nodes} noeuds {rng.randint(1000, 9999)}",
            owner_node_id=client.id,
            description="DAG de stress genere pour les bancs de performance (simulation).",
            created_at=rng.uniform(1.6e9, 1.8e9),
        )

        nodes: list[SupplyNode] = [client]
        arcs: list[SupplyArc] = []
        previous_rank: list[SupplyNode] = [client]
        rank = 0
        while len(nodes) < n_nodes:
            rank += 1
            taille = min(largeur_rang, n_nodes - len(nodes))
            current_rank = [
                self._make_node(rank=rank, index=index, project_id=project_id)
                for index in range(taille)
            ]
            for supplier in current_rank:
                consumer = rng.choice(previous_rank)
                arcs.append(self._make_arc(supplier, consumer))
                if len(previous_rank) >= 2 and rng.random() < p_arc_croise:
                    extra_client = rng.choice([c for c in previous_rank if c.id != consumer.id])
                    arcs.append(self._make_arc(supplier, extra_client))
            nodes.extend(current_rank)
            previous_rank = current_rank

        if enrich:
            _categories, tags = self.generate_tags(project_id)
            tag_ids = [tag.id for tag in tags]
            for node in nodes:
                node.tags = self.pick_node_tags(tag_ids)
            arcs.extend(self.generate_backup_arcs(nodes, arcs))

        return project, nodes, arcs

    # enrichissements v2 (jalons, tags, arcs de secours)

    def generate_milestones(self, node_id: str, t0_ts: float) -> list[Milestone]:
        """Jalons de TEST pour un noeud : 2 a 4 fenetres successives depuis ``t0_ts``.

        Les deadlines sont RELATIVES a ``t0_ts`` (l'origine du projet) pour que
        l'horloge - reelle ou de jeu - rende les echeances vivantes. Le premier
        jalon est parfois deja termine (~30 % de chance).
        """
        rng = self._rng
        kinds = ["proto", "serie", "livraison", "custom"]
        names = ["Proto", "Série 1", "Livraison", "Qualification"]
        count = rng.randint(2, 4)
        milestones: list[Milestone] = []
        cursor = t0_ts
        for position in range(count):
            duration_h = rng.uniform(7 * 24.0, 60 * 24.0)
            start = cursor
            deadline = start + duration_h * 3600.0
            done = position == 0 and rng.random() < 0.30
            milestones.append(
                Milestone(
                    id=self._uuid(),
                    node_id=node_id,
                    name=names[position % len(names)],
                    kind=kinds[position % len(kinds)],
                    start_ts=start,
                    deadline_ts=deadline,
                    status=MilestoneStatus.DONE if done else MilestoneStatus.ACTIVE,
                    progress=1.0 if done else round(rng.uniform(0.0, 0.9), 2),
                    position=position,
                )
            )
            cursor = deadline
        return milestones

    def generate_tags(self, project_id: str) -> tuple[list[TagCategory], list[Tag]]:
        """Taxonomie de TEST : 2 categories colorees et 4 a 6 tags rattaches."""
        rng = self._rng
        categories = [
            TagCategory(id=self._uuid(), project_id=project_id, name="Procédé", color="#2c5f7c"),
            TagCategory(id=self._uuid(), project_id=project_id, name="Région", color="#b06000"),
        ]
        pool = [
            ("Usinage", 0),
            ("Fonderie", 0),
            ("Assemblage", 0),
            ("Europe", 1),
            ("Asie", 1),
            ("Amériques", 1),
        ]
        count = rng.randint(4, 6)
        tags = [
            Tag(
                id=self._uuid(),
                project_id=project_id,
                name=name,
                category_id=categories[cat_index].id,
            )
            for name, cat_index in pool[:count]
        ]
        return categories, tags

    def pick_node_tags(self, tag_ids: list[str]) -> list[str]:
        """Tire 1 a 3 tags (sans doublon) pour un noeud."""
        if not tag_ids:
            return []
        rng = self._rng
        k = rng.randint(1, min(3, len(tag_ids)))
        return rng.sample(tag_ids, k)

    def generate_backup_arcs(
        self, nodes: list[SupplyNode], arcs: list[SupplyArc]
    ) -> list[SupplyArc]:
        """Arcs de secours de TEST : ~1 arc nominal sur 10 recoit un fournisseur backup.

        L'arc backup relie un AUTRE noeud du meme rang que le fournisseur nominal
        vers le meme client (purement visuel - inerte dans les calculs).
        """
        rng = self._rng
        by_id = {n.id: n for n in nodes}
        existing = {(a.source_id, a.target_id) for a in arcs}
        backups: list[SupplyArc] = []
        for arc in list(arcs):
            if rng.random() >= 0.10:
                continue
            source = by_id.get(arc.source_id)
            if source is None:
                continue
            candidates = [
                n
                for n in nodes
                if n.rank == source.rank
                and n.id != source.id
                and (n.id, arc.target_id) not in existing
            ]
            if not candidates:
                continue
            backup_source = rng.choice(candidates)
            backup = SupplyArc(
                source_id=backup_source.id,
                target_id=arc.target_id,
                label="Backup",
                gamma=0.0,
                beta=0.0,
                kind_arc=ArcKind.BACKUP,
                kpis=self._arc_kpis(),
            )
            backups.append(backup)
            existing.add((backup.source_id, backup.target_id))
        return backups

    def generate_assessment(
        self,
        node_id: str,
        project_id: str,
        operator_id: str = "sim",
        urgency_bias: float = 0.5,
        n_criteria: int = 4,
        notes: str = "",
    ) -> AHPAssessment:
        """Questionnaire AHP simule COHERENT (CR < 0.10 garanti).

        Tire des poids cibles aleatoires, construit les comparaisons par paires
        a partir des ratios ``w_i / w_j`` arrondis a l'echelle de Saaty, puis
        recalcule les poids par moyenne des lignes normalisees (AHP standard)
        et le ratio de coherence - sans dependre de ``supplyscore.core``.

        ``urgency_bias`` dans [0, 1] decale les scores criteres : 0 -> scores
        proches de 1 (pas urgent), 1 -> proches de 9 (tres urgent).

        Le defaut ``n_criteria=4`` est aligne sur les 4 criteres de l'UI du
        questionnaire (``CRITERIA`` de :mod:`supplyscore.core.ahp`).
        """
        rng = self._rng
        n = n_criteria
        if n < 2:
            raise ValueError("n_criteria doit être >= 2")

        # Boucle de securite : l'arrondi Saaty d'une matrice issue de vrais ratios donne quasi toujours CR < 0.10 ; on retire au cas ou.
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

        # Scores criteres [1, 9] centres selon urgency_bias.
        center = 1.0 + 8.0 * min(max(urgency_bias, 0.0), 1.0)
        criteria_scores = [min(max(rng.gauss(center, 1.2), 1.0), 9.0) for _ in range(n)]

        # Ud = (somme ponderee des scores - 1) / 8, dans [0, 1].
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
        """Poids AHP (moyenne des lignes normalisees) + ratio de coherence."""
        # Matrice complete reciproque.
        matrix = [[1.0] * n for _ in range(n)]
        for (i, j), value in comparisons.items():
            matrix[i][j] = value
            matrix[j][i] = 1.0 / value

        # Normalisation par colonne puis moyenne par ligne.
        col_sums = [sum(matrix[i][j] for i in range(n)) for j in range(n)]
        weights = [sum(matrix[i][j] / col_sums[j] for j in range(n)) / n for i in range(n)]

        # lambda_max approche : moyenne de (A.w)_i / w_i.
        aw = [sum(matrix[i][j] * weights[j] for j in range(n)) for i in range(n)]
        lambda_max = sum(aw[i] / weights[i] for i in range(n)) / n

        ci = (lambda_max - n) / (n - 1)
        ri = _RANDOM_INDEX.get(n, 1.49)
        cr = 0.0 if ri == 0.0 else ci / ri
        return weights, cr
