import csv
from html.parser import HTMLParser
import io
import json

import pytest

from openbim_qa.config import Mapping
from openbim_qa.models import InputError, ScheduleRow
from openbim_qa.report import render_csv, render_html, write_reports
from openbim_qa.validate import validate


def test_untrusted_values_are_escaped_in_html_and_safe_in_csv(door_factory, fingerprints):
    payload = '<script>alert("x")</script>&'
    doors = (door_factory(door_id="=1+1", rating=payload, ifc_global_id=payload),)
    rows = (ScheduleRow(2, "=1+1", "60", {"source_reference": payload, "approved_by": "@SUM(1,2)"}),)
    report = {"run": {"inputs": {"model": payload}}, "diagnostics": [payload], "summary": {"REVIEW REQUIRED": 1},
              "findings": validate(doors, rows, Mapping(), fingerprints)}
    html = render_html(report)
    assert payload not in html
    assert "&lt;script&gt;" in html and "&quot;x&quot;" in html
    class Parser(HTMLParser):
        scripts = 0

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.scripts += 1
    parser = Parser()
    parser.feed(html)
    assert parser.scripts == 0
    csv_row, = csv.DictReader(io.StringIO(render_csv(report)))
    assert csv_row["door_id"] == "'=1+1"
    assert csv_row["approved_by"] == "'@SUM(1,2)"
    assert csv_row["actual_raw"] == payload
    assert json.loads(csv_row["model_evidence"])["door_id"] == "=1+1"
    assert json.loads(csv_row["schedule_evidence"])["metadata"]["source_reference"] == payload


@pytest.mark.parametrize("formula", ["=1+1", "+1", "-1", "@SUM(A1)", " \t=1", "\tfoo", "\nfoo", "\rfoo"])
def test_csv_formula_neutralization(formula, door_factory, fingerprints):
    report = {"findings": validate((door_factory(rating=formula),), (ScheduleRow(2, "001", "60"),), Mapping(), fingerprints)}
    row, = csv.DictReader(io.StringIO(render_csv(report)))
    assert row["actual_raw"] == "'" + formula


def test_output_cannot_replace_an_input(tmp_path):
    source = tmp_path / "findings.json"
    source.write_text("source must remain", encoding="utf-8")
    with pytest.raises(InputError, match="overwrite an input"):
        write_reports({}, tmp_path, (source,))
    assert source.read_text(encoding="utf-8") == "source must remain"
