"""Validation exhaustive du domaine — erreurs bloquantes et avertissements (E10.1).

Deux sévérités, deux philosophies :

- « erreur » : la valeur est physiquement impossible ou hors des bornes de
  :data:`supplyscore.domain.constraints.KPI_CONSTRAINTS` (NaN, infini,
  probabilité > 1...) — l'enregistrement doit être refusé ;
- « avertissement » : la situation est anormale mais RÉELLE (stock au-delà de
  la capacité déclarée, échéance déjà intenable...) — l'opérateur doit pouvoir
  l'enregistrer telle quelle, le signal est purement informatif et n'est
  JAMAIS bloquant.

Les bornes champ à champ proviennent exclusivement de
:mod:`supplyscore.domain.constraints` (source de vérité unique, partagée avec
l'UI) ; ce module y ajoute les contrôles croisés inter-champs et la validation
des entités (:class:`~supplyscore.domain.models.SupplyNode`,
:class:`~supplyscore.domain.models.SupplyArc`,
:class:`~supplyscore.domain.milestones.Milestone`,
:class:`~supplyscore.domain.specsheet.CahierDesCharges`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from supplyscore.domain.constraints import KPI_CONSTRAINTS, validate_kpi_value
from supplyscore.domain.milestones import Milestone
from supplyscore.domain.models import KPIBundle, SupplyArc, SupplyNode
from supplyscore.domain.specsheet import CahierDesCharges

#: États d'onboarding acceptés pour un nœud.
_ONBOARDING_STATES = frozenset({"draft", "complete"})


@dataclass(frozen=True)
class ValidationIssue:
    """Constat de validation : champ fautif, message français et sévérité."""

    champ: str
    message_fr: str
    severite: Literal["erreur", "avertissement"]


# --- Briques internes -----------------------------------------------------------


def _non_fini(champ: str, value: float) -> ValidationIssue:
    """Erreur « valeur non finie » (NaN ou ±inf) pour ``champ``."""
    return ValidationIssue(champ, f"{champ} : valeur non finie ({value!r})", "erreur")


def _check_intervalle(champ: str, value: float, lo: float, hi: float) -> ValidationIssue | None:
    """Erreur si ``value`` n'est pas finie ou sort de [lo, hi], sinon None."""
    if not math.isfinite(value):
        return _non_fini(champ, value)
    if not lo <= value <= hi:
        return ValidationIssue(champ, f"{champ} : {value} hors [{lo}, {hi}]", "erreur")
    return None


def _check_montant(champ: str, value: float) -> ValidationIssue | None:
    """Erreur si ``value`` n'est pas finie ou est négative (montant), sinon None."""
    if not math.isfinite(value):
        return _non_fini(champ, value)
    if value < 0.0:
        return ValidationIssue(champ, f"{champ} : montant négatif ({value})", "erreur")
    return None


def _avertissements_croises(b: KPIBundle) -> list[ValidationIssue]:
    """Avertissements croisés inter-champs d'un bundle KPI (jamais bloquants)."""
    issues: list[ValidationIssue] = []
    inv, tps, co2, cost = b.inventory, b.time, b.co2, b.cost
    if (
        inv.current_volume_m3 is not None
        and inv.max_volume_m3 is not None
        and inv.current_volume_m3 > inv.max_volume_m3
    ):
        issues.append(
            ValidationIssue(
                "inventory.current_volume_m3",
                "stock au-delà de la capacité déclarée "
                f"({inv.current_volume_m3} m³ > {inv.max_volume_m3} m³)",
                "avertissement",
            )
        )
    if (
        inv.current_weight_kg is not None
        and inv.max_weight_kg is not None
        and inv.current_weight_kg > inv.max_weight_kg
    ):
        issues.append(
            ValidationIssue(
                "inventory.current_weight_kg",
                "stock au-delà de la capacité déclarée "
                f"({inv.current_weight_kg} kg > {inv.max_weight_kg} kg)",
                "avertissement",
            )
        )
    if (
        co2.co2_target_g_h is not None
        and co2.co2_max_g_h is not None
        and co2.co2_target_g_h >= co2.co2_max_g_h
    ):
        issues.append(
            ValidationIssue(
                "co2.co2_target_g_h",
                "cible CO2 >= maximum : bornes incohérentes "
                f"({co2.co2_target_g_h} >= {co2.co2_max_g_h} gCO2/h)",
                "avertissement",
            )
        )
    if (
        tps.deadline_h is not None
        and tps.lead_time_h is not None
        and tps.deadline_h < tps.lead_time_h
    ):
        issues.append(
            ValidationIssue(
                "time.deadline_h",
                "retard quasi certain : échéance < lead time "
                f"({tps.deadline_h} h < {tps.lead_time_h} h)",
                "avertissement",
            )
        )
    if inv.flow_rate is not None and b.network.demand is None:
        issues.append(
            ValidationIssue(
                "inventory.flow_rate",
                "débit sans demande : u_cap partiel (network.demand non renseigné)",
                "avertissement",
            )
        )
    if (
        cost.op_cost is not None
        and cost.nominal_op_cost is not None
        and cost.op_cost < cost.nominal_op_cost
    ):
        issues.append(
            ValidationIssue(
                "cost.op_cost",
                "coût réel < nominal : économie — vérifier la saisie "
                f"({cost.op_cost} < {cost.nominal_op_cost})",
                "avertissement",
            )
        )
    return issues


# --- API publique ----------------------------------------------------------------


def validate_kpis(b: KPIBundle) -> list[ValidationIssue]:
    """Valide un bundle KPI : bornes champ à champ + contrôles croisés.

    Chaque champ renseigné est confronté aux bornes de
    :data:`~supplyscore.domain.constraints.KPI_CONSTRAINTS` via
    :func:`~supplyscore.domain.constraints.validate_kpi_value` (sévérité
    « erreur » : bornes, NaN, infinis). Les incohérences inter-champs (stock
    au-delà de la capacité, échéance < lead time, cible CO2 >= maximum,
    débit sans demande, coût réel < nominal) produisent des
    « avertissement » jamais bloquants : l'opérateur doit pouvoir
    enregistrer des situations anormales réelles.
    """
    issues: list[ValidationIssue] = []
    for path in KPI_CONSTRAINTS:
        block_name, field_name = path.split(".", 1)
        value = getattr(getattr(b, block_name), field_name)
        message = validate_kpi_value(path, value)
        if message is not None:
            issues.append(ValidationIssue(path, message, "erreur"))
    issues.extend(_avertissements_croises(b))
    return issues


def validate_node(n: SupplyNode) -> list[ValidationIssue]:
    """Valide un nœud : identité, rang, géolocalisation, onboarding et KPIs."""
    issues: list[ValidationIssue] = []
    if not n.name.strip():
        issues.append(ValidationIssue("name", "nom de nœud vide", "erreur"))
    if n.rank < 0:
        issues.append(ValidationIssue("rank", f"rang négatif ({n.rank})", "erreur"))
    if n.latitude is not None:
        issue = _check_intervalle("latitude", n.latitude, -90.0, 90.0)
        if issue is not None:
            issues.append(issue)
    if n.longitude is not None:
        issue = _check_intervalle("longitude", n.longitude, -180.0, 180.0)
        if issue is not None:
            issues.append(issue)
    if n.onboarding_state not in _ONBOARDING_STATES:
        issues.append(
            ValidationIssue(
                "onboarding_state",
                f"état d'onboarding inconnu ({n.onboarding_state!r}) — "
                "attendu « draft » ou « complete »",
                "erreur",
            )
        )
    issues.extend(validate_kpis(n.kpis))
    return issues


def validate_arc(a: SupplyArc) -> list[ValidationIssue]:
    """Valide un arc : coefficients de propagation bornés et absence de boucle."""
    issues: list[ValidationIssue] = []
    coefficients = (("gamma", a.gamma, 1.0), ("beta", a.beta, 1.0), ("delta", a.delta, 2.0))
    for champ, value, hi in coefficients:
        issue = _check_intervalle(champ, value, 0.0, hi)
        if issue is not None:
            issues.append(issue)
    if a.source_id == a.target_id:
        issues.append(
            ValidationIssue(
                "target_id",
                f"boucle sur soi-même interdite (source = target = {a.source_id!r})",
                "erreur",
            )
        )
    return issues


def validate_milestone(m: Milestone) -> list[ValidationIssue]:
    """Valide un jalon : nom, fenêtre temporelle finie et ordonnée, avancement."""
    issues: list[ValidationIssue] = []
    if not m.name.strip():
        issues.append(ValidationIssue("name", "nom de jalon vide", "erreur"))
    fenetres_finies = True
    for champ, ts in (("start_ts", m.start_ts), ("deadline_ts", m.deadline_ts)):
        if not math.isfinite(ts):
            issues.append(_non_fini(champ, ts))
            fenetres_finies = False
    if fenetres_finies and m.deadline_ts <= m.start_ts:
        issues.append(
            ValidationIssue(
                "deadline_ts",
                f"échéance ({m.deadline_ts}) <= début ({m.start_ts}) : fenêtre vide ou inversée",
                "erreur",
            )
        )
    issue = _check_intervalle("progress", m.progress, 0.0, 1.0)
    if issue is not None:
        issues.append(issue)
    return issues


def validate_cdc(c: CahierDesCharges) -> list[ValidationIssue]:
    """Valide un cahier des charges : budgets, livrables, qualité et pénalités."""
    issues: list[ValidationIssue] = []
    montants = (("budget_total", c.budget_total), ("target_unit_cost", c.target_unit_cost))
    for champ, montant in montants:
        if montant is None:
            continue
        issue = _check_montant(champ, montant)
        if issue is not None:
            issues.append(issue)
    for i, livrable in enumerate(c.deliverables):
        champ = f"deliverables[{i}].quantity"
        if not math.isfinite(livrable.quantity):
            issues.append(_non_fini(champ, livrable.quantity))
        elif livrable.quantity <= 0.0:
            issues.append(
                ValidationIssue(
                    champ,
                    f"quantité du livrable {livrable.name!r} <= 0 ({livrable.quantity})",
                    "erreur",
                )
            )
    if c.quality.max_scrap_rate is not None:
        issue = _check_intervalle("quality.max_scrap_rate", c.quality.max_scrap_rate, 0.0, 1.0)
        if issue is not None:
            issues.append(issue)
    for i, penalite in enumerate(c.penalties):
        sous_champs = (
            ("amount_per_day", penalite.amount_per_day),
            ("cap_amount", penalite.cap_amount),
        )
        for sub, montant in sous_champs:
            if montant is None:
                continue
            issue = _check_montant(f"penalties[{i}].{sub}", montant)
            if issue is not None:
                issues.append(issue)
    return issues


def erreurs(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    """Filtre les constats bloquants (sévérité « erreur »)."""
    return [issue for issue in issues if issue.severite == "erreur"]


def avertissements(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    """Filtre les constats informatifs (sévérité « avertissement »)."""
    return [issue for issue in issues if issue.severite == "avertissement"]
