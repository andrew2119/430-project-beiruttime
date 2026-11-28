"""Synthetic commands and trusted source facts; never runtime completion evidence."""
from datetime import datetime, timedelta, timezone
from uuid import UUID


def identifier(value):
    return UUID(int=value)


def fixture():
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    binding = dict(job_id=identifier(1), watch_id=identifier(2), organization_id=identifier(3),
                   scope_revision=1, work_revision=1, assignment_revision=1,
                   quote_id=identifier(4), quote_revision=1, policy_revision=1)
    check = dict(key='actual', actual='Synthetic measured result: 175 mm', satisfactory=True)
    command = dict(**binding, operation_id=identifier(5), actor_id=identifier(6), expected_revision=0,
                   lines=[dict(line_id=identifier(7), tests=[check], condition=check, fit=check, returned_parts=check)])
    current = dict(**binding, actor_id=identifier(6), assessor_id=identifier(8), approver_id=identifier(9),
                   performer_ids={identifier(8)}, quality_reviewer_id=identifier(6), qualified=True,
                   assessor_qualified=True, approver_qualified=True, permitted=True, seller_type='dealer', required_line_ids={identifier(7)},
                   completed_line_ids={identifier(7)}, required_tests={identifier(7): {'actual'}}, custody_current=True, payment_held=True,
                   commitment_current=True, incident_open=False, accepted_current=True,
                   checked_at=now, valid_until=now + timedelta(seconds=2))
    return command, current, now


def cases():
    command, current, _ = fixture()
    return {
        'success': {'command': command, 'current': current},
        'denied': {'command': command, 'current': {**current, 'permitted': False}},
        'stale': {'command': command, 'current': {**current, 'work_revision': 2}},
        'lost_response': {'command': command, 'retry': command, 'operation_id': command['operation_id']},
    }
