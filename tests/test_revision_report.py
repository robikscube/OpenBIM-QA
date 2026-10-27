import csv
import io
import json

import pytest

from openbim_qa.models import InputError
from openbim_qa.report import render_csv, render_html, write_reports


def revision_report():
    return {'report_type': 'revision', 'summary': {'UNCERTAIN': 1}, 'diagnostics': ['<script>bad()</script>'],
            'run': {}, 'changes': [{'status': 'UNCERTAIN', 'door_id': '=1+1',
                                   'before': {'raw_rating': '<script>bad()</script>'},
                                   'uncertainty_reasons': ['<script>bad()</script>']}],
            'assessments': {'before': None, 'after': [{'door_id': '<script>bad()</script>'}]}}


def test_revision_renders_untrusted_evidence_safely():
    report = revision_report()
    html = render_html(report)
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    row, = csv.DictReader(io.StringIO(render_csv(report)))
    assert row['door_id'] == "'=1+1"
    assert json.loads(row['before']) == report['changes'][0]['before']


@pytest.mark.parametrize('link_kind', ['direct', 'hardlink', 'symlink'])
def test_revision_outputs_refuse_input_aliases(tmp_path, link_kind):
    source = tmp_path / ('revision.json' if link_kind == 'direct' else 'original.ifc')
    source.write_bytes(b'input preserved')
    destination = tmp_path / 'revision.json'
    if link_kind != 'direct':
        try:
            if link_kind == 'hardlink':
                destination.hardlink_to(source)
            else:
                destination.symlink_to(source)
        except OSError as exc:
            pytest.skip(f'File link unavailable: {exc}')
    with pytest.raises(InputError, match='overwrite an input'):
        write_reports(revision_report(), tmp_path, (source,))
    assert source.read_bytes() == b'input preserved'


def test_revision_csv_includes_explicit_machine_schema_and_checker_version():
    report = revision_report()
    report['report_schema_version'] = 2
    report['run']['checker_version'] = '0.2.0'
    report['changes'][0]['rating_decreased'] = False
    row, = csv.DictReader(io.StringIO(render_csv(report)))
    assert row['report_schema_version'] == '2'
    assert row['checker_version'] == '0.2.0'
    assert row['rating_decreased'] == 'False'
    assert row['requirement_regression'] == ''


def test_revision_html_shows_rating_and_requirement_changes_before_expanding_evidence():
    report = revision_report()
    change = report['changes'][0]
    change.update(before={'raw_rating': '90 min', 'rating': {'minutes': 90}},
                  after={'raw_rating': '60 min', 'rating': {'minutes': 60}},
                  requirement_before={'state': 'EXPLICIT', 'candidates': [{'raw_rating': '90', 'rating': {'minutes': 90}, 'metadata': {'requirement_revision': 'R1'}}]},
                  requirement_after={'state': 'AMBIGUOUS', 'candidates': []})
    from html.parser import HTMLParser
    class VisibleText(HTMLParser):
        hidden = 0
        visible = []
        def handle_starttag(self, tag, attrs):
            if tag == 'details':
                self.hidden += 1
        def handle_endtag(self, tag):
            if tag == 'details':
                self.hidden -= 1
        def handle_data(self, data):
            if not self.hidden:
                self.visible.append(data)
    parser = VisibleText()
    parser.feed(render_html(report))
    text = ' '.join(parser.visible)
    assert 'Before raw' in text and 'After min' in text
    assert '90 min' in text and '60 min' in text
    assert 'EXPLICIT' in text and 'AMBIGUOUS' in text and 'R1' in text
