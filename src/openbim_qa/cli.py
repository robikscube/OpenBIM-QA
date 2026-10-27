"""Single-model and revision CLI orchestration. Success means evaluated, including discrepancy findings."""

import argparse
from collections import Counter
from hashlib import sha256
from pathlib import Path
import sys

from . import __version__
from .config import parse_mapping
from .ifc_extract import extract_ifc
from .models import InputError
from .report import NOTICE, write_reports
from .schedule import parse_schedule
from .validate import validate


def evaluate(model_path: Path, schedule_path: Path, mapping_path: Path) -> dict:
    model_bytes = model_path.read_bytes()
    schedule_bytes = schedule_path.read_bytes()
    mapping_bytes = mapping_path.read_bytes()
    mapping = parse_mapping(mapping_bytes)
    rows = parse_schedule(schedule_bytes)
    fingerprints = {
        "source_model_sha256": sha256(model_bytes).hexdigest(),
        "source_schedule_sha256": sha256(schedule_bytes).hexdigest(),
        "source_mapping_sha256": sha256(mapping_bytes).hexdigest(),
    }
    extraction = extract_ifc(model_path, mapping)
    if sha256(model_path.read_bytes()).hexdigest() != fingerprints["source_model_sha256"]:
        raise InputError("IFC input changed during extraction; rerun with a stable source file.")
    findings = validate(extraction.doors, rows, mapping, fingerprints)
    revisions = sorted({row.metadata["requirement_revision"].strip() for row in rows
                        if row.metadata.get("requirement_revision", "").strip()})
    diagnostics = list(extraction.diagnostics)
    if len(revisions) > 1:
        diagnostics.append("MULTIPLE_REQUIREMENT_REVISIONS: schedule rows contain different revision labels; review source schedule.")
    diagnostics.append("MODEL_SCHEDULE_REVISION_ALIGNMENT_UNVERIFIED: confirm these inputs belong together; IFC revision is not inferred.")
    return {
        "report_schema_version": 1,
        "notice": NOTICE,
        "run": {
            "checker_version": __version__, "ifcopenshell_version": extraction.ifcopenshell_version,
            "ifc_schema": extraction.schema, "mapping": mapping.as_dict(),
            "inputs": {"model": model_path.name, "schedule": schedule_path.name, "mapping": mapping_path.name},
            "model_door_count": len(extraction.doors), "schedule_row_count": len(rows),
            "requirement_revisions": revisions, **fingerprints,
        },
        "diagnostics": sorted(diagnostics),
        "summary": dict(sorted(Counter(f["status"] for f in findings).items())),
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=NOTICE)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--ifc", type=Path, help="Input IFC model")
    parser.add_argument("--schedule", type=Path, help="Approved UTF-8 CSV")
    parser.add_argument("--mapping", required=True, type=Path, help="Explicit JSON mapping")
    parser.add_argument("--out", required=True, type=Path, help="Report directory (findings.json/findings.csv/report.html or revision.json/revision.csv/revision.html)")
    parser.add_argument("--compare-from", type=Path, help="Earlier IFC snapshot")
    parser.add_argument("--compare-to", type=Path, help="Later IFC snapshot")
    parser.add_argument("--schedule-from", type=Path, help="Optional earlier approved CSV")
    parser.add_argument("--schedule-to", type=Path, help="Optional later approved CSV")
    args = parser.parse_args(argv)
    comparison = args.compare_from is not None or args.compare_to is not None
    if comparison:
        if args.compare_from is None or args.compare_to is None:
            parser.error("comparison requires both --compare-from and --compare-to")
        if args.ifc is not None or args.schedule is not None:
            parser.error("comparison uses --schedule-from/--schedule-to; omit --ifc and --schedule")
    elif args.ifc is None or args.schedule is None or args.schedule_from is not None or args.schedule_to is not None:
        parser.error("single-model evaluation requires --ifc and --schedule; comparison requires --compare-from and --compare-to")
    try:
        if comparison:
            report = evaluate_revision(args.compare_from, args.compare_to, args.mapping, args.schedule_from, args.schedule_to)
            inputs = tuple(path for path in (args.compare_from, args.compare_to, args.mapping, args.schedule_from, args.schedule_to) if path is not None)
        else:
            report = evaluate(args.ifc, args.schedule, args.mapping)
            inputs = (args.ifc, args.schedule, args.mapping)
        write_reports(report, args.out, inputs)
    except (InputError, OSError) as exc:
        print(f"Input/output error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unexpected runtime failure ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 3
    print("; ".join(f"{key}: {value}" for key, value in report["summary"].items()))
    print(f"Reports written to {args.out}")
    return 0


def evaluate_revision(model_a_path: Path, model_b_path: Path, mapping_path: Path,
                      schedule_a_path: Path | None = None, schedule_b_path: Path | None = None) -> dict:
    """Compare two snapshots and independently assess any supplied schedules."""
    from .revision import compare_revisions

    paths = {"model_a": model_a_path, "model_b": model_b_path, "mapping": mapping_path,
             "schedule_a": schedule_a_path, "schedule_b": schedule_b_path}
    data = {key: path.read_bytes() if path is not None else None for key, path in paths.items()}
    fingerprints = {f"source_{key}_sha256": sha256(value).hexdigest() if value is not None else None
                    for key, value in data.items()}
    mapping = parse_mapping(data["mapping"])
    rows = {side: parse_schedule(data[f"schedule_{side}"]) if data[f"schedule_{side}"] is not None else None
            for side in ("a", "b")}
    snapshots = {"a": extract_ifc(model_a_path, mapping), "b": extract_ifc(model_b_path, mapping)}
    # Recheck both after all extraction: B's extraction can overlap a change to A.
    for side in ("a", "b"):
        if sha256(paths[f"model_{side}"].read_bytes()).hexdigest() != fingerprints[f"source_model_{side}_sha256"]:
            raise InputError("IFC input changed during extraction; rerun with stable source files.")
    changes = compare_revisions(snapshots["a"].doors, snapshots["b"].doors, mapping,
                                rows["a"], rows["b"], fingerprints)
    assessments, diagnostics, revisions = {}, [], {}
    for side, label in (("a", "before"), ("b", "after")):
        snapshot, schedule = snapshots[side], rows[side]
        side_hashes = {"source_model_sha256": fingerprints[f"source_model_{side}_sha256"],
                       "source_schedule_sha256": fingerprints[f"source_schedule_{side}_sha256"],
                       "source_mapping_sha256": fingerprints["source_mapping_sha256"]}
        assessments[label] = validate(snapshot.doors, schedule, mapping, side_hashes) if schedule is not None else None
        revisions[side] = sorted({row.metadata.get("requirement_revision", "").strip() for row in schedule or ()
                                  if row.metadata.get("requirement_revision", "").strip()})
        diagnostics.extend(f"{label}: {message}" for message in snapshot.diagnostics)
        if len(revisions[side]) > 1:
            diagnostics.append(f"{label}: MULTIPLE_REQUIREMENT_REVISIONS: schedule rows contain different revision labels; review source schedule.")
        if schedule is not None:
            diagnostics.append(f"{label}: MODEL_SCHEDULE_REVISION_ALIGNMENT_UNVERIFIED: confirm these inputs belong together; IFC revision is not inferred.")
    return {"report_schema_version": 2, "report_type": "revision", "notice": NOTICE,
            "run": {"checker_version": __version__, "mapping": mapping.as_dict(), **fingerprints,
                    "inputs": {key: path.name if path is not None else None for key, path in paths.items()},
                    "ifc_schema": {side: snapshot.schema for side, snapshot in snapshots.items()},
                    "ifcopenshell_version": {side: snapshot.ifcopenshell_version for side, snapshot in snapshots.items()},
                    "model_door_count": {side: len(snapshot.doors) for side, snapshot in snapshots.items()},
                    "schedule_row_count": {side: len(schedule) if schedule is not None else None for side, schedule in rows.items()},
                    "requirement_revisions": revisions},
            "diagnostics": sorted(diagnostics), "summary": dict(sorted(Counter(change["status"] for change in changes).items())),
            "changes": changes, "assessments": assessments}
