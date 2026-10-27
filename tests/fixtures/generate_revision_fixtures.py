"""Regenerate original CC0-1.0 metadata-only revision fixtures; no BIM input.

Run with Python from any directory. The golden expectations are maintained
separately by hand so they do not inherit the comparison implementation.
"""

from pathlib import Path


HERE = Path(__file__).parent
DOORS_A = [
    (10, 10, "STABLE", "60"), (11, 11, "DECREASE", "90"),
    (12, 12, "FORMAT", "1 hr"), (13, 13, "REQUIREMENT", "60"),
    (14, 14, "MISSING", "60"), (15, 15, "RECREATED", "60"),
    (16, 16, "DUP-MARK", "60"), (17, 17, "DUP-MARK", "90"),
    (18, 18, "REMOVED", "60"), (20, 20, "DUP-GUID-1", "60"),
    (21, 20, "DUP-GUID-2", "60"), (22, None, "MISSING-GUID", "60"),
]
DOORS_B = [
    (110, 10, "STABLE", "60"), (111, 11, "DECREASE", "60"),
    (112, 12, "FORMAT", "60 min"), (113, 13, "REQUIREMENT", "60"),
    (114, 14, "MISSING", None), (115, 115, "RECREATED", "60"),
    (116, 16, "DUP-MARK", "60"), (117, 17, "DUP-MARK", "90"),
    (119, 19, "ADDED", "60"), (120, 20, "DUP-GUID-1", "60"),
    (122, None, "MISSING-GUID", "60"),
]


def write_model(name, doors):
    lines = [
        "ISO-10303-21;", "HEADER;",
        "FILE_DESCRIPTION(('Original synthetic revision fixture; deliberately invalid identities; no real building.'),'2;1');",
        f"FILE_NAME('{name}','2026-10-26T00:00:00',('OpenBIM QA'),('Synthetic test data'),'OpenBIM QA','OpenBIM QA','CC0-1.0');",
        "FILE_SCHEMA(('IFC4'));", "ENDSEC;", "DATA;",
    ]
    for number, guid_number, mark, rating in doors:
        guid = f"'{guid_number:022}'" if guid_number is not None else "$"
        lines.append(f"#{number}=IFCDOOR({guid},$,'Synthetic {mark}',$,$,$,$,'{mark}',$,$,$,$,$);")
        if rating is not None:
            prop, pset, rel = number + 1000, number + 2000, number + 3000
            lines.extend([
                f"#{prop}=IFCPROPERTYSINGLEVALUE('FireRating',$,IFCLABEL('{rating}'),$);",
                f"#{pset}=IFCPROPERTYSET('{pset:022}',$,'Pset_DoorCommon',$,(#{prop}));",
                f"#{rel}=IFCRELDEFINESBYPROPERTIES('{rel:022}',$,$,$,(#{number}),#{pset});",
            ])
    lines.extend(["ENDSEC;", "END-ISO-10303-21;", ""])
    (HERE / name).write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write_model("revision_a.ifc", DOORS_A)
    write_model("revision_b.ifc", DOORS_B)
