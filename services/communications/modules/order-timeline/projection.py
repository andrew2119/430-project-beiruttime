"""Read-only, bounded composition of current source snapshots."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Protocol

SOURCES = ('orders', 'payments', 'inspection', 'custody', 'progress', 'settlement')
STATES = {'pending', 'confirmed', 'blocked', 'not_applicable'}
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$')
MAX_MINOR = 9007199254740991


class Denied(Exception):
    pass


class Unavailable(Exception):
    pass


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('Invalid reference')
    return value


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_MINOR:
        raise ValueError('Invalid integer')
    return value


def instant(value):
    if not isinstance(value, str) or len(value) > 32 or not value.endswith('Z'):
        raise ValueError('UTC instant required')
    result = datetime.fromisoformat(value[:-1] + '+00:00')
    if result.utcoffset() != timedelta(0):
        raise ValueError('UTC instant required')
    return result


def utc(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


@dataclass(frozen=True)
class Lease:
    actor_id: str
    organization_id: str | None
    order_id: str
    watch_id: str
    access_revision: int
    source_revisions: tuple[tuple[str, int], ...]


class Access(Protocol):
    async def authorize(self, credential: str, order_id: str, organization_id: str | None) -> Lease: ...
    async def recheck(self, credential: str, lease: Lease) -> bool: ...
    async def catalog(self, credential: str, organization_id: str | None, offset: int, limit: int) -> dict: ...


class Source(Protocol):
    async def snapshot(self, lease: Lease) -> dict: ...


async def bounded(call):
    try:
        return await asyncio.wait_for(call, timeout=.3)
    except (TimeoutError, OSError):
        raise Unavailable() from None


def milestone(name, value, lease, now):
    if (value['schema_version'] != 'timeline-source.v1' or value['source'] != name or
            value['order_id'] != lease.order_id or value['watch_id'] != lease.watch_id):
        raise ValueError('Source binding mismatch')
    identifier(value['operation_id'])
    identifier(value['quote_id'])
    integer(value['quote_revision'], 1)
    revision = integer(value['revision'], 1)
    if revision != dict(lease.source_revisions).get(name):
        raise ValueError('Stale source revision')
    if value['state'] not in STATES:
        raise ValueError('Invalid state')
    occurred = instant(value['occurred_at'])
    if occurred > now:
        raise ValueError('Future fact')
    amount = value.get('amount_minor')
    if amount is not None:
        integer(amount)
    return dict(source=name, state=value['state'], revision=revision, operation_id=value['operation_id'],
                occurred_at=utc(occurred), amount_minor=amount)


def waiting(value, now):
    if value['party'] not in {'buyer', 'seller', 'business', 'operator', 'authenticator'}:
        raise ValueError('Invalid party')
    if value['action'] not in {'pay', 'review', 'receive', 'inspect', 'work', 'reconcile', 'wait'}:
        raise ValueError('Invalid action')
    identifier(value['operator_id'])
    since, progress = instant(value['since']), instant(value['last_progress_at'])
    if not since <= progress <= now:
        raise ValueError('Invalid progress time')
    due, escalation = progress + timedelta(hours=24), progress + timedelta(hours=48)
    return dict(party=value['party'], action=value['action'], operator_id=value['operator_id'],
                since=utc(since), next_review_at=utc(due if now < due else escalation),
                follow_up='escalated' if now >= escalation else 'due' if now >= due else 'scheduled')


def economics(value):
    result = {key: integer(value[key]) for key in
              ('principal_minor', 'buyer_fee_minor', 'business_fee_minor', 'total_minor')}
    if result['total_minor'] != result['principal_minor'] + result['buyer_fee_minor']:
        raise ValueError('Invalid retained total')
    if result['business_fee_minor'] > result['principal_minor']:
        raise ValueError('Invalid retained fee')
    result.update(quote_id=identifier(value['quote_id']), quote_revision=integer(value['quote_revision'], 1))
    return result


def financial(value, name, now):
    rows = value['financial'] if name in ('payments', 'settlement') else []
    if not isinstance(rows, list) or len(rows) > 50:
        raise ValueError('Invalid financial rows')
    result = []
    for row in rows:
        if (set(row) != {'kind', 'state', 'amount_minor', 'operation_id', 'revision', 'occurred_at', 'source'} or
                row['source'] != name or row['kind'] not in {'gross', 'collected_fee', 'refund', 'net', 'payout'} or
                row['state'] not in {'pending', 'confirmed', 'blocked'} or instant(row['occurred_at']) > now):
            raise ValueError('Invalid financial fact')
        identifier(row['operation_id'])
        integer(row['revision'], 1)
        integer(row['amount_minor'])
        result.append(dict(row))
    if len({row['operation_id'] for row in result}) != len(result):
        raise ValueError('Duplicate financial fact')
    return result


class TimelineService:
    def __init__(self, access: Access, sources: dict[str, Source], clock):
        self.access, self.sources, self.clock = access, sources, clock

    async def read(self, credential, order_id, organization_id=None):
        identifier(order_id)
        if organization_id is not None:
            identifier(organization_id)
        lease = await bounded(self.access.authorize(credential, order_id, organization_id))
        if not isinstance(lease, Lease):
            raise Unavailable()
        if lease.order_id != order_id or lease.organization_id != organization_id:
            raise Denied()
        try:
            identifier(lease.actor_id)
            identifier(lease.watch_id)
            integer(lease.access_revision, 1)
            revisions = dict(lease.source_revisions)
            if len(lease.source_revisions) != 6 or set(revisions) != set(SOURCES):
                raise ValueError('Invalid revision bindings')
            for revision in revisions.values():
                integer(revision, 1)
        except (ValueError, TypeError):
            raise Unavailable() from None
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise Unavailable()

        async def load(name):
            try:
                value = await bounded(self.sources[name].snapshot(lease))
                row = milestone(name, value, lease, now)
                financial(value, name, now)
                return value, row
            except (Unavailable, ValueError, KeyError, TypeError, OverflowError):
                return None, dict(source=name, state='unavailable', revision=None, operation_id=None,
                                  occurred_at=None, amount_minor=None)

        rows = await asyncio.gather(*(load(name) for name in SOURCES))
        order = rows[0][0]
        if order is None:
            raise Unavailable()
        try:
            result = dict(schema_version='order-timeline.v1', order_id=order_id,
                          watch_id=lease.watch_id, reference=identifier(order['reference']),
                          revision=rows[0][1]['revision'], operation_id=order['operation_id'],
                          currency='USD', simulated=True, as_of=utc(now),
                          economics=economics(order['economics']), waiting=waiting(order['waiting'], now),
                          milestones=[row[1] for row in rows])
            if (order['quote_id'] != result['economics']['quote_id'] or
                    order['quote_revision'] != result['economics']['quote_revision']):
                raise ValueError('Contradictory retained quote')
            if order['currency'] != 'USD':
                raise ValueError('Unsupported currency')
        except (ValueError, KeyError, TypeError, OverflowError):
            raise Unavailable() from None
        for index, name in enumerate(SOURCES[1:], 1):
            source = rows[index][0]
            if source is not None and (source.get('quote_id') != result['economics']['quote_id'] or
                    source.get('quote_revision') != result['economics']['quote_revision']):
                result['milestones'][index] = dict(source=name, state='unavailable', revision=None, operation_id=None,
                                                   occurred_at=None, amount_minor=None)
        result['financial'] = [fact for index, name in enumerate(SOURCES)
                               if result['milestones'][index]['state'] != 'unavailable'
                               for fact in financial(rows[index][0], name, now)]
        if len({row['operation_id'] for row in result['financial']}) != len(result['financial']):
            raise Unavailable()
        if await bounded(self.access.recheck(credential, lease)) is not True:
            raise Denied()
        return result

    async def list(self, credential, organization_id=None, offset=0, limit=20):
        integer(offset)
        if type(limit) is not int or not 1 <= limit <= 20 or offset > 1000000:
            raise ValueError('Invalid page')
        if organization_id is not None:
            identifier(organization_id)
        page = await bounded(self.access.catalog(credential, organization_id, offset, limit))
        try:
            total = integer(page['total'])
            if not isinstance(page['items'], list) or len(page['items']) > limit:
                raise ValueError('Invalid page size')
            items = [dict(order_id=identifier(row['order_id']), reference=identifier(row['reference']))
                     for row in page['items']]
            if len(items) != min(limit, max(0, total - offset)) or len({r['order_id'] for r in items}) != len(items):
                raise ValueError('Invalid page')
            return dict(schema_version='order-timeline-list.v1', items=items, total=total, offset=offset, limit=limit)
        except (ValueError, KeyError, TypeError):
            raise Unavailable() from None
