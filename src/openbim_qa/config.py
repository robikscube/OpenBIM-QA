"""Strict, explicit JSON mapping; never guess an exporter's Mark field."""

import json
from dataclasses import asdict, dataclass, fields
from typing import Any

from .models import InputError


def _valid_source(value: Any) -> bool:
    return isinstance(value, str) and (
        value in {"Tag", "Name", "GlobalId"}
        or (value.count(".") == 1 and all(part.strip() == part and part for part in value.split("."))
            and value.split(".")[1] != "id")
    )


@dataclass(frozen=True)
class Mapping:
    door_id_source: str = "Tag"
    door_id_fallback: str | None = None
    fire_rating_pset: str = "Pset_DoorCommon"
    fire_rating_property: str = "FireRating"
    numeric_rating_unit: str = "minutes"
    strict_matching: bool = True
    inherit_type_properties: bool = False

    def __post_init__(self) -> None:
        if not _valid_source(self.door_id_source):
            raise InputError("door_id_source must be Tag, Name, GlobalId or Pset.Property.")
        if self.door_id_fallback is not None and not _valid_source(self.door_id_fallback):
            raise InputError("door_id_fallback must be null or an explicit identity source.")
        for key in ("fire_rating_pset", "fire_rating_property"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise InputError(f"{key} must be a nonempty string without surrounding whitespace.")
        if self.fire_rating_property == "id":
            raise InputError("Property name id is reserved by IfcOpenShell's property-set metadata.")
        if self.numeric_rating_unit not in ("minutes", "hours"):
            raise InputError("numeric_rating_unit must be minutes or hours.")
        if self.strict_matching is not True:
            raise InputError("P0 requires strict_matching: true (unique, case-sensitive IDs).")
        if type(self.inherit_type_properties) is not bool:
            raise InputError("inherit_type_properties must be a JSON boolean.")

    def as_dict(self) -> dict:
        return asdict(self)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"Duplicate mapping key: {key}")
        result[key] = value
    return result


def parse_mapping(data: bytes) -> Mapping:
    try:
        obj = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"Mapping must be a UTF-8 JSON object: {exc}") from exc
    if not isinstance(obj, dict):
        raise InputError("Mapping must be a JSON object.")
    unknown = set(obj) - {f.name for f in fields(Mapping)}
    if unknown:
        raise InputError(f"Unknown mapping keys: {', '.join(sorted(unknown))}")
    return Mapping(**obj)
