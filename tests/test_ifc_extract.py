"""Adapter contract tests; real IfcOpenShell tests are explicitly skipped if absent."""

import sys
from types import SimpleNamespace

import pytest

from openbim_qa.config import Mapping
from openbim_qa.ifc_extract import extract_ifc, extract_model
from openbim_qa.models import InputError


class Entity:
    def __init__(self, number, tag="001", guid="guid-1", psets=None, door_type=None):
        self.number, self.Tag, self.GlobalId = number, tag, guid
        self.Name = "Name is not a guessed Mark"
        self.psets = psets or {}
        self.door_type = door_type
        self.IsTypedBy = ()

    def id(self):
        return self.number


class Util:
    @staticmethod
    def get_psets(entity, *, psets_only, should_inherit):
        assert psets_only is True
        assert should_inherit is False
        return entity.psets

    @staticmethod
    def get_type(entity):
        return entity.door_type


def extract(entities, mapping=Mapping(), util=Util):
    class Model:
        schema = "IFC4"

        def by_type(self, kind):
            assert kind in ("IfcDoor", "IfcRoot")
            return entities
    return extract_model(Model(), util, mapping, "test-double")


def test_explicit_instance_properties_and_no_guessed_fallback():
    entity = Entity(1, tag=None, psets={"Pset_DoorCommon": {"FireRating": "1 hr"}})
    door, = extract([entity]).doors
    assert door.door_id is None
    assert door.raw_rating == "1 hr"
    assert door.rating_source == "instance#1:Pset_DoorCommon.FireRating"
    assert door.extraction_warnings == ()


def test_explicit_fallback_and_property_identity():
    entity = Entity(1, tag=" ", psets={"Identity": {"Mark": "001"}})
    door, = extract([entity], Mapping(door_id_fallback="Identity.Mark")).doors
    assert door.door_id == "001"
    assert door.identity_source == "instance#1:Identity.Mark"


def test_type_inheritance_is_opt_in_and_provenance_is_exact():
    door_type = Entity(9, psets={"Pset_DoorCommon": {"FireRating": "90 min"}, "Identity": {"Mark": "T-01"}})
    entity = Entity(1, door_type=door_type)
    assert extract([entity]).doors[0].raw_rating is None
    door, = extract([entity], Mapping(inherit_type_properties=True)).doors
    assert door.raw_rating == "90 min"
    assert door.rating_source == "type#9:Pset_DoorCommon.FireRating"
    door, = extract([entity], Mapping(inherit_type_properties=True, door_id_source="Identity.Mark")).doors
    assert door.door_id == "T-01" and door.identity_source == "type#9:Identity.Mark"


@pytest.mark.parametrize("instance_value", [None, "", "60 min"])
def test_instance_presence_overrides_type_even_when_empty(instance_value):
    door_type = Entity(9, psets={"Pset_DoorCommon": {"FireRating": "90 min"}})
    entity = Entity(1, psets={"Pset_DoorCommon": {"FireRating": instance_value}}, door_type=door_type)
    door, = extract([entity], Mapping(inherit_type_properties=True)).doors
    assert door.raw_rating == instance_value
    assert door.rating_source == "instance#1:Pset_DoorCommon.FireRating"


def test_recoverable_property_error_is_not_reported_as_plain_missing():
    class BrokenUtil(Util):
        @staticmethod
        def get_psets(*args, **kwargs):
            raise RuntimeError("bad property")
    result = extract([Entity(1)], util=BrokenUtil)
    assert "Instance property extraction failed" in result.doors[0].extraction_warnings[0]
    assert any("EXTRACTION_REVIEW" in message for message in result.diagnostics)


def test_globalid_missing_and_duplicates_are_reviewable():
    result = extract([Entity(1), Entity(2), Entity(3, guid=None)])
    assert "Duplicate IFC GlobalId." in result.doors[0].extraction_warnings
    assert "Duplicate IFC GlobalId." in result.doors[1].extraction_warnings
    assert "IFC GlobalId is missing." in result.doors[2].extraction_warnings


def test_numeric_identity_and_non_scalar_ratings_remain_evidence():
    door, = extract([Entity(1, tag=1, psets={"Pset_DoorCommon": {"FireRating": ["60", "90"]}})]).doors
    assert door.door_id == 1 and door.raw_rating == ["60", "90"]
    assert door.extraction_warnings


def test_run_diagnostics_for_empty_model_and_absent_property():
    assert any("NO_IFC_DOORS" in msg for msg in extract([]).diagnostics)
    assert any("RATING_PROPERTY_NOT_FOUND" in msg for msg in extract([Entity(1)]).diagnostics)


def test_multiple_type_relationships_block_type_fallback():
    entity = Entity(1)
    entity.IsTypedBy = (SimpleNamespace(is_a=lambda kind: True), SimpleNamespace(is_a=lambda kind: True))
    result = extract([entity], Mapping(inherit_type_properties=True))
    assert "Multiple type relationships" in result.doors[0].extraction_warnings[0]


@pytest.mark.parametrize("problem", ["duplicate_pset", "duplicate_property", "embedded_unit"])
def test_collapsed_property_ambiguities_and_units_cannot_silently_pass(problem):
    prop = SimpleNamespace(Name="FireRating", Unit="hour" if problem == "embedded_unit" else None)
    pset = SimpleNamespace(Name="Pset_DoorCommon", is_a=lambda kind: kind == "IfcPropertySet",
                           HasProperties=[prop, prop] if problem == "duplicate_property" else [prop])
    relation = SimpleNamespace(is_a=lambda kind: kind == "IfcRelDefinesByProperties", RelatingPropertyDefinition=pset)
    entity = Entity(1, psets={"Pset_DoorCommon": {"FireRating": "60"}})
    entity.IsDefinedBy = [relation, relation] if problem == "duplicate_pset" else [relation]
    door, = extract([entity]).doors
    assert door.extraction_warnings
    from openbim_qa.validate import validate
    from openbim_qa.models import ScheduleRow
    finding, = validate((door,), (ScheduleRow(2, "001", "60"),), Mapping(), {})
    assert finding["status"] == "REVIEW REQUIRED"


def test_guid_duplicates_with_non_door_roots_are_flagged():
    door = Entity(1)
    class Model:
        schema = "IFC4"

        def by_type(self, kind):
            return [door] if kind == "IfcDoor" else [door, Entity(2)]
    result = extract_model(Model(), Util, Mapping(), "test-double")
    assert "Duplicate IFC GlobalId." in result.doors[0].extraction_warnings


def test_type_read_failure_is_recoverable_and_review_required():
    class BrokenTypeUtil(Util):
        @staticmethod
        def get_type(entity):
            raise RuntimeError("bad type relationship")
    result = extract([Entity(1)], Mapping(inherit_type_properties=True), util=BrokenTypeUtil)
    assert any("Type property extraction failed" in message for message in result.doors[0].extraction_warnings)


def test_missing_dependency_has_actionable_error(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "ifcopenshell", None)
    with pytest.raises(InputError, match="Install with"):
        extract_ifc(tmp_path / "model.ifc", Mapping())


def test_corrupt_ifc_when_library_available(tmp_path):
    pytest.importorskip("ifcopenshell", reason="IfcOpenShell wheel unavailable; real parsing not verified")
    path = tmp_path / "bad.ifc"
    path.write_text("not an IFC file", encoding="utf-8")
    with pytest.raises(InputError, match="Cannot read IFC"):
        extract_ifc(path, Mapping())


def test_real_type_fallback_and_instance_precedence_when_library_available(tmp_path):
    ifc = pytest.importorskip("ifcopenshell", reason="IfcOpenShell wheel unavailable; real type inheritance not verified")
    from openbim_qa.models import ScheduleRow
    from openbim_qa.validate import validate

    model = ifc.file(schema="IFC4")
    door = model.create_entity("IfcDoor", GlobalId="0000000000000000000001", Tag="001")
    prop = model.create_entity("IfcPropertySingleValue", Name="FireRating", NominalValue=model.create_entity("IfcLabel", "90 min"))
    pset = model.create_entity("IfcPropertySet", GlobalId="0000000000000000000002", Name="Pset_DoorCommon", HasProperties=[prop])
    door_type = model.create_entity("IfcDoorType", GlobalId="0000000000000000000003", HasPropertySets=[pset],
                                    PredefinedType="DOOR", OperationType="NOTDEFINED", ParameterTakesPrecedence=False)
    model.create_entity("IfcRelDefinesByType", GlobalId="0000000000000000000004", RelatedObjects=[door], RelatingType=door_type)
    path = tmp_path / "type.ifc"
    model.write(str(path))
    assert extract_ifc(path, Mapping()).doors[0].raw_rating is None
    extracted = extract_ifc(path, Mapping(inherit_type_properties=True)).doors[0]
    assert extracted.raw_rating == "90 min" and extracted.rating_source.startswith("type#")
    instance_prop = model.create_entity("IfcPropertySingleValue", Name="FireRating", NominalValue=None)
    instance_pset = model.create_entity("IfcPropertySet", GlobalId="0000000000000000000005", Name="Pset_DoorCommon", HasProperties=[instance_prop])
    model.create_entity("IfcRelDefinesByProperties", GlobalId="0000000000000000000006", RelatedObjects=[door], RelatingPropertyDefinition=instance_pset)
    model.write(str(path))
    extracted = extract_ifc(path, Mapping(inherit_type_properties=True)).doors[0]
    assert extracted.raw_rating is None and extracted.rating_source.startswith("instance#")
    finding, = validate((extracted,), (ScheduleRow(2, "001", "90"),),
                        Mapping(inherit_type_properties=True), {})
    assert finding["status"] == "MISSING DATA"
    assert finding["actual_minutes"] is None
    assert finding["model"]["raw_rating"] is None


@pytest.mark.parametrize("owner", ["instance", "type"])
@pytest.mark.parametrize("nominal_type,value,expected_status", [
    ("IfcLabel", "60", "PASS"),
    ("IfcText", "60 min", "PASS"),
    ("IfcIdentifier", "1 hr", "PASS"),
    ("IfcInteger", 60, "PASS"),
    ("IfcReal", 60.0, "PASS"),
    ("IfcNumericMeasure", 60.0, "PASS"),
    ("IfcTimeMeasure", 60.0, "REVIEW REQUIRED"),
    ("IfcLengthMeasure", 60.0, "REVIEW REQUIRED"),
    ("IfcCountMeasure", 60.0, "REVIEW REQUIRED"),
    ("IfcAreaMeasure", 60.0, "REVIEW REQUIRED"),
    (None, None, "MISSING DATA"),
])
def test_real_rating_nominal_types_preserve_semantics_before_flattening(
        tmp_path, fingerprints, owner, nominal_type, value, expected_status):
    ifc = pytest.importorskip("ifcopenshell", reason="IfcOpenShell wheel unavailable; nominal-type semantics not verified")
    from openbim_qa.models import ScheduleRow
    from openbim_qa.report import render_html
    from openbim_qa.validate import canonical_json, validate

    model = ifc.file(schema="IFC4")
    door = model.create_entity("IfcDoor", GlobalId="0000000000000000000001", Tag="001")
    prop = model.create_entity("IfcPropertySingleValue", Name="FireRating",
                               NominalValue=model.create_entity(nominal_type, value) if nominal_type else None)
    pset = model.create_entity("IfcPropertySet", GlobalId="0000000000000000000002",
                               Name="Pset_DoorCommon", HasProperties=[prop])
    if owner == "instance":
        model.create_entity("IfcRelDefinesByProperties", GlobalId="0000000000000000000003",
                            RelatedObjects=[door], RelatingPropertyDefinition=pset)
    else:
        door_type = model.create_entity("IfcDoorType", GlobalId="0000000000000000000003", HasPropertySets=[pset],
                                        PredefinedType="DOOR", OperationType="NOTDEFINED", ParameterTakesPrecedence=False)
        model.create_entity("IfcRelDefinesByType", GlobalId="0000000000000000000004",
                            RelatedObjects=[door], RelatingType=door_type)
    path = tmp_path / "nominal-type.ifc"
    model.write(str(path))
    mapping = Mapping(inherit_type_properties=owner == "type")
    extracted = extract_ifc(path, mapping)
    finding, = validate(extracted.doors, (ScheduleRow(2, "001", "60"),), mapping, fingerprints)
    assert extracted.doors[0].raw_rating == value
    assert extracted.doors[0].rating_source.startswith(owner + "#")
    assert finding["status"] == expected_status
    if expected_status == "REVIEW REQUIRED":
        assert any(nominal_type in warning for warning in extracted.doors[0].extraction_warnings)
        # Warning evidence survives both machine output and the review report.
        assert nominal_type in canonical_json(finding)
        report = {"run": {}, "diagnostics": extracted.diagnostics,
                  "summary": {expected_status: 1}, "findings": [finding]}
        assert nominal_type in render_html(report)
    else:
        assert extracted.doors[0].extraction_warnings == ()


@pytest.mark.parametrize("inherit_type_properties", [False, True])
def test_real_unsupported_type_nominal_with_explicit_instance_rating(
        tmp_path, fingerprints, inherit_type_properties):
    ifc = pytest.importorskip("ifcopenshell", reason="IfcOpenShell wheel unavailable; nominal-type semantics not verified")
    from openbim_qa.models import ScheduleRow
    from openbim_qa.validate import canonical_json, validate

    model = ifc.file(schema="IFC4")
    door = model.create_entity("IfcDoor", GlobalId="0000000000000000000001", Tag="001")
    type_prop = model.create_entity("IfcPropertySingleValue", Name="FireRating",
                                    NominalValue=model.create_entity("IfcLengthMeasure", 90.0))
    type_pset = model.create_entity("IfcPropertySet", GlobalId="0000000000000000000002",
                                    Name="Pset_DoorCommon", HasProperties=[type_prop])
    door_type = model.create_entity("IfcDoorType", GlobalId="0000000000000000000003", HasPropertySets=[type_pset],
                                    PredefinedType="DOOR", OperationType="NOTDEFINED", ParameterTakesPrecedence=False)
    model.create_entity("IfcRelDefinesByType", GlobalId="0000000000000000000004",
                        RelatedObjects=[door], RelatingType=door_type)
    instance_prop = model.create_entity("IfcPropertySingleValue", Name="FireRating",
                                        NominalValue=model.create_entity("IfcLabel", "60"))
    instance_pset = model.create_entity("IfcPropertySet", GlobalId="0000000000000000000005",
                                        Name="Pset_DoorCommon", HasProperties=[instance_prop])
    model.create_entity("IfcRelDefinesByProperties", GlobalId="0000000000000000000006",
                        RelatedObjects=[door], RelatingPropertyDefinition=instance_pset)
    path = tmp_path / "instance-and-type.ifc"
    model.write(str(path))
    mapping = Mapping(inherit_type_properties=inherit_type_properties)
    extracted = extract_ifc(path, mapping)
    finding, = validate(extracted.doors, (ScheduleRow(2, "001", "60"),), mapping, fingerprints)
    assert finding["model"]["raw_rating"] == "60"
    assert finding["model"]["rating_source"].startswith("instance#")
    if inherit_type_properties:
        assert finding["status"] == "REVIEW REQUIRED"
        assert any(f"IfcLengthMeasure on #{door_type.id()}" in warning
                   for warning in finding["model"]["extraction_warnings"])
        assert "IfcLengthMeasure" in canonical_json(finding)
    else:
        assert finding["status"] == "PASS"
        assert finding["model"]["extraction_warnings"] == []
