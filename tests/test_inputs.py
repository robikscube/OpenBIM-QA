import json

import pytest

from openbim_qa.config import Mapping, parse_mapping
from openbim_qa.models import InputError
from openbim_qa.schedule import parse_schedule


def test_mapping_defaults_and_example(fixture_dir):
    mapping = parse_mapping((fixture_dir.parents[1] / "mapping.example.json").read_bytes())
    assert mapping == Mapping()


@pytest.mark.parametrize("obj", [
    [], {"typo": "Tag"}, {"door_id_source": "Mark"}, {"door_id_source": 1},
    {"door_id_source": "Pset."}, {"door_id_fallback": ""}, {"numeric_rating_unit": "seconds"},
    {"strict_matching": False}, {"strict_matching": 1}, {"inherit_type_properties": "false"},
    {"fire_rating_pset": " "}, {"fire_rating_property": None},
    {"fire_rating_property": "id"}, {"door_id_source": "Identity.id"},
])
def test_bad_mapping(obj):
    with pytest.raises(InputError):
        parse_mapping(json.dumps(obj).encode())


@pytest.mark.parametrize("raw", [b'{"door_id_source":"Tag","door_id_source":"Name"}', b"\xff", b"{"])
def test_bad_mapping_bytes(raw):
    with pytest.raises(InputError):
        parse_mapping(raw)


def test_csv_preserves_ids_raw_metadata_bom_and_physical_lines():
    rows = parse_schedule(b'\xef\xbb\xbfdoor_id,required_rating,source_reference\r\n001,1 hr,"line 1\r\nline 2"\r\n\r\n 002 ,90 min,ref\r\n')
    assert [(r.schedule_row, r.door_id, r.raw_rating) for r in rows] == [(2, "001", "1 hr"), (5, " 002 ", "90 min")]
    assert rows[0].metadata == {"source_reference": "line 1\r\nline 2"}


def test_blank_cells_and_duplicate_ids_are_retained_for_checking():
    rows = parse_schedule(b"door_id,required_rating\n,\n001,60\n001,60\n")
    assert len(rows) == 3
    assert rows[0].door_id == "" and rows[0].raw_rating == ""


@pytest.mark.parametrize("raw,fragment", [
    (b"", "empty"), (b"door_id,required_rating\n", "no data"),
    (b"door_id,wrong\nA,60\n", "required_rating"),
    (b"door_id,door_id,required_rating\nA,A,60\n", "duplicate"),
    (b"door_id,required_rating,\nA,60,\n", "empty column"),
    (b"door_id,required_rating\nA,60,extra\n", "line 2"),
    (b"door_id,required_rating\nA\n", "line 2"),
    (b'door_id,required_rating\nA,"60\n', "Malformed CSV"),
    (b"door_id,required_rating\n\xff,60\n", "UTF-8"),
    (b"door_id,required_rating\nA,\x0060\n", "NUL"),
])
def test_bad_csv_is_actionable(raw, fragment):
    with pytest.raises(InputError, match=fragment):
        parse_schedule(raw)
