from hashlib import sha256

import pytest

from openbim_qa import cli
from openbim_qa.models import Extraction, InputError


def test_revision_evaluation_retains_optional_schedule_assessments(monkeypatch, fixture_dir, tmp_path, door_factory):
    before, after = tmp_path / 'before.ifc', tmp_path / 'after.ifc'
    before.write_bytes(b'before')
    after.write_bytes(b'after')
    schedule = tmp_path / 'approved.csv'
    schedule.write_text('door_id,required_rating\n001,60\nMISSING,90\n,60\n', encoding='utf-8')
    monkeypatch.setattr(cli, 'extract_ifc', lambda *_: Extraction((door_factory(),), 'IFC4', 'test-double'))
    report = cli.evaluate_revision(before, after, fixture_dir.parents[1] / 'mapping.example.json', schedule_b_path=schedule)
    assert report['report_schema_version'] == 2
    assert report['report_type'] == 'revision'
    assert report['summary'] == {'UNCHANGED': 1}
    assert report['assessments']['before'] is None
    assert len(report['assessments']['after']) == 3
    assert report['run']['source_model_a_sha256'] == sha256(b'before').hexdigest()
    assert report['run']['source_schedule_a_sha256'] is None
    assert report['run']['inputs']['model_a'] == 'before.ifc'


def test_revision_cli_writes_separate_reports(monkeypatch, fixture_dir, tmp_path, door_factory):
    monkeypatch.setattr(cli, 'extract_ifc', lambda *_: Extraction((door_factory(),), 'IFC4', 'test-double'))
    result = cli.main(['--compare-from', str(fixture_dir / 'sample.ifc'), '--compare-to', str(fixture_dir / 'sample.ifc'),
                       '--mapping', str(fixture_dir.parents[1] / 'mapping.example.json'), '--out', str(tmp_path)])
    assert result == 0
    assert {path.name for path in tmp_path.iterdir()} == {'revision.json', 'revision.csv', 'revision.html'}


@pytest.mark.parametrize('changed_side', ['before', 'after'])
def test_revision_guards_both_sources_until_extraction_finishes(monkeypatch, fixture_dir, tmp_path, changed_side):
    before, after = tmp_path / 'before.ifc', tmp_path / 'after.ifc'
    before.write_bytes(b'before')
    after.write_bytes(b'after')
    def extract(path, mapping):
        if path == after:
            (before if changed_side == 'before' else after).write_bytes(b'mutated')
        return Extraction((), 'IFC4', 'test-double')
    monkeypatch.setattr(cli, 'extract_ifc', extract)
    with pytest.raises(InputError, match='changed during extraction'):
        cli.evaluate_revision(before, after, fixture_dir.parents[1] / 'mapping.example.json')


@pytest.mark.parametrize('arguments', [[], ['--compare-from', 'a.ifc'], ['--compare-from', 'a.ifc', '--compare-to', 'b.ifc', '--schedule', 's.csv'], ['--ifc', 'a.ifc', '--schedule', 's.csv', '--schedule-to', 's.csv']])
def test_revision_cli_rejects_incomplete_or_mixed_modes(arguments):
    with pytest.raises(SystemExit) as exc:
        cli.main(arguments + ['--mapping', 'mapping.json', '--out', 'out'])
    assert exc.value.code == 2
