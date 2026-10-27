from openbim_qa.match import match_records
from openbim_qa.models import ScheduleRow


def test_only_trimmed_unique_exact_ids_pair(door_factory):
    doors = (door_factory(1, " 001 "), door_factory(2, "a"), door_factory(3, None))
    rows = (ScheduleRow(2, "001", "60"), ScheduleRow(3, "A", "60"), ScheduleRow(4, " ", "60"))
    groups = match_records(doors, rows)
    assert [g.door_id for g in groups if g.kind == "matched"] == ["001"]
    assert {g.kind for g in groups} == {"matched", "missing_identity", "unmatched_schedule", "unreferenced_model"}


def test_duplicates_never_collapse_or_pair(door_factory):
    doors = (door_factory(1, "A"), door_factory(2, " A "), door_factory(3, "B"))
    rows = (ScheduleRow(2, "A", "60"), ScheduleRow(3, "B", "60"), ScheduleRow(4, " B ", "60"))
    groups = match_records(doors, rows)
    assert all(g.kind == "ambiguous_identity" for g in groups)
    assert sum(len(g.models) for g in groups) == len(doors)
    assert sum(len(g.schedule) for g in groups) == len(rows)
