"""Index both sides; only a unique nonempty ID on each side creates a pair."""

from collections import defaultdict
from dataclasses import dataclass

from .models import Door, ScheduleRow
from .normalize import normalize_id


@dataclass(frozen=True)
class MatchGroup:
    door_id: str | None
    models: tuple[Door, ...]
    schedule: tuple[ScheduleRow, ...]
    kind: str


def match_records(doors: tuple[Door, ...], rows: tuple[ScheduleRow, ...]) -> tuple[MatchGroup, ...]:
    model_index, schedule_index = defaultdict(list), defaultdict(list)
    groups = []
    for record in doors:
        key = normalize_id(record.door_id)
        if key is None:
            groups.append(MatchGroup(None, (record,), (), "missing_identity"))
        else:
            model_index[key].append(record)
    for record in rows:
        key = normalize_id(record.door_id)
        if key is None:
            groups.append(MatchGroup(None, (), (record,), "missing_identity"))
        else:
            schedule_index[key].append(record)
    for key in sorted(model_index.keys() | schedule_index.keys()):
        models, schedule = tuple(model_index[key]), tuple(schedule_index[key])
        if len(models) > 1 or len(schedule) > 1:
            kind = "ambiguous_identity"
        elif not models:
            kind = "unmatched_schedule"
        elif not schedule:
            kind = "unreferenced_model"
        else:
            kind = "matched"
        groups.append(MatchGroup(key, models, schedule, kind))
    return tuple(groups)
