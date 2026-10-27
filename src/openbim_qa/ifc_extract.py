"""IfcOpenShell adapter, imported lazily so the functional core needs no IFC wheel."""

from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import Mapping
from .models import Door, Extraction, InputError, evidence_value
from .normalize import normalize_id


# get_psets unwraps IFC nominal values. Only these text/plain-number types can
# safely use the configured duration parser; dimensional measures need review.
_RATING_NOMINAL_TYPES = frozenset({
    "IfcLabel", "IfcText", "IfcIdentifier", "IfcInteger", "IfcReal", "IfcNumericMeasure",
})


def extract_model(model: Any, util: Any, mapping: Mapping, version: str) -> Extraction:
    """Read explicit instance properties, then optional type fallback per property.

    A present instance property (even null/blank) takes precedence over its type.
    Inspection uses get_psets(..., should_inherit=False) on each source so that
    the report can identify the actual owner instead of a merged property set.
    """
    try:
        entities = model.by_type("IfcDoor")
        guid_counts = Counter(getattr(root, "GlobalId", None) for root in model.by_type("IfcRoot"))
        schema = model.schema
    except Exception as exc:
        raise InputError(f"Cannot select IfcDoor instances: {exc}") from exc
    doors = []
    for entity in sorted(entities, key=lambda item: item.id()):
        warnings: list[str] = []
        try:
            instance_psets = util.get_psets(entity, psets_only=True, should_inherit=False)
        except Exception as exc:
            instance_psets = {}
            warnings.append(f"Instance property extraction failed: {type(exc).__name__}: {exc}")
        type_psets, type_entity = {}, None
        if mapping.inherit_type_properties:
            try:
                relations = getattr(entity, "IsTypedBy", ()) or getattr(entity, "IsDefinedBy", ())
                types = [r for r in relations if r.is_a("IfcRelDefinesByType")]
                if len(types) > 1:
                    warnings.append("Multiple type relationships; type fallback is ambiguous.")
                else:
                    type_entity = util.get_type(entity)
                    if type_entity is not None:
                        type_psets = util.get_psets(type_entity, psets_only=True, should_inherit=False)
            except Exception as exc:
                warnings.append(f"Type property extraction failed: {type(exc).__name__}: {exc}")

        # get_psets collapses names into dictionaries. Inspect the underlying
        # sources as well, so duplicate names or embedded units cannot silently
        # turn an arbitrary selected value into PASS.
        requested = {(mapping.fire_rating_pset, mapping.fire_rating_property)}
        for source in (mapping.door_id_source, mapping.door_id_fallback):
            if source and "." in source:
                requested.add(tuple(source.split(".")))
        for owner in (entity, type_entity):
            if owner is None:
                continue
            try:
                if owner is type_entity:
                    sets = list(getattr(owner, "HasPropertySets", ()) or ())
                else:
                    sets = [r.RelatingPropertyDefinition for r in (getattr(owner, "IsDefinedBy", ()) or ())
                            if r.is_a("IfcRelDefinesByProperties")]
                for pset_name, prop_name in sorted(requested):
                    relevant = [pset for pset in sets if pset.is_a("IfcPropertySet") and pset.Name == pset_name]
                    if len(relevant) > 1:
                        warnings.append(f"Ambiguous property sets on #{owner.id()}: {pset_name}.")
                    for pset in relevant:
                        props = [prop for prop in pset.HasProperties if prop.Name == prop_name]
                        if len(props) > 1:
                            warnings.append(f"Duplicate property on #{owner.id()}: {pset_name}.{prop_name}.")
                        if (pset_name, prop_name) == (mapping.fire_rating_pset, mapping.fire_rating_property):
                            if any(getattr(prop, "Unit", None) is not None for prop in props):
                                warnings.append(f"Embedded IFC rating unit on #{owner.id()}; P0 requires review of its mapping.")
                            for prop in props:
                                nominal = getattr(prop, "NominalValue", None)
                                if nominal is not None:
                                    nominal_type = nominal.is_a()
                                    if nominal_type not in _RATING_NOMINAL_TYPES:
                                        warnings.append(
                                            f"Unsupported IFC rating nominal type {nominal_type} on #{owner.id()}; "
                                            "its semantics require review before duration comparison."
                                        )
            except Exception as exc:
                warnings.append(f"Property provenance inspection failed: {type(exc).__name__}: {exc}")

        def property_value(pset: str, prop: str) -> tuple[Any, str | None, bool]:
            for source, psets in (("instance", instance_psets), ("type", type_psets)):
                values = psets.get(pset, {})
                if isinstance(values, dict) and prop in values and prop != "id":
                    owner = entity if source == "instance" else type_entity
                    return evidence_value(values[prop]), f"{source}#{owner.id()}:{pset}.{prop}", True
            return None, None, False

        def identity(source: str) -> tuple[Any, str | None]:
            if "." in source:
                value, provenance, _ = property_value(*source.split("."))
                return value, provenance
            try:
                return evidence_value(getattr(entity, source)), f"IfcDoor.{source}"
            except Exception as exc:
                warnings.append(f"Identity extraction failed for {source}: {type(exc).__name__}: {exc}")
                return None, None

        raw_id, identity_source = identity(mapping.door_id_source)
        if (raw_id is None or (isinstance(raw_id, str) and not raw_id.strip())) and mapping.door_id_fallback:
            raw_id, identity_source = identity(mapping.door_id_fallback)
        if raw_id is not None and not isinstance(raw_id, str):
            warnings.append("Configured identity is not a string; automatic matching is unavailable.")
        raw_rating, rating_source, found = property_value(mapping.fire_rating_pset, mapping.fire_rating_property)
        try:
            guid = entity.GlobalId if isinstance(entity.GlobalId, str) else None
        except Exception as exc:
            guid = None
            warnings.append(f"GlobalId extraction failed: {type(exc).__name__}: {exc}")
        if not normalize_id(guid):
            warnings.append("IFC GlobalId is missing.")
        doors.append(Door(entity.id(), guid, raw_id, raw_rating, identity_source, rating_source, found, tuple(warnings)))
    doors = [replace(door, extraction_warnings=door.extraction_warnings + ("Duplicate IFC GlobalId.",))
             if door.ifc_global_id and guid_counts[door.ifc_global_id] > 1 else door for door in doors]
    diagnostics = []
    if not doors:
        diagnostics.append("NO_IFC_DOORS: no IfcDoor instances were found; verify model/export scope.")
    elif not any(door.rating_property_found for door in doors):
        diagnostics.append("RATING_PROPERTY_NOT_FOUND: configured property was not found on any door; verify mapping/export.")
    if doors and not any(normalize_id(door.door_id) for door in doors):
        diagnostics.append("NO_USABLE_MODEL_IDS: verify configured identity source and IFC export.")
    if any(door.extraction_warnings for door in doors):
        diagnostics.append("EXTRACTION_REVIEW: one or more model records require review; inspect their evidence.")
    return Extraction(tuple(doors), schema, version, tuple(diagnostics))


def extract_ifc(path: Path, mapping: Mapping) -> Extraction:
    try:
        import ifcopenshell
        import ifcopenshell.util.element as util
    except (ImportError, OSError) as exc:
        raise InputError('IfcOpenShell is unavailable. Install with: python -m pip install -e ".[ifc]"; use a supported Python/wheel.') from exc
    try:
        model = ifcopenshell.open(str(path))
    except Exception as exc:
        raise InputError(f"Cannot read IFC file {path.name}: {exc}") from exc
    return extract_model(model, util, mapping, str(ifcopenshell.version))
