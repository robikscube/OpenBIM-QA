# Synthetic fixtures

`sample.ifc` is an original, hand-authored IFC4 STEP metadata fixture for this
repository, dedicated to the public domain under **CC0-1.0**. It describes no
real building, contains no geometry, and is **not a Revit export**. The CSV is
also original synthetic data under CC0-1.0; its approval/revision labels are test
strings, not an actual project approval.

Eight doors exercise a duration match, a mismatch, a missing property, an
unsupported classification, duplicate model IDs, missing identity, and a model
door with no schedule row. The CSV adds a schedule-only ID, a missing ID, and
duplicate schedule IDs. `expected_findings.json` is the manually specified
13-finding semantic contract (an unordered projection, excluding file hashes
and evidence IDs). Detailed provenance and determinism have separate tests.

Real parsing of this STEP fixture and type-inheritance integration tests require
the optional IfcOpenShell wheel. Both were verified locally against version
0.8.5. Without the wheel these tests skip explicitly; a skipped test is not verification on that environment.

## Synthetic revision fixtures

`revision_a.ifc` (12 doors), `revision_b.ifc` (11 doors), the two
`revision_schedule_*.csv` files and `expected_revision.json` are also original
synthetic **CC0-1.0** data. The metadata-only IFC files intentionally contain
invalid missing/duplicate GlobalIds to test recovery; they are parser fixtures,
not schema-valid building deliverables or Revit exports.

Regenerate the IFC files with
`python tests/fixtures/generate_revision_fixtures.py`. The generator uses only
explicit test data and Python's standard library. Golden expectations are
written separately by hand, not derived from the comparison implementation.

Cases cover stable GUIDs despite changed STEP numbers, addition/removal,
raw-only formatting, a normalized rating decrease, a stricter requirement with
an unchanged model, missing rating, recreated GUID, duplicate Marks, duplicate
GUID on only one side, missing GUID, unmatched schedule rows and duplicate
schedule rows. Seven records pair by GUID; nine remain unpaired, producing
16 changes: ADDED 1, REMOVED 1, MODIFIED 3, UNCHANGED 4, UNCERTAIN 7.
