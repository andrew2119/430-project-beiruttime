"""Current accepted progress; no fulfillment or financial authority."""
from datetime import datetime, timedelta
from .contracts import Binding


class Denied(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status


def authorize(access, source, now, write=False):
    if now >= source.authority_until:
        raise Denied('unavailable', 503)
    staff = (access.organization_id == source.organization_id and access.actor_id in source.assigned_actor_ids)
    buyer = access.actor_id == source.buyer_id and access.organization_id is None
    if not access.can_read or not (staff or buyer) or write and not (staff and access.can_write):
        raise Denied('denied', 403)


def current_binding(source):
    return Binding.model_validate(source.model_dump(include=set(Binding.model_fields)))


def validate(command, source, access, revision, now):
    authorize(access, source, now, write=True)
    if current_binding(source) != Binding.model_validate(command.model_dump(include=set(Binding.model_fields))):
        raise Denied('stale')
    if command.expected_revision != revision:
        raise Denied('stale')
    ids = {line.line_id for line in source.accepted_lines}
    if command.line_id not in ids or command.next_actor not in source.assigned_actor_ids:
        raise Denied('scope_mismatch')
    if not source.commitment_current or not source.scope_accepted or not source.custody_current or not source.payment_held or source.incident_open:
        raise Denied('work_held')
    if command.line_id in source.material_line_ids:
        raise Denied('material_change')
    if not now < command.next_review_at <= now + timedelta(hours=24):
        raise Denied('review_required')


def project(source, reports, revision, now, offset=0):
    if type(offset) is not int or offset < 0 or offset > 1000 or offset % 50:
        raise Denied('invalid_page', 422)
    rows = []
    bindings = current_binding(source).model_dump(mode='json', exclude={'source_revision'})
    held = not source.commitment_current or source.incident_open or not source.scope_accepted or not source.custody_current or not source.payment_held
    for line in source.accepted_lines:
        report = reports.get(str(line.line_id))
        # Accepted-scope replacement preserves history, but cannot reuse old completion.
        matches = report and all(report.get(key) == value for key, value in bindings.items())
        current = report if matches else None
        state = current['state'] if current else 'not_started'
        if line.line_id in source.material_line_ids:
            state = 'paused'
        elif held:
            state = 'held'
        rows.append({**line.model_dump(mode='json'), 'state': state, 'report': current,
                     'overdue': bool(current and now >= datetime.fromisoformat(current['next_review_at']))})
    complete = bool(rows) and all(row['state'] == 'completed' for row in rows)
    quality_current = (source.quality_independent and source.quality_work_revision == revision
                       and source.quality_scope_revision == source.scope_revision)
    quality_result = source.quality_result if quality_current else 'missing'
    quality = quality_result == 'passed'
    ready = complete and quality and not held and not source.material_line_ids
    return dict(schema_version='service.progress.v1', subject_id=str(source.subject_id),
                watch_id=str(source.watch_id), organization_id=str(source.organization_id), revision=revision,
                scope_revision=source.scope_revision, next_actor=str(source.responsible_actor_id),
                next_action_en=source.next_action_en, next_action_ar=source.next_action_ar,
                next_review_at=source.next_review_at.isoformat(), review_overdue=now >= source.next_review_at, state='held' if held else 'ready' if ready else
                'rework' if quality_result == 'failed' else 'progress', quality=quality_result,
                total=len(rows), items=rows[offset:offset + 50], next_offset=offset + 50 if offset + 50 < len(rows) else None,
                execution_authorized=False, release_authorized=False)
