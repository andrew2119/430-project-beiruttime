"""Durable personal subscriptions, immutable receipts and bounded match delivery."""
import asyncio
import hashlib
import json
from uuid import uuid4
from bt_contracts_core.errors import PublicError
from bt_contracts.comms.saved_searches.models import Validation, Match


def fail(code, status=409):
    raise PublicError(code, code, status=status)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def project(row):
    return {key: str(row[key]) if key == 'id' else row[key].isoformat() if key == 'created_at'
            else decoded(row[key]) if key == 'criteria' else row[key]
            for key in ('id', 'revision', 'name', 'criteria', 'alerts_enabled', 'state', 'created_at')}


async def call(provider, method, *args):
    if provider is None:
        fail('unavailable', 503)
    try:
        return await asyncio.wait_for(getattr(provider, method)(*args), timeout=.6)
    except PublicError:
        raise
    except (TimeoutError, ValueError, TypeError, AttributeError, OSError):
        fail('unavailable', 503)


async def validate(provider, criteria):
    try:
        result = Validation.model_validate(await call(provider, 'validate', criteria))
    except ValueError:
        fail('unavailable', 503)
    if result.criteria != criteria:
        fail('unavailable', 503)
    return result.semantics_revision


async def command(tx, owner, body, provider):
    # Caller owns the personal advisory lock for the whole transaction.
    hashed = digest(body.model_dump(mode='json'))
    prior = await tx.fetchrow('SELECT * FROM l22_search_operations WHERE owner_id=$1 AND operation_id=$2', owner, body.operation_id)
    if prior:
        if prior['request_hash'] != hashed:
            fail('operation_conflict')
        return decoded(prior['result'])
    row = await tx.fetchrow('SELECT * FROM l22_saved_searches WHERE id=$1 AND owner_id=$2 FOR UPDATE', body.subject_id, owner)
    if not row and body.expected_revision != 0:
        fail('not_found', 404)
    if row and (row['revision'] != body.expected_revision or row['state'] == 'removed'):
        fail('stale_revision')
    if not row and body.kind == 'remove':
        fail('not_found', 404)
    semantics = await validate(provider, body.criteria) if body.kind == 'save' else row['semantics_revision']
    if not row:
        count = await tx.fetchval("SELECT count(*) FROM l22_saved_searches WHERE owner_id=$1 AND state='saved'", owner)
        if count >= 100:
            fail('subscription_limit', 422)
        # The identifier is globally unique; a different owner's identifier never overwrites.
        inserted = await tx.fetchrow('''INSERT INTO l22_saved_searches
            (id,owner_id,name,criteria,semantics_revision,alerts_enabled,state,revision,created_at,eligible_at)
            VALUES($1,$2,$3,$4::jsonb,$5,$6,'saved',1,clock_timestamp(),clock_timestamp())
            ON CONFLICT(id) DO NOTHING RETURNING *''', body.subject_id, owner, body.name,
            body.criteria.model_dump_json(), semantics, body.alerts_enabled)
        if not inserted:
            fail('not_found', 404)
        row = inserted
    else:
        reset = (row['semantics_revision'] != semantics or decoded(row['criteria']) != body.criteria.model_dump(mode='json') or
                 (body.alerts_enabled and not row['alerts_enabled']))
        row = await tx.fetchrow('''UPDATE l22_saved_searches SET name=$3,criteria=$4::jsonb,
            semantics_revision=$5,alerts_enabled=$6,state=$7,revision=revision+1,
            eligible_at=CASE WHEN $8 THEN clock_timestamp() ELSE eligible_at END
            WHERE id=$1 AND owner_id=$2 RETURNING *''', body.subject_id, owner, body.name,
            body.criteria.model_dump_json(), semantics, body.alerts_enabled if body.kind == 'save' else False,
            'saved' if body.kind == 'save' else 'removed', reset)
    result = {'schema_version': 'saved-searches.v1', 'operation_id': str(body.operation_id),
              'subject_id': str(body.subject_id), 'actor_id': str(owner), 'organization_id': None,
              'expected_revision': body.expected_revision, 'state': row['state'], 'revision': row['revision'],
              'pending_reason': None, 'next_actor': None, 'next_review_at': None, 'result': project(row)}
    await tx.execute('INSERT INTO l22_search_operations VALUES($1,$2,$3,$4::jsonb)', owner, body.operation_id, hashed, json.dumps(result))
    return result


async def deliver(tx, owner, publication, provider):
    hashed = digest(publication.model_dump(mode='json'))
    prior = await tx.fetchrow('SELECT * FROM l22_match_deliveries WHERE owner_id=$1 AND occurrence_id=$2', owner, publication.occurrence_id)
    if prior:
        if prior['request_hash'] != hashed:
            fail('occurrence_conflict')
        return
    now = await tx.fetchval('SELECT clock_timestamp()')
    if publication.published_at > now:
        fail('invalid_publication', 422)
    rows = await tx.fetch("SELECT * FROM l22_saved_searches WHERE owner_id=$1 AND state='saved' AND alerts_enabled ORDER BY id LIMIT 101", owner)
    if len(rows) > 100:
        fail('subscription_limit', 422)
    from bt_contracts.comms.saved_searches.models import Criteria

    async def matching(row):
        try:
            criteria = Criteria.model_validate(decoded(row['criteria']))
            match = Match.model_validate(await call(provider, 'match', publication, criteria, row['semantics_revision']))
        except ValueError:
            fail('unavailable', 503)
        if any(getattr(match, key) != getattr(publication, key) for key in ('occurrence_id', 'listing_id', 'watch_id', 'revision')) or match.semantics_revision != row['semantics_revision']:
            fail('unavailable', 503)
        return match

    eligible = [row for row in rows if publication.published_at >= row['eligible_at']]
    matches = []
    # Ten bounded calls per batch; finish each batch before starting another.
    # Collect failures too so no dependency call survives a failed batch.
    for start in range(0, len(eligible), 10):
        results = await asyncio.gather(*(matching(row) for row in eligible[start:start + 10]), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        matches.extend(results)
    for row, match in zip(eligible, matches):
        if match.matches and match.currently_public:
            # This inbox row and delivery receipt share the event transaction.
            await tx.execute('''INSERT INTO l22_match_notices
                (id,owner_id,subscription_id,occurrence_id,listing_id,watch_id,source_revision,event_time,sample)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT(subscription_id,occurrence_id) DO NOTHING''',
                uuid4(), owner, row['id'], publication.occurrence_id, publication.listing_id,
                publication.watch_id, publication.revision, publication.published_at, publication.sample)
    await tx.execute('INSERT INTO l22_match_deliveries VALUES($1,$2,$3)', owner, publication.occurrence_id, hashed)
