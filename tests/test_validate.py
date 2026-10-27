import pytest

from openbim_qa.config import Mapping
from openbim_qa.models import ScheduleRow
from openbim_qa.validate import canonical_json, validate


@pytest.mark.parametrize("actual,expected,status", [
    ("60", "1 hr", "PASS"), ("60", "90 min", "MISMATCH"), (None, "60", "MISSING DATA"),
    ("60", "", "MISSING DATA"), (None, "", "MISSING DATA"), ("FD60", "60", "REVIEW REQUIRED"),
    ("60", "EI60", "REVIEW REQUIRED"), ("FD60", "FD60", "REVIEW REQUIRED"),
    ("FD60", "", "REVIEW REQUIRED"), (0, "0", "PASS"), (True, "1", "REVIEW REQUIRED"),
])
def test_statuses(actual, expected, status, door_factory, fingerprints):
    finding, = validate((door_factory(rating=actual),), (ScheduleRow(2, "001", expected),), Mapping(), fingerprints)
    assert finding["status"] == status
    assert finding["source_model_sha256"] == "a" * 64
    assert finding["schedule"]["raw_rating"] == expected
    assert finding["model"]["raw_rating"] == actual
    if status == "MISMATCH":
        assert (finding["ifc_global_id"], finding["schedule_row"], finding["expected_minutes"], finding["actual_minutes"]) == ("guid-1", 2, 90, 60)


@pytest.mark.parametrize("side", ["model", "schedule", "both"])
def test_duplicate_identical_values_never_pass(side, door_factory, fingerprints):
    doors = (door_factory(1),) + ((door_factory(2),) if side in ("model", "both") else ())
    rows = (ScheduleRow(2, "001", "60"),) + ((ScheduleRow(3, " 001 ", "60"),) if side in ("schedule", "both") else ())
    findings = validate(doors, rows, Mapping(), fingerprints)
    assert len(findings) == len(doors) + len(rows)
    assert all(f["status"] == "REVIEW REQUIRED" and f["code"] == "DUPLICATE_ID" for f in findings)
    assert all((f["model"] is None) != (f["schedule"] is None) for f in findings)


def test_missing_ids_never_join_each_other(door_factory, fingerprints):
    findings = validate((door_factory(door_id=" "),), (ScheduleRow(2, "", "60"),), Mapping(), fingerprints)
    assert len(findings) == 2
    assert {f["code"] for f in findings} == {"MISSING_MODEL_ID", "MISSING_SCHEDULE_ID"}
    assert all(f["status"] == "MISSING DATA" for f in findings)


def test_unmatched_categories_are_separate(door_factory, fingerprints):
    findings = validate((door_factory(door_id="A"),), (ScheduleRow(2, "B", "60"),), Mapping(), fingerprints)
    assert {f["status"] for f in findings} == {"UNMATCHED SCHEDULE", "UNREFERENCED MODEL"}


def test_unmatched_with_extraction_error_keeps_category(door_factory, fingerprints):
    findings = validate((door_factory(door_id="A", extraction_warnings=("Read failed",)),), (), Mapping(), fingerprints)
    assert findings[0]["status"] == "REVIEW REQUIRED"
    assert findings[0]["category"] == "unreferenced_model"


def test_guid_ambiguity_and_extraction_errors_block_pass(door_factory, fingerprints):
    doors = (door_factory(1, "A", ifc_global_id="duplicate"), door_factory(2, "B", ifc_global_id="duplicate"),
             door_factory(3, "C", ifc_global_id=None), door_factory(4, "D", extraction_warnings=("Cannot read properties",)))
    rows = tuple(ScheduleRow(index + 2, key, "60") for index, key in enumerate("ABCD"))
    findings = validate(doors, rows, Mapping(), fingerprints)
    assert len(findings) == 4
    assert all(f["status"] == "REVIEW REQUIRED" for f in findings)


def test_deterministic_under_record_order(door_factory, fingerprints):
    doors = (door_factory(1, "B"), door_factory(2, " A "), door_factory(3, "A"), door_factory(4, None))
    rows = (ScheduleRow(2, "A", "60"), ScheduleRow(3, "B", "90"), ScheduleRow(4, "C", "60"))
    first = canonical_json(validate(doors, rows, Mapping(), fingerprints))
    second = canonical_json(validate(tuple(reversed(doors)), tuple(reversed(rows)), Mapping(), fingerprints))
    assert first == second


def test_every_input_has_exactly_one_evidence_record(door_factory, fingerprints):
    doors = tuple(door_factory(i, key) for i, key in enumerate(["A", "A", None, "B", "C"], 1))
    rows = tuple(ScheduleRow(i, key, "60") for i, key in enumerate(["A", "", "B", "D", "D"], 2))
    findings = validate(doors, rows, Mapping(), fingerprints)
    assert sorted(f["model"]["ifc_entity_id"] for f in findings if f["model"]) == [d.ifc_entity_id for d in doors]
    assert sorted(f["schedule_row"] for f in findings if f["schedule"]) == [r.schedule_row for r in rows]


def test_blank_globalid_is_not_usable(door_factory, fingerprints):
    findings = validate((door_factory(ifc_global_id=" \t"),), (ScheduleRow(2, "001", "60"),), Mapping(), fingerprints)
    assert findings[0]["status"] == "REVIEW REQUIRED"


@pytest.mark.parametrize("raw", [float("nan"), float("inf"), -float("inf"), ["60"], {"value": "60"}])
def test_unsupported_canonical_values_produce_valid_json(raw, door_factory, fingerprints):
    findings = validate((door_factory(rating=raw),), (ScheduleRow(2, "001", "60"),), Mapping(), fingerprints)
    assert findings[0]["status"] == "REVIEW REQUIRED"
    assert "UNSUPPORTED_RATING" in canonical_json(findings)
