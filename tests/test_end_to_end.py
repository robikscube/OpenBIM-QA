"""Core golden contract + CLI orchestration; separate real IFC integration gate."""

import json
from pathlib import Path
import sys

import pytest

from openbim_qa import cli
from openbim_qa.config import Mapping
from openbim_qa.models import Door, Extraction
from openbim_qa.schedule import parse_schedule
from openbim_qa.validate import canonical_json, validate


def synthetic_canonical_doors():
    """Explicit test data, NOT an IFC parser or evidence of real extraction."""
    cases = [(10, "D-PASS", "60 min"), (11, "D-MISMATCH", "60"), (12, "D-MISSING", None),
             (13, "D-REVIEW", "FD60"), (14, "D-DUP", "60"), (15, " D-DUP ", "90"),
             (16, None, "60"), (17, "D-MODEL-ONLY", "60")]
    return tuple(Door(number, f"{number:022}", key, rating, "IfcDoor.Tag",
                      f"instance#{number}:Pset_DoorCommon.FireRating" if number != 12 else None,
                      number != 12) for number, key, rating in cases)


def assert_golden(findings, fixture_dir):
    expected = json.loads((fixture_dir / "expected_findings.json").read_text(encoding="utf-8"))
    keys = expected[0].keys()
    projected = [{key: finding[key] for key in keys} for finding in findings]
    assert sorted(map(canonical_json, projected)) == sorted(map(canonical_json, expected))


def test_pure_core_golden_contract(fixture_dir, fingerprints):
    rows = parse_schedule((fixture_dir / "approved_doors.csv").read_bytes())
    findings = validate(synthetic_canonical_doors(), rows, Mapping(), fingerprints)
    assert_golden(findings, fixture_dir)


def test_cli_orchestration_with_explicit_test_double_is_deterministic(monkeypatch, fixture_dir, tmp_path, capsys):
    monkeypatch.setattr(cli, "extract_ifc", lambda *_: Extraction(synthetic_canonical_doors(), "IFC4", "test-double"))
    inputs = [fixture_dir / "sample.ifc", fixture_dir / "approved_doors.csv", fixture_dir.parents[1] / "mapping.example.json"]
    before = [path.read_bytes() for path in inputs]
    first, second = tmp_path / "first", tmp_path / "second"
    for output in (first, second):
        assert cli.main(["--ifc", str(inputs[0]), "--schedule", str(inputs[1]), "--mapping", str(inputs[2]), "--out", str(output)]) == 0
    for name in ("findings.json", "findings.csv", "report.html"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert [path.read_bytes() for path in inputs] == before
    report = json.loads((first / "findings.json").read_text(encoding="utf-8"))
    assert report["run"]["ifcopenshell_version"] == "test-double"
    assert report["summary"] == {"PASS": 1, "MISMATCH": 1, "MISSING DATA": 3, "REVIEW REQUIRED": 6,
                                 "UNMATCHED SCHEDULE": 1, "UNREFERENCED MODEL": 1}
    for finding in report["findings"]:
        for key in ("source_model_sha256", "source_schedule_sha256", "source_mapping_sha256"):
            assert finding[key] == report["run"][key]
            assert len(finding[key]) == 64
    assert_golden(report["findings"], fixture_dir)
    assert "Reports written" in capsys.readouterr().out


def test_real_ifc_golden_and_byte_determinism_when_library_available(fixture_dir, tmp_path):
    pytest.importorskip("ifcopenshell", reason="IfcOpenShell wheel unavailable; synthetic STEP parsing and real end-to-end pending")
    args = ["--ifc", str(fixture_dir / "sample.ifc"), "--schedule", str(fixture_dir / "approved_doors.csv"),
            "--mapping", str(fixture_dir.parents[1] / "mapping.example.json")]
    for directory in (tmp_path / "first", tmp_path / "second"):
        assert cli.main(args + ["--out", str(directory)]) == 0
    report = json.loads((tmp_path / "first" / "findings.json").read_text(encoding="utf-8"))
    assert report["run"]["model_door_count"] == 8
    assert report["run"]["ifc_schema"] == "IFC4"
    assert_golden(report["findings"], fixture_dir)
    for name in ("findings.json", "findings.csv", "report.html"):
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()


def test_cli_dependency_blocker_does_not_create_reports(monkeypatch, fixture_dir, tmp_path, capsys):
    monkeypatch.setitem(sys.modules, "ifcopenshell", None)
    result = cli.main(["--ifc", str(fixture_dir / "sample.ifc"), "--schedule", str(fixture_dir / "approved_doors.csv"),
                       "--mapping", str(fixture_dir.parents[1] / "mapping.example.json"), "--out", str(tmp_path / "out")])
    assert result == 2
    assert "IfcOpenShell is unavailable" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_cli_invalid_input_and_unexpected_exit_codes(monkeypatch, tmp_path, capsys):
    args = ["--ifc", "absent.ifc", "--schedule", "absent.csv", "--mapping", "absent.json", "--out", str(tmp_path)]
    assert cli.main(args) == 2
    assert "Input/output error" in capsys.readouterr().err
    def fail(*_):
        raise RuntimeError("deliberate test failure")
    monkeypatch.setattr(cli, "evaluate", fail)
    assert cli.main(args) == 3
    assert "Unexpected runtime failure" in capsys.readouterr().err


def test_cli_rejects_source_that_changes_during_extraction(monkeypatch, fixture_dir, tmp_path):
    model = tmp_path / "model.ifc"
    model.write_bytes(b"original input")
    def changing_input(*_):
        model.write_bytes(b"changed input")
        return Extraction((), "IFC4", "test-double")
    monkeypatch.setattr(cli, "extract_ifc", changing_input)
    from openbim_qa.models import InputError
    with pytest.raises(InputError, match="changed during extraction"):
        cli.evaluate(model, fixture_dir / "approved_doors.csv", fixture_dir.parents[1] / "mapping.example.json")


def test_multiple_revision_labels_are_reported(monkeypatch, fixture_dir, tmp_path):
    schedule = tmp_path / "schedule.csv"
    schedule.write_text("door_id,required_rating,requirement_revision\nA,60,R1\nB,60,R2\n", encoding="utf-8")
    monkeypatch.setattr(cli, "extract_ifc", lambda *_: Extraction((), "IFC4", "test-double", ("NO_IFC_DOORS",)))
    report = cli.evaluate(fixture_dir / "sample.ifc", schedule, fixture_dir.parents[1] / "mapping.example.json")
    assert any("MULTIPLE_REQUIREMENT_REVISIONS" in message for message in report["diagnostics"])
    assert any("NO_IFC_DOORS" in message for message in report["diagnostics"])
