"""Cahier des charges structure d'un noeud : livrables, budget, qualite, penalites.

Le cahier des charges (:class:`CahierDesCharges`) formalise le besoin declare :
QUOI livrer (:class:`Deliverable`, rattachable a un jalon), a quel cout
(budget total, cout unitaire cible), sous quelles exigences qualite
(:class:`QualityRequirements`) et avec quelles clauses de penalite
(:class:`PenaltyClause`).

La serialisation JSON (``cdc_to_json`` / ``cdc_from_json``) suit le meme
pattern tolerant que ``kpis_to_json`` / ``kpis_from_json`` de
:mod:`supplyscore.data.db` : ``dataclasses.asdict`` a l'aller, reconstruction
au retour en IGNORANT les cles inconnues (robustesse a l'evolution de schema).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Deliverable:
    """Livrable du cahier des charges (quoi, combien, rattache a quel jalon)."""

    name: str
    quantity: float
    unit: str  # "pieces", "kg", "lots"...
    milestone_id: str | None = None  # jalon associe (voir domain.milestones)


@dataclass
class QualityRequirements:
    """Exigences qualite : normes, certifications et taux de rebut maximal."""

    standards: list[str] = field(default_factory=list)  # normes (ISO 9001, EN 9100...)
    certifications: list[str] = field(default_factory=list)
    max_scrap_rate: float | None = None  # taux de rebut max [0, 1]
    notes: str = ""


@dataclass
class PenaltyClause:
    """Clause de penalite contractuelle (retard, qualite ou autre)."""

    kind: str  # "late_delivery" | "quality" | "other"
    trigger: str  # description du declencheur
    amount_per_day: float | None = None
    cap_amount: float | None = None


@dataclass
class CahierDesCharges:
    """Cahier des charges structure : livrables, budget, qualite et penalites."""

    deliverables: list[Deliverable] = field(default_factory=list)
    budget_total: float | None = None
    target_unit_cost: float | None = None
    currency: str = "EUR"
    quality: QualityRequirements = field(default_factory=QualityRequirements)
    penalties: list[PenaltyClause] = field(default_factory=list)
    notes: str = ""


# Serialisation CahierDesCharges <-> JSON


def _from_dict[T: (Deliverable, QualityRequirements, PenaltyClause)](cls: type[T], raw: Any) -> T:
    """Reconstruit ``cls`` depuis un dict en ignorant les cles inconnues.

    Tout ce qui n'est pas un dict (None, scalaire...) est traite comme vide :
    les champs obligatoires manquants levent alors le TypeError naturel.
    """
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    known = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


def _list_of[T: (Deliverable, QualityRequirements, PenaltyClause)](
    cls: type[T], payload: dict[str, Any], key: str
) -> list[T]:
    """Reconstruit une liste de ``cls`` (cle manquante, nulle ou non-liste -> [])."""
    value = payload.get(key)
    items: list[Any] = value if isinstance(value, list) else []
    return [_from_dict(cls, item) for item in items]


def _str_or(payload: dict[str, Any], key: str, default: str) -> str:
    """Lit une chaine du payload (cle manquante, nulle ou non-chaine -> defaut)."""
    value = payload.get(key)
    return value if isinstance(value, str) else default


def cdc_to_json(cdc: CahierDesCharges) -> str:
    """Serialise un :class:`CahierDesCharges` en JSON (cles triees, stable)."""
    return json.dumps(dataclasses.asdict(cdc), sort_keys=True)


def cdc_from_json(raw: str) -> CahierDesCharges:
    """Reconstruit un :class:`CahierDesCharges` depuis son JSON.

    Tolerant pour absorber l'evolution de schema : les cles inconnues sont
    ignorees (a tous les niveaux), les listes manquantes ou nulles deviennent
    vides, le bloc qualite manquant redevient :class:`QualityRequirements`
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
