"""Small data contracts shared by ingestion and the pure checking core."""

from dataclasses import dataclass, field
import math
from typing import Any


class InputError(ValueError):
    """Invalid input, mapping, dependency or output destination."""


def evidence_value(value: Any) -> Any:
    """Keep unsupported values auditable without emitting invalid JSON numbers."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (list, tuple)):
        return [evidence_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): evidence_value(item) for key, item in value.items()}
    # IFC references have a stable STEP representation; other unsupported
    # objects have no duration semantics and are never parsed as numbers.
    return {"unsupported_type": type(value).__name__, "value": str(value)}


@dataclass(frozen=True)
class Door:
    ifc_entity_id: int
    ifc_global_id: str | None
    door_id: Any
    raw_rating: Any
    identity_source: str | None = None
    rating_source: str | None = None
    rating_property_found: bool = False
    extraction_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScheduleRow:
    schedule_row: int
    door_id: str
    raw_rating: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Extraction:
    doors: tuple[Door, ...]
    schema: str
    ifcopenshell_version: str
    diagnostics: tuple[str, ...] = ()
