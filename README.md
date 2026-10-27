# OpenBIM QA

**Local-first IFC door-rating quality assurance.**

OpenBIM QA compares exported `IfcDoor` fire ratings with an approved CSV door schedule and produces traceable discrepancy reports. It also compares two IFC revisions to identify changed doors and ratings without silently matching uncertain identities.

## Features

- Read IFC door IDs and configured fire-rating properties with [IfcOpenShell](https://ifcopenshell.org/).
- Compare against approved schedules; flag matches, mismatches, missing data, duplicates, and ambiguous values.
- Compare IFC revisions: added, removed, modified, unchanged, or uncertain doors; rating decreases and requirement regressions.
- Generate deterministic **HTML, CSV, and JSON** reports with source-file SHA-256 fingerprints.
- Run entirely offline; input models are not modified.

## Install and test

Requires **Python 3.11–3.13** and a supported IfcOpenShell wheel.

```sh
python -m venv .venv
# Activate: .venv\Scripts\Activate.ps1 (Windows PowerShell)
#      or: source .venv/bin/activate (macOS/Linux)
python -m pip install -e ".[ifc,test]"
python -m pytest -q
```

## Try the examples

**Check one IFC against a schedule:**

```sh
openbim-qa --ifc tests/fixtures/sample.ifc --schedule tests/fixtures/approved_doors.csv --mapping mapping.example.json --out outputs/demo
```

Open `outputs/demo/report.html`. Machine-readable results are in `findings.json` and `findings.csv`.

**Compare two IFC revisions and their schedules:**

```sh
openbim-qa --compare-from tests/fixtures/revision_a.ifc --compare-to tests/fixtures/revision_b.ifc --schedule-from tests/fixtures/revision_schedule_a.csv --schedule-to tests/fixtures/revision_schedule_b.csv --mapping mapping.example.json --out outputs/revision-demo
```

Open `outputs/revision-demo/revision.html`. The two schedule options are optional.

## Scope and status

**v1 (dry):** Single-model checks and revision comparison implemented and tested using original synthetic IFC fixtures. **v2 (wet):** Validation against real Revit-exported IFCs, export settings, and actual model revisions remains pending.

This tool checks **consistency with an approved schedule**, **not** fire-code compliance or building safety. Missing or ambiguous data must not be treated as a pass. Actual export property mappings must be verified for each project.

[Synthetic fixture provenance and regeneration notes](tests/fixtures/README.md)
