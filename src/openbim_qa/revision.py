"""Deterministic, conservative comparison of door-property snapshots.

Only a unique, usable GlobalId pairs records. Marks suggest review candidates;
they never establish cross-revision identity. STEP ids and provenance locations
are evidence, not semantic changes to a door.
"""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256

from .config import Mapping
from .models import Door, ScheduleRow, InputError, evidence_value
from .normalize import normalize_id, normalize_rating
from .validate import canonical_json


def compare_revisions(doors_a: tuple[Door, ...], doors_b: tuple[Door, ...], mapping: Mapping,
                      rows_a: tuple[ScheduleRow, ...] | None = None,
                      rows_b: tuple[ScheduleRow, ...] | None = None,
                      fingerprints: dict[str, str | None] | None = None) -> list[dict]:
    """Compare exported door properties; ratings never establish legal compliance."""
    allowed = {'source_model_a_sha256', 'source_model_b_sha256', 'source_schedule_a_sha256',
               'source_schedule_b_sha256', 'source_mapping_sha256'}
    if set(fingerprints or {}) - allowed:
        raise InputError('Unknown revision fingerprint key.')
    findings = []

    def evidence(door):
        if door is None:
            return None
        item = evidence_value(asdict(door))
        item['normalized_door_id'] = normalize_id(door.door_id)
        item['rating'] = normalize_rating(door.raw_rating, mapping.numeric_rating_unit).as_dict()
        return item

    def requirement(door, rows, doors):
        if rows is None or door is None:
            return None
        key = normalize_id(door.door_id)
        candidates = []
        for row in rows:
            if key is not None and normalize_id(row.door_id) == key:
                item = asdict(row)
                item['normalized_door_id'] = key
                item['rating'] = normalize_rating(row.raw_rating, mapping.numeric_rating_unit).as_dict()
                candidates.append(item)
        candidates.sort(key=canonical_json)
        if key is None or sum(normalize_id(d.door_id) == key for d in doors) != 1 or len(candidates) > 1:
            state = 'AMBIGUOUS'
        elif not candidates:
            state = 'UNMATCHED'
        else:
            state = {'ok': 'EXPLICIT', 'missing': 'MISSING', 'unsupported': 'UNSUPPORTED'}[candidates[0]['rating']['state']]
        return {'state': state, 'candidates': candidates}

    def requirement_signature(req):
        return (req['state'], sorted((canonical_json({k: v for k, v in row.items() if k != 'schedule_row'})
                                     for row in req['candidates'])))

    def assessment(model, req):
        if not model or not req or req['state'] != 'EXPLICIT' or model['rating']['state'] != 'ok' or model['extraction_warnings'] or not model['rating_property_found']:
            return 'UNKNOWN'
        actual, expected = model['rating']['minutes'], req['candidates'][0]['rating']['minutes']
        return 'MET' if actual == expected else ('BELOW' if actual < expected else 'ABOVE')

    counts = [Counter(d.ifc_global_id for d in doors if normalize_id(d.ifc_global_id))
              for doors in (doors_a, doors_b)]
    def usable(d, side):
        return bool(normalize_id(d.ifc_global_id)) and counts[side][d.ifc_global_id] == 1 and not any(
            'globalid' in warning.lower() for warning in d.extraction_warnings)

    paired = {d.ifc_global_id for d in doors_a if usable(d, 0)} & {
        d.ifc_global_id for d in doors_b if usable(d, 1)}
    pairs = [(next(d for d in doors_a if d.ifc_global_id == guid),
              next(d for d in doors_b if d.ifc_global_id == guid)) for guid in sorted(paired)]
    pairs += [(d, None) for d in doors_a if d.ifc_global_id not in paired]
    pairs += [(None, d) for d in doors_b if d.ifc_global_id not in paired]
    for before, after in pairs:
        a, b = evidence(before), evidence(after)
        door = after or before
        reasons, candidates = [], []
        if before is None or after is None:
            side = 1 if after else 0
            opposite = doors_a if after else doors_b
            candidates = [{'revision': 'A' if after else 'B', 'ifc_global_id': d.ifc_global_id,
                           'ifc_entity_id': d.ifc_entity_id, 'door_id': normalize_id(d.door_id)}
                          for d in opposite if normalize_id(door.door_id) is not None
                          and normalize_id(d.door_id) == normalize_id(door.door_id)]
            if candidates:
                reasons.append('Same Mark appears in opposite revision without a stable unique GlobalId; review identity.')
            if not usable(door, side) or any(
                    d.ifc_global_id == door.ifc_global_id and not usable(d, 1 - side) for d in opposite):
                reasons.append('Missing or duplicate IFC GlobalId; no cross-revision pairing.')
        identity_uncertain = bool(reasons)
        both = bool(a and b)
        raw_changed = a['raw_rating'] != b['raw_rating'] if both else None
        changed = (a['door_id'], a['raw_rating']) != (b['door_id'], b['raw_rating']) if both else None
        for revision, model in (('A', a), ('B', b)):
            if model and (model['rating']['state'] != 'ok' or model['extraction_warnings'] or not model['rating_property_found']):
                reasons.append(f'Revision {revision}: rating evidence is missing, unsupported or has extraction warnings; no rating conclusion.')
        comparable = both and all(item['rating']['state'] == 'ok' and not item['extraction_warnings']
                                  and item['rating_property_found'] for item in (a, b))
        result = {'status': ('UNCERTAIN' if identity_uncertain else ('MODIFIED' if changed else 'UNCHANGED')) if both
                  else ('UNCERTAIN' if identity_uncertain else ('ADDED' if after else 'REMOVED')),
                  'ifc_global_id': door.ifc_global_id, 'door_id': normalize_id(door.door_id),
                  'before': a, 'after': b, 'model_changed': changed,
                  'raw_rating_changed': raw_changed,
                  'normalized_rating_changed': a['rating']['minutes'] != b['rating']['minutes'] if comparable else None,
                  'rating_decreased': b['rating']['minutes'] < a['rating']['minutes'] if comparable else None,
                  'requirement_before': None, 'requirement_after': None,
                  'requirement_changed': None, 'assessment_before': 'UNKNOWN', 'assessment_after': 'UNKNOWN',
                  'requirement_regression': None, 'uncertainty_reasons': reasons,
                  'candidates': sorted(candidates, key=canonical_json), **(fingerprints or {})}
        req_a, req_b = requirement(before, rows_a, doors_a), requirement(after, rows_b, doors_b)
        assess_a = assessment(a, req_a) if before and usable(before, 0) else 'UNKNOWN'
        assess_b = assessment(b, req_b) if after and usable(after, 1) else 'UNKNOWN'
        for revision, req in (('A', req_a), ('B', req_b)):
            if req and req['state'] != 'EXPLICIT':
                reasons.append(f"Revision {revision}: approved requirement {req['state'].lower()}; no requirement assessment.")
        result.update(requirement_before=req_a, requirement_after=req_b,
                      assessment_before=assess_a, assessment_after=assess_b,
                      requirement_changed=(requirement_signature(req_a) != requirement_signature(req_b))
                      if req_a is not None and req_b is not None else None,
                      requirement_regression=(assess_a in ('MET', 'ABOVE') and assess_b == 'BELOW')
                      if both and assess_a != 'UNKNOWN' and assess_b != 'UNKNOWN' else None)
        result['change_id'] = sha256(canonical_json(result).encode('utf-8')).hexdigest()
        findings.append(result)
    return sorted(findings, key=lambda r: (r['door_id'] or '', r['status'], r['ifc_global_id'] or '', r['change_id']))
