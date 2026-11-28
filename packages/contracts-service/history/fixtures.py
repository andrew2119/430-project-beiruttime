"""Synthetic boundary examples, never release evidence."""
from uuid import UUID


def result(state='ready'):
    return dict(schema_version='history.v1', operation_id=str(UUID(int=1)),
        subject_id=str(UUID(int=2)), watch_id=str(UUID(int=3)), actor_id=str(UUID(int=2)),
        organization_id=None, expected_revision=2, state=state, revision=2,
        pending_reason='source_pending' if state=='pending' else 'source_unavailable' if state=='unavailable' else None,
        next_actor='record_operator' if state in ('pending', 'unavailable') else 'reader',
        next_review_at=None, items=[], total=0, page=0, page_size=20)


SUCCESS = result()
DENIED = result('denied')
STALE = result('stale')
LOST_RESPONSE = result('unavailable')


PUBLICATION_SUCCESS = {**result(), 'schema_version':'history-publication.v1'}
PUBLICATION_DENIED = {**result('denied'), 'schema_version':'history-publication.v1'}
PUBLICATION_STALE = {**result('stale'), 'schema_version':'history-publication.v1'}
PUBLICATION_LOST_RESPONSE = {**result('pending'), 'schema_version':'history-publication.v1'}


# Explicit synthetic display example; it is not an assertion of completed work.
SAFE_ENTRY = dict(job_id=str(UUID(int=4)), watch_id=str(UUID(int=3)),
    organization_id=str(UUID(int=5)), kind='service', work_codes=['repair'],
    released_at='2026-11-01T00:00:00Z', source_revision=2,
    warranty=dict(issuer_id=str(UUID(int=5)), scope_code='accepted_work',
        starts_at='2026-11-01T00:00:00Z', terms_revision=1,
        terms_en='Synthetic accepted-work terms', terms_ar='شروط تجريبية للعمل المقبول'))
SUCCESS = {**SUCCESS, 'items':[SAFE_ENTRY], 'total':1}
