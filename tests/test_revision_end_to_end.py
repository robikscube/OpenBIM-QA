"""Golden public synthetic IFCs through extraction and revision CLI, no doubles."""

import json

import pytest

from openbim_qa import cli
from openbim_qa.validate import canonical_json


def test_real_revision_cli_golden(fixture_dir, tmp_path):
    pytest.importorskip("ifcopenshell", reason="Real revision parsing requires the optional IFC extra")
    output = tmp_path / "revision"
    assert cli.main([
        "--compare-from", str(fixture_dir / "revision_a.ifc"),
        "--compare-to", str(fixture_dir / "revision_b.ifc"),
        "--schedule-from", str(fixture_dir / "revision_schedule_a.csv"),
        "--schedule-to", str(fixture_dir / "revision_schedule_b.csv"),
        "--mapping", str(fixture_dir.parents[1] / "mapping.example.json"),
        "--out", str(output),
    ]) == 0
    report = json.loads((output / "revision.json").read_text(encoding="utf-8"))
    changes = report["changes"]
    expected = json.loads((fixture_dir / "expected_revision.json").read_text(encoding="utf-8"))
    projection = [{"door_id": c["door_id"], "status": c["status"],
                   "before_minutes": c["before"]["rating"]["minutes"] if c["before"] else None,
                   "after_minutes": c["after"]["rating"]["minutes"] if c["after"] else None}
                  for c in changes]
    assert report["summary"] == expected["summary"]
    assert sorted(map(canonical_json, projection)) == sorted(map(canonical_json, expected["changes"]))
    stable, = [c for c in changes if c["door_id"] == "STABLE"]
    assert stable["status"] == "UNCHANGED"
    decrease, = [c for c in changes if c["door_id"] == "DECREASE"]
    assert decrease["rating_decreased"] is True
    assert decrease["requirement_regression"] is True
    requirement, = [c for c in changes if c["door_id"] == "REQUIREMENT"]
    assert requirement["status"] == "UNCHANGED"
    assert requirement["rating_decreased"] is False
    assert requirement["requirement_regression"] is True
    recreated = [c for c in changes if c["door_id"] == "RECREATED"]
    assert len(recreated) == 2
    assert all(c["status"] == "UNCERTAIN" for c in recreated)
    assert sum(c["before"] is not None for c in changes) == 12
    assert sum(c["after"] is not None for c in changes) == 11


def test_real_revision_outputs_are_byte_deterministic_and_inputs_unchanged(fixture_dir, tmp_path):
    pytest.importorskip("ifcopenshell", reason="Real revision parsing requires the optional IFC extra")
    sources = [fixture_dir / name for name in ("revision_a.ifc", "revision_b.ifc", "revision_schedule_a.csv")]
    sources.append(fixture_dir.parents[1] / "mapping.example.json")
    original = [path.read_bytes() for path in sources]
    args = ["--compare-from", str(sources[0]), "--compare-to", str(sources[1]),
            "--schedule-from", str(sources[2]), "--schedule-to", str(sources[2]),
            "--mapping", str(sources[3])]
    for directory in (tmp_path / "first", tmp_path / "second"):
        assert cli.main(args + ["--out", str(directory)]) == 0
    for filename in ("revision.json", "revision.csv", "revision.html"):
        assert (tmp_path / "first" / filename).read_bytes() == (tmp_path / "second" / filename).read_bytes()
    assert [path.read_bytes() for path in sources] == original
