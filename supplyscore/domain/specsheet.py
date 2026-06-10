"""Cahier des charges structuré d'un nœud : livrables, budget, qualité, pénalités.

Le cahier des charges (:class:`CahierDesCharges`) formalise le besoin déclaré :
QUOI livrer (:class:`Deliverable`, rattachable à un jalon), à quel coût
(budget total, coût unitaire cible), sous quelles exigences qualité
(:class:`QualityRequirements`) et avec quelles clauses de pénalité
(:class:`PenaltyClause`).

La sérialisation JSON (``cdc_to_json`` / ``cdc_from_json``) suit le même
pattern tolérant que ``kpis_to_json`` / ``kpis_from_json`` de
:mod:`supplyscore.data.db` : ``dataclasses.asdict`` à l'aller, reconstruction
au retour en IGNORANT les clés inconnues (robustesse à l'évolution de schéma).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Deliverable:
    """Livrable du cahier des charges (quoi, combien, rattaché à quel jalon)."""

    name: str
    quantity: float
    unit: str  # "pièces", "kg", "lots"...
    milestone_id: str | None = None  # jalon associé (voir domain.milestones)


@dataclass
class QualityRequirements:
    """Exigences qualité : normes, certifications et taux de rebut maximal."""

    standards: list[str] = field(default_factory=list)  # normes (ISO 9001, EN 9100...)
    certifications: list[str] = field(default_factory=list)
    max_scrap_rate: float | None = None  # taux de rebut max [0, 1]
    notes: str = ""


@dataclass
class PenaltyClause:
    """Clause de pénalité contractuelle (retard, qualité ou autre)."""

    kind: str  # "late_delivery" | "quality" | "other"
    trigger: str  # description du déclencheur
    amount_per_day: float | None = None
    cap_amount: float | None = None


@dataclass
class CahierDesCharges:
    """Cahier des charges structuré : livrables, budget, qualité et pénalités."""

    deliverables: list[Deliverable] = field(default_factory=list)
    budget_total: float | None = None
    target_unit_cost: float | None = None
    currency: str = "EUR"
    quality: QualityRequirements = field(default_factory=QualityRequirements)
    penalties: list[PenaltyClause] = field(default_factory=list)
    notes: str = ""


# --- Sérialisation CahierDesCharges <-> JSON -------------------------------------


def _from_dict[T: (Deliverable, QualityRequirements, PenaltyClause)](cls: type[T], raw: Any) -> T:
    """Reconstruit ``cls`` depuis un dict en ignorant les clés inconnues.

    Tout ce qui n'est pas un dict (None, scalaire...) est traité comme vide :
    les champs obligatoires manquants lèvent alors le TypeError naturel.
    """
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    known = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


def _list_of[T: (Deliverable, QualityRequirements, PenaltyClause)](
    cls: type[T], payload: dict[str, Any], key: str
) -> list[T]:
    """Reconstruit une liste de ``cls`` (clé manquante, nulle ou non-liste -> [])."""
    value = payload.get(key)
    items: list[Any] = value if isinstance(value, list) else []
    return [_from_dict(cls, item) for item in items]


def _str_or(payload: dict[str, Any], key: str, default: str) -> str:
    """Lit une chaîne du payload (clé manquante, nulle ou non-chaîne -> défaut)."""
    value = payload.get(key)
    return value if isinstance(value, str) else default


def cdc_to_json(cdc: CahierDesCharges) -> str:
    """Sérialise un :class:`CahierDesCharges` en JSON (clés triées, stable)."""
    return json.dumps(dataclasses.asdict(cdc), sort_keys=True)


def cdc_from_json(raw: str) -> CahierDesCharges:
    """Reconstruit un :class:`CahierDesCharges` depuis son JSON.

    Tolérant pour absorber l'évolution de schéma : les clés inconnues sont
    ignorées (à tous les niveaux), les listes manquantes ou nulles deviennent
    vides, le bloc qualité manquant redevient :class:`QualityRequirements`
    vierge. Le round-trip ``cdc_from_json(cdc_to_json(x)) == x`` est exact.

    Raises:
        ValueError: si ``raw`` n'est pas un JSON valide ou n'est pas un objet.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON de cahier des charges invalide : {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON de cahier des charges invalide : objet JSON attendu")
    return CahierDesCharges(
        deliverables=_list_of(Deliverable, payload, "deliverables"),
        budget_total=payload.get("budget_total"),
        target_unit_cost=payload.get("target_unit_cost"),
        currency=_str_or(payload, "currency", "EUR"),
        quality=_from_dict(QualityRequirements, payload.get("quality")),
        penalties=_list_of(PenaltyClause, payload, "penalties"),
        notes=_str_or(payload, "notes", ""),
    )
