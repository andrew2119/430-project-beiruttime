"""Deterministic synthetic boundary examples, never connected completion proof."""
from uuid import UUID


def identifier(value):
    return str(UUID(int=value))


def source():
    return dict(subject_id=identifier(1), watch_id=identifier(2), organization_id=identifier(3),
                source_revision=1, scope_revision=1, quote_id=identifier(4), quote_revision=1,
                policy_revision=1, buyer_id=identifier(5), assigned_actor_ids=[identifier(6), identifier(7)],
                accepted_lines=[dict(line_id=identifier(i), required=True, title_en='Repair', title_ar='إصلاح',
                                     amount_minor=10000) for i in (8, 9)], currency='USD', commitment_current=True, custody_current=True,
                payment_held=True, scope_accepted=True, incident_open=False, material_line_ids=[],
                quality_result='missing', quality_work_revision=0, quality_scope_revision=0,
                quality_independent=False, responsible_actor_id=identifier(7), next_action_en='Review current prerequisites',
                next_action_ar='مراجعة المتطلبات الحالية', next_review_at='2026-11-17T12:30:00Z', authority_until='2026-11-17T13:00:00Z')


def command():
    facts = source()
    return {**{key: facts[key] for key in ('subject_id', 'watch_id', 'organization_id', 'source_revision',
            'scope_revision', 'quote_id', 'quote_revision', 'policy_revision')},
            'schema_version': 'service.progress.v1', 'operation_id': identifier(10), 'expected_revision': 0,
            'line_id': identifier(8), 'state': 'working', 'step_en': 'Movement examined',
            'step_ar': 'تم فحص الحركة', 'parts_en': '', 'parts_ar': '', 'readings_en': '', 'readings_ar': '',
            'estimate_start': None, 'estimate_end': None, 'estimate_basis_en': '', 'estimate_basis_ar': '',
            'next_actor': identifier(7), 'next_review_at': '2026-11-17T12:30:00Z', 'follow_up': 'review'}


CASES = {'success': {'status': 200, 'revision': 1}, 'denied': {'status': 403, 'code': 'denied'},
         'stale': {'status': 409, 'code': 'stale'},
         'lost_response': {'status': 503, 'code': 'pending', 'retry_operation_id': identifier(10)}}
