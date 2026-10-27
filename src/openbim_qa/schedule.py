"""UTF-8 CSV ingestion with physical source line numbers and no coercion."""

import csv
import io

from .models import InputError, ScheduleRow


def parse_schedule(data: bytes) -> tuple[ScheduleRow, ...]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise InputError("Schedule must be UTF-8 CSV (UTF-8 BOM is accepted).") from exc
    if "\x00" in text:
        raise InputError("Schedule contains NUL characters; export a UTF-8 CSV.")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if not header:
            raise InputError("Schedule is empty; expected door_id,required_rating columns.")
        if len(set(header)) != len(header) or any(not name for name in header):
            raise InputError("Schedule has duplicate or empty column names.")
        missing = {"door_id", "required_rating"} - set(header)
        if missing:
            raise InputError(f"Missing schedule columns: {', '.join(sorted(missing))}")
        rows = []
        while True:
            line = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            if not values:  # Empty physical lines are not schedule records.
                continue
            if len(values) != len(header):
                raise InputError(f"Schedule line {line}: expected {len(header)} cells, got {len(values)}.")
            record = dict(zip(header, values))
            rows.append(ScheduleRow(line, record.pop("door_id"), record.pop("required_rating"), record))
    except csv.Error as exc:
        raise InputError(f"Malformed CSV near line {reader.line_num}: {exc}") from exc
    if not rows:
        raise InputError("Schedule contains a header but no data rows.")
    return tuple(rows)
