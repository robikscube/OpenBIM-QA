"""Deterministic machine output and escaped, offline HTML presentation."""

import csv
from html import escape
import io
import os
from pathlib import Path
import tempfile

from .models import InputError
from .validate import canonical_json


REVISION_OUTPUT_NAMES = ("revision.json", "revision.csv", "revision.html")
OUTPUT_NAMES = ("findings.json", "findings.csv", "report.html")
NOTICE = "Checks exported data against an approved schedule. Does not determine building-code compliance or fire safety."
_FIELDS = (
    "finding_id", "category", "status", "code", "door_id", "ifc_global_id", "schedule_row",
    "expected_minutes", "actual_minutes", "expected_raw", "actual_raw", "identity_source", "rating_source",
    "requirement_revision", "source_reference", "approved_by", "message", "model_evidence", "schedule_evidence",
    "source_model_sha256", "source_schedule_sha256", "source_mapping_sha256",
)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return canonical_json(value).strip()
    return str(value)


def _csv_safe(value: object) -> str:
    text = _cell(value)
    # csv.writer handles quoting, not spreadsheet formula execution. Prefix
    # unsafe cells; JSON and the evidence columns retain the original values.
    stripped = text.lstrip()
    if stripped.startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def render_csv(report: dict) -> str:
    if report.get("report_type") == "revision":
        return render_revision_csv(report)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_FIELDS, lineterminator="\n")
    writer.writeheader()
    for finding in report["findings"]:
        model, schedule = finding["model"] or {}, finding["schedule"] or {}
        metadata = schedule.get("metadata", {})
        row = {key: finding.get(key) for key in _FIELDS}
        row.update(expected_raw=schedule.get("raw_rating"), actual_raw=model.get("raw_rating"),
                   identity_source=model.get("identity_source"), rating_source=model.get("rating_source"),
                   requirement_revision=metadata.get("requirement_revision"), source_reference=metadata.get("source_reference"),
                   approved_by=metadata.get("approved_by"), model_evidence=finding["model"], schedule_evidence=finding["schedule"])
        writer.writerow({key: _csv_safe(value) for key, value in row.items()})
    return stream.getvalue()


def render_html(report: dict) -> str:
    if report.get("report_type") == "revision":
        return render_revision_html(report)
    def esc(value: object) -> str:
        return escape(_cell(value), quote=True)

    counts = "".join(f"<li>{esc(key)}: {value}</li>" for key, value in sorted(report["summary"].items()))
    diagnostics = "".join(f"<li>{esc(message)}</li>" for message in report["diagnostics"])
    rows = []
    for finding in report["findings"]:
        model, schedule = finding["model"] or {}, finding["schedule"] or {}
        cells = (finding["status"], finding["category"], finding["door_id"], finding["ifc_global_id"],
                 finding["schedule_row"], schedule.get("raw_rating"), finding["expected_minutes"],
                 model.get("raw_rating"), finding["actual_minutes"], model.get("identity_source"), model.get("rating_source"))
        evidence = {"message": finding["message"], "model": finding["model"], "schedule": finding["schedule"],
                    "source_model_sha256": finding["source_model_sha256"],
                    "source_schedule_sha256": finding["source_schedule_sha256"],
                    "source_mapping_sha256": finding["source_mapping_sha256"]}
        rows.append(f'<tr id="{esc(finding["finding_id"])}">' + "".join(f"<td>{esc(cell)}</td>" for cell in cells)
                    + f'<td><details><summary>{esc(finding["code"])}</summary><pre>{esc(evidence)}</pre>'
                    + f'<small>Evidence ID: {esc(finding["finding_id"])}</small></details></td></tr>')
    return ("<!doctype html>\n<html lang=\"en\"><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>OpenBIM QA report</title><style>body{font:16px system-ui;margin:2rem;color:#172431}"
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbc6d0;padding:.5rem;text-align:left}"
            "th{background:#eef2f5}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{overflow-wrap:anywhere}"
            ".table{overflow:auto}</style><body><h1>Door schedule reconciliation</h1>"
            f"<p>{esc(NOTICE)}</p><h2>Summary</h2><ul>{counts}</ul><h2>Run diagnostics</h2>"
            f"<ul>{diagnostics or '<li>None.</li>'}</ul><h2>Run evidence</h2>"
            f"<pre>{esc(report['run'])}</pre><h2>Findings</h2><div class=\"table\"><table><thead><tr>"
            "<th>Status</th><th>Category</th><th>Door ID</th><th>IFC GlobalId</th><th>CSV line</th>"
            "<th>Expected raw</th><th>Expected min</th><th>Actual raw</th><th>Actual min</th>"
            "<th>Identity source</th><th>Rating source</th><th>Evidence</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></div></body></html>\n")


def write_reports(report: dict, output_dir: Path, input_paths: tuple[Path, ...] = ()) -> None:
    """Replace each output atomically after rendering; refuse source collisions."""
    sources = {path.resolve() for path in input_paths}
    names = REVISION_OUTPUT_NAMES if report.get("report_type") == "revision" else OUTPUT_NAMES
    destinations = [output_dir / name for name in names]
    if any(path.resolve() in sources or (path.exists() and any(os.path.samefile(path, source) for source in sources))
           for path in destinations):
        raise InputError("Output destination would overwrite an input file; choose another --out directory.")
    contents = (canonical_json(report), render_csv(report), render_html(report))
    output_dir.mkdir(parents=True, exist_ok=True)
    for destination, content in zip(destinations, contents):
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=output_dir, delete=False) as handle:
                temp_path = Path(handle.name)
                handle.write(content)
            temp_path.replace(destination)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


_REVISION_FIELDS = (
    "report_schema_version", "checker_version",
    "change_id", "status", "ifc_global_id", "door_id", "model_changed", "raw_rating_changed",
    "normalized_rating_changed", "rating_decreased", "requirement_changed", "requirement_regression",
    "assessment_before", "assessment_after", "uncertainty_reasons", "before", "after",
    "requirement_before", "requirement_after", "candidates", "source_model_a_sha256",
    "source_model_b_sha256", "source_schedule_a_sha256", "source_schedule_b_sha256", "source_mapping_sha256",
)


def render_revision_csv(report: dict) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_REVISION_FIELDS, lineterminator="\n")
    writer.writeheader()
    for change in report["changes"]:
        row = {key: change.get(key) for key in _REVISION_FIELDS}
        row.update(report_schema_version=report.get("report_schema_version"), checker_version=report["run"].get("checker_version"))
        writer.writerow({key: _csv_safe(value) for key, value in row.items()})
    return stream.getvalue()


def render_revision_html(report: dict) -> str:
    def esc(value):
        return escape(_cell(value), quote=True)

    counts = "".join(f"<li>{esc(key)}: {esc(value)}</li>" for key, value in sorted(report["summary"].items()))
    def requirement_text(requirement):
        if requirement is None:
            return "ABSENT"
        parts = [requirement.get("state", "UNKNOWN")]
        for candidate in requirement.get("candidates", []):
            parts.append("raw=" + _cell(candidate.get("raw_rating"))
                         + "; min=" + _cell(candidate.get("rating", {}).get("minutes"))
                         + "; revision=" + _cell(candidate.get("metadata", {}).get("requirement_revision")))
        return " | ".join(parts)

    rows = []
    for change in report["changes"]:
        before, after = change.get("before") or {}, change.get("after") or {}
        cells = (change.get("status"), change.get("door_id"), change.get("ifc_global_id"),
                 before.get("raw_rating"), before.get("rating", {}).get("minutes"),
                 after.get("raw_rating"), after.get("rating", {}).get("minutes"),
                 requirement_text(change.get("requirement_before")), requirement_text(change.get("requirement_after")),
                 change.get("assessment_before"), change.get("assessment_after"),
                 change.get("rating_decreased"), change.get("requirement_regression"))
        rows.append("<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in cells)
                    + f'<td><details><summary>Evidence</summary><pre>{esc(change)}</pre></details></td></tr>')
    assessments = "".join(f"<h3>{esc(side)}</h3><pre>{esc(findings)}</pre>"
                          for side, findings in report.get("assessments", {}).items())
    return ('<!doctype html>\n<html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Door revision comparison</title><style>body{font:16px system-ui;margin:2rem}'
            'table{border-collapse:collapse}td,th{border:1px solid #bbc6d0;padding:.5rem}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere}.table{overflow:auto}</style>'
            f'<body><h1>Door revision comparison</h1><p>{esc(NOTICE)}</p><h2>Summary</h2><ul>{counts}</ul>'
            f'<h2>Run diagnostics</h2><pre>{esc(report["diagnostics"])}</pre>'
            f'<h2>Run evidence</h2><pre>{esc(report["run"])}</pre><h2>Changes</h2><div class="table"><table>'
            '<thead><tr><th>Status</th><th>Door ID</th><th>IFC GlobalId</th>'
            '<th>Before raw</th><th>Before min</th><th>After raw</th><th>After min</th>'
            '<th>Requirement before (state/raw/min/revision)</th><th>Requirement after (state/raw/min/revision)</th>'
            '<th>Assessment before</th><th>Assessment after</th><th>Rating decreased</th>'
            '<th>Requirement regression</th><th>Evidence</th></tr></thead><tbody>'
            + "".join(rows) + f'</tbody></table></div><h2>Snapshot schedule assessments</h2>{assessments}</body></html>\n')
