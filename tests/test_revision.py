from openbim_qa.config import Mapping
from openbim_qa.revision import compare_revisions


def test_stable_guid_rating_decrease(door_factory):
    before = door_factory(rating='90')
    after = door_factory(rating='60')
    result, = compare_revisions((before,), (after,), Mapping())
    assert result['status'] == 'MODIFIED'
    assert result['rating_decreased'] is True
    assert result['before']['rating']['minutes'] == 90
    assert result['requirement_regression'] is None


def test_stable_guid_pairs_independently_of_order_and_step_ids(door_factory):
    a = (door_factory(1, 'A'), door_factory(2, 'B'))
    b = (door_factory(99, 'B', ifc_global_id='guid-2'), door_factory(98, 'A', ifc_global_id='guid-1'))
    results = compare_revisions(a, b, Mapping())
    assert [r['status'] for r in results] == ['UNCHANGED', 'UNCHANGED']
    assert all(r['before']['ifc_global_id'] == r['after']['ifc_global_id'] for r in results)


def test_added_removed_and_recreated_identity_remain_unpaired(door_factory):
    a = (door_factory(1, 'RECREATED'), door_factory(2, 'REMOVED'))
    b = (door_factory(3, 'RECREATED'), door_factory(4, 'ADDED'))
    results = compare_revisions(a, b, Mapping())
    assert sorted(r['status'] for r in results) == ['ADDED', 'REMOVED', 'UNCERTAIN', 'UNCERTAIN']
    uncertain = [r for r in results if r['status'] == 'UNCERTAIN']
    assert all((r['before'] is None) != (r['after'] is None) for r in uncertain)
    assert all(r['candidates'] and r['rating_decreased'] is None for r in uncertain)


def test_duplicate_and_missing_guids_and_extractor_collision_never_pair(door_factory):
    a = (door_factory(1, 'A'), door_factory(2, 'B', ifc_global_id='guid-1'),
         door_factory(3, 'C', ifc_global_id=None),
         door_factory(4, 'D', extraction_warnings=('Duplicate IFC GlobalId.',)))
    b = (door_factory(1, 'A'), door_factory(4, 'D'))
    results = compare_revisions(a, b, Mapping())
    assert len(results) == 6
    assert all(r['status'] == 'UNCERTAIN' for r in results)
    assert all(r['rating_decreased'] is None for r in results)


def test_requirement_only_regression_is_separate_from_model_change(door_factory):
    from openbim_qa.models import ScheduleRow
    a = (ScheduleRow(2, '001', '60', {'requirement_revision': 'A', 'source_reference': 'approved'}),)
    b = (ScheduleRow(9, '001', '90', {'requirement_revision': 'B'}),)
    result, = compare_revisions((door_factory(),), (door_factory(),), Mapping(), a, b)
    assert result['status'] == 'UNCHANGED'
    assert result['rating_decreased'] is False
    assert result['requirement_changed'] is True
    assert result['requirement_regression'] is True
    assert result['assessment_before'] == 'MET'
    assert result['assessment_after'] == 'BELOW'
    assert result['requirement_before']['candidates'][0]['metadata']['source_reference'] == 'approved'


def test_bad_rating_evidence_never_concludes_decrease_or_regression(door_factory):
    from openbim_qa.models import ScheduleRow
    for bad in (door_factory(rating=None), door_factory(rating='FD60'),
                door_factory(rating='30', extraction_warnings=('Property extraction failed',)),
                door_factory(rating='30', rating_property_found=False)):
        result, = compare_revisions((door_factory(),), (bad,), Mapping(),
                                   (ScheduleRow(2, '001', '60'),), (ScheduleRow(2, '001', '60'),))
        assert result['rating_decreased'] is None
        assert result['normalized_rating_changed'] is None
        assert result['requirement_regression'] is None
        assert result['assessment_after'] == 'UNKNOWN'
        assert result['uncertainty_reasons']


def test_raw_only_and_duplicate_marks_preserve_model_pairing(door_factory):
    from openbim_qa.models import ScheduleRow
    a = (door_factory(1, 'D', '1 hr'), door_factory(2, 'D', '60'))
    b = (door_factory(1, 'D', '60 min'), door_factory(2, 'D', '60'))
    results = compare_revisions(a, b, Mapping(), (ScheduleRow(2, 'D', '60'),), (ScheduleRow(2, 'D', '60'),))
    assert {r['status'] for r in results} == {'MODIFIED', 'UNCHANGED'}
    first = next(r for r in results if r['status'] == 'MODIFIED')
    assert first['raw_rating_changed'] is True
    assert first['normalized_rating_changed'] is False
    assert all(r['requirement_before']['state'] == 'AMBIGUOUS' for r in results)
    assert all(r['assessment_before'] == 'UNKNOWN' and r['uncertainty_reasons'] for r in results)


def test_ambiguous_schedule_candidates_retained_and_output_deterministic(door_factory):
    from openbim_qa.models import ScheduleRow
    from openbim_qa.validate import canonical_json
    doors = (door_factory(1, 'A'), door_factory(2, 'B'))
    rows = (ScheduleRow(2, 'A', '60'), ScheduleRow(3, ' A ', '90'), ScheduleRow(4, 'B', 'FD60'))
    first = compare_revisions(doors, doors, Mapping(), rows, rows, {'source_model_a_sha256': 'a'})
    second = compare_revisions(tuple(reversed(doors)), doors, Mapping(), tuple(reversed(rows)), rows,
                               {'source_model_a_sha256': 'a'})
    assert canonical_json(first) == canonical_json(second)
    assert len(first[0]['requirement_before']['candidates']) == 2
    assert all(r['requirement_regression'] is None for r in first)
    assert first[0]['source_model_a_sha256'] == 'a'


def test_fingerprints_cannot_override_classification(door_factory):
    import pytest
    from openbim_qa.models import InputError
    with pytest.raises(InputError, match='fingerprint'):
        compare_revisions((door_factory(),), (door_factory(),), Mapping(), fingerprints={'status': 'PASS'})


def test_requirement_line_reordering_is_evidence_not_requirement_change(door_factory):
    from openbim_qa.models import ScheduleRow
    result, = compare_revisions((door_factory(),), (door_factory(),), Mapping(),
                               (ScheduleRow(2, '001', '60'),), (ScheduleRow(19, '001', '60'),))
    assert result['requirement_changed'] is False
    assert result['requirement_after']['candidates'][0]['schedule_row'] == 19


def test_previous_rating_above_requirement_can_regress_below(door_factory):
    from openbim_qa.models import ScheduleRow
    rows = (ScheduleRow(2, '001', '90'),)
    result, = compare_revisions((door_factory(rating='120'),), (door_factory(rating='60'),), Mapping(), rows, rows)
    assert result['assessment_before'] == 'ABOVE'
    assert result['requirement_regression'] is True


def test_missing_guid_blocks_snapshot_requirement_assessment(door_factory):
    from openbim_qa.models import ScheduleRow
    rows = (ScheduleRow(2, '001', '60'),)
    results = compare_revisions((door_factory(ifc_global_id=None),), (door_factory(ifc_global_id=None),), Mapping(), rows, rows)
    assert len(results) == 2
    assert all(r['assessment_before'] == r['assessment_after'] == 'UNKNOWN' for r in results)


def test_rating_decrease_while_meeting_requirement_is_not_regression(door_factory):
    from openbim_qa.models import ScheduleRow
    rows = (ScheduleRow(2, '001', '60'),)
    result, = compare_revisions((door_factory(rating='90'),), (door_factory(rating='60'),), Mapping(), rows, rows)
    assert result['rating_decreased'] is True
    assert result['requirement_regression'] is False


def test_requirement_metadata_change_is_preserved_separately(door_factory):
    from openbim_qa.models import ScheduleRow
    a = (ScheduleRow(2, '001', '60', {'requirement_revision': 'A'}),)
    b = (ScheduleRow(2, '001', '60', {'requirement_revision': 'B'}),)
    result, = compare_revisions((door_factory(),), (door_factory(),), Mapping(), a, b)
    assert result['requirement_changed'] is True
    assert result['model_changed'] is False
    assert result['requirement_regression'] is False
