"""Pure reconciliation with full per-record evidence and deterministic ordering."""

from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json

from .config import Mapping
from .match import match_records
from .models import Door, ScheduleRow, evidence_value
from .normalize import normalize_id, normalize_rating


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def validate(doors: tuple[Door, ...], rows: tuple[ScheduleRow, ...], mapping: Mapping,
             fingerprints: dict[str, str]) -> list[dict]:
    """All records appear once. Duplicates emit separate, explicitly unpaired rows."""
    findings = []
    guid_counts = Counter(door.ifc_global_id for door in doors if door.ifc_global_id)

    def emit(kind: str, key: str | None, door: Door | None, row: ScheduleRow | None,
             duplicate_sides: list[str]) -> None:
        actual = normalize_rating(door.raw_rating if door else None, mapping.numeric_rating_unit)
        expected = normalize_rating(row.raw_rating if row else None, mapping.numeric_rating_unit)
        warnings = list(door.extraction_warnings) if door else []
        if door and not normalize_id(door.ifc_global_id):
            warnings.append("IFC GlobalId is missing.")
        if door and guid_counts[door.ifc_global_id] > 1:
            warnings.append("Duplicate IFC GlobalId.")
        if door and door.door_id is not None and not isinstance(door.door_id, str):
            warnings.append("Configured identity is not a string.")
        warnings = sorted(set(warnings))
        if kind == "ambiguous_identity":
            status, code = "REVIEW REQUIRED", "DUPLICATE_ID"
            message = f"Duplicate normalized ID on {', '.join(duplicate_sides)} side(s); no pairing was attempted."
        elif warnings:
            status, code = "REVIEW REQUIRED", "MODEL_DATA_REVIEW"
            message = "Model evidence has extraction or identity problems; no rating conclusion is available."
        elif kind == "missing_identity":
            status = "MISSING DATA"
            code = "MISSING_MODEL_ID" if door else "MISSING_SCHEDULE_ID"
            message = "Door ID is absent; no pairing was attempted."
        elif kind == "unmatched_schedule":
            status, code = "UNMATCHED SCHEDULE", "SCHEDULE_ONLY"
            message = "Approved schedule ID has no corresponding model door in this export."
        elif kind == "unreferenced_model":
            status, code = "UNREFERENCED MODEL", "MODEL_ONLY"
            message = "Model door ID has no approved schedule row; no approved rating conclusion is available."
        elif "unsupported" in (actual.state, expected.state):
            status, code = "REVIEW REQUIRED", "UNSUPPORTED_RATING"
            message = "At least one rating is unsupported; inspect both raw values and parser reasons."
        elif "missing" in (actual.state, expected.state):
            status, code = "MISSING DATA", "MISSING_RATING"
            message = "At least one rating is absent from the supplied export/schedule."
        elif actual.minutes == expected.minutes:
            status, code = "PASS", "RATING_MATCH"
            message = "Explicit rating durations agree with the approved schedule."
        else:
            status, code = "MISMATCH", "RATING_MISMATCH"
            message = "Explicit rating durations disagree with the approved schedule."
        model_evidence = evidence_value(asdict(door)) if door else None
        if model_evidence is not None:
            model_evidence["extraction_warnings"] = warnings
            model_evidence["normalized_door_id"] = normalize_id(door.door_id)
            model_evidence["rating"] = actual.as_dict()
        schedule_evidence = asdict(row) if row else None
        if schedule_evidence is not None:
            schedule_evidence["normalized_door_id"] = normalize_id(row.door_id)
            schedule_evidence["rating"] = expected.as_dict()
        finding = {
            "category": kind, "code": code, "status": status, "message": message,
            "door_id": key, "ifc_global_id": door.ifc_global_id if door else None,
            "schedule_row": row.schedule_row if row else None,
            "requirement_revision": row.metadata.get("requirement_revision") if row else None,
            "expected_minutes": expected.minutes, "actual_minutes": actual.minutes,
            "model": model_evidence, "schedule": schedule_evidence,
            **fingerprints,
        }
        finding["finding_id"] = sha256(canonical_json(finding).encode("utf-8")).hexdigest()
        findings.append(finding)

    for group in match_records(doors, rows):
        duplicate_sides = []
        if len(group.models) > 1:
            duplicate_sides.append("model")
        if len(group.schedule) > 1:
            duplicate_sides.append("schedule")
        if group.kind == "matched":
            emit(group.kind, group.door_id, group.models[0], group.schedule[0], [])
        else:
            for door in group.models:
                emit(group.kind, group.door_id, door, None, duplicate_sides)
            for row in group.schedule:
                emit(group.kind, group.door_id, None, row, duplicate_sides)
    return sorted(findings, key=lambda f: (
        f["door_id"] or "", f["status"], f["ifc_global_id"] or "",
        f["schedule_row"] or 0, f["model"]["ifc_entity_id"] if f["model"] else 0, f["finding_id"],
    ))
