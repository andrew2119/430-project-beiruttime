"""Current buyer activity from scoped Auction records and authoritative Orders facts."""
import asyncio
import hashlib
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from bt_contracts_core.errors import AccessDenied, PublicError

from .private_maximum import own_bidder

router = APIRouter(prefix='/v2', tags=['buyer-activity'])
MAX_SCOPE = 1000
MAX_FINANCIAL_CANDIDATES = 4096
FINANCIAL_VIEWS = frozenset({'released', 'unpaid'})
SEEN_BID = '''EXISTS (SELECT 1 FROM auction_operations o WHERE o.auction_id=a.id
    AND o.subject_id=$1 AND o.organization_id IS NULL AND o.outcome->>'status'='succeeded'
    AND o.outcome->>'code'='bid_accepted')'''
SHOP_SCOPE = '''a.currency='USD' AND a.seller_id<>$1
    AND (a.seller_organization_id IS NULL OR NOT (a.seller_organization_id=ANY($2::uuid[])))'''
CLOSE_FIELDS = '''a.id, a.listing_id, a.watch_id, a.seller_id, a.seller_organization_id,
    a.currency, a.listing_is_demo, c.result_revision, c.state, c.winner_id, c.order_id,
    c.closing_minor, a.scheduled_ends_at AS ended_at'''


class FinancialFact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_id: UUID
    auction_id: UUID
    watch_id: UUID
    revision: StrictInt = Field(ge=1)
    state: Literal['pending', 'unknown', 'unpaid', 'unpaid_released', 'paid_held', 'released']


class FinancialPage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: StrictInt = Field(ge=1, le=1)
    items: list[FinancialFact] = Field(max_length=MAX_FINANCIAL_CANDIDATES)


def unavailable():
    return PublicError('buyer_activity_unavailable', 'Current buyer activity is unavailable.', status=503)


def stale():
    return PublicError('stale_cursor', 'Activity changed. Return to the first page.', status=409)


async def financial_facts(request, engine, rows):
    orders = [dict(order_id=str(row['order_id']), auction_id=str(row['id']), watch_id=str(row['watch_id']))
              for row in rows if row['order_id'] is not None]

    if not orders:
        return {}
    if len(orders) > MAX_FINANCIAL_CANDIDATES or len({row['order_id'] for row in orders}) != len(orders):
        raise unavailable()
    expected = {(row['order_id'], row['auction_id'], row['watch_id']) for row in orders}
    large = len(orders) > 50
    path = '/internal/v2/auction-financial-snapshot' if large else '/internal/v2/auction-financial-facts'
    body = {'schema_version': 1, 'orders': orders} if large else {'orders': orders}
    try:
        # One bounded Orders snapshot leaves time for the local reread and the
        # 600 ms workspace budget. A slow or missing owner never yields a partial total.
        async with asyncio.timeout(.4):
            data = await engine.dependencies.json('orders', 'POST', path, request,
                headers=engine.dependencies.service_headers(request, 'orders'), json=body)
        page = FinancialPage.model_validate(data)
    except (TimeoutError, ValidationError, PublicError, AccessDenied, HTTPException):
        raise unavailable() from None
    observed = {(str(row.order_id), str(row.auction_id), str(row.watch_id)) for row in page.items}
    if observed != expected or len(page.items) != len(expected):
        raise unavailable()
    return {row.order_id: row for row in page.items}


def activity_page(rows, principal, view, limit, cursor, *, result=False, source_revisions=None):
    # The cursor is a position in an exact scoped snapshot, not authorization.
    # Both order and membership are rebuilt from current server facts on retry.
    ids = [row['auction_id'] for row in rows]
    material = [str(principal.actor.subject_id), sorted(map(str, principal.organizations)), view,
                rows, source_revisions]
    stamp = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    start = 0
    if cursor is not None:
        anchor, separator, supplied = cursor.partition('.')
        if not separator or supplied != stamp or anchor not in ids:
            raise stale()
        start = ids.index(anchor) + 1
        if start >= len(ids):
            raise stale()
    page = rows[start:start + limit]
    next_cursor = page[-1]['auction_id'] + '.' + stamp if start + limit < len(rows) else None
    return {**({'schema_version': 2, 'state': 'available'} if result else {}),
            'items': page, 'total': len(rows), 'next_cursor': next_cursor}


@router.get('/my-bids')
async def my_bids(request: Request, response: Response,
                  view: Literal['leading', 'outbid', 'calendar'] = 'leading',
                  limit: int = Query(default=50, ge=1, le=50), cursor: str | None = Query(default=None, max_length=200)):
    actor = await own_bidder(request.app.state.auction, request)
    buyer = actor.actor.subject_id
    async with request.app.state.pool.acquire() as db:
        async with db.transaction(isolation='repeatable_read', readonly=True):
            now = await db.fetchval('SELECT clock_timestamp()')
            rows = await db.fetch(f'''SELECT a.id, a.listing_id, a.revision, a.starts_at, a.ends_at,
                    a.current_minor, a.leader_id, a.listing_is_demo, {SEEN_BID} AS participated
                 FROM auction_lots a WHERE {SHOP_SCOPE} AND a.mode='bidding' AND a.ends_at>$3
                   AND ($4='calendar' OR (a.starts_at<=$3 AND {SEEN_BID} AND
                       (($4='leading' AND a.leader_id=$1) OR ($4='outbid' AND a.leader_id<>$1))))
                 ORDER BY a.ends_at ASC, a.id ASC LIMIT $5''', buyer, actor.organizations, now, view, MAX_SCOPE + 1)
    if len(rows) > MAX_SCOPE or any(type(row['listing_is_demo']) is not bool for row in rows):
        raise unavailable()
    items = []
    for row in rows:
        scheduled = row['starts_at'] > now
        items.append(dict(auction_id=str(row['id']), listing_id=str(row['listing_id']), buyer_id=str(buyer),
            currency='USD', revision=row['revision'], is_demo=row['listing_is_demo'],
            lifecycle='scheduled' if scheduled else 'live', current_price_minor=row['current_minor'],
            status=None if scheduled or not row['participated'] else 'leading' if row['leader_id'] == buyer else 'outbid',
            starts_at=row['starts_at'].isoformat(), ends_at=row['ends_at'].isoformat()))
    response.headers['Cache-Control'] = 'no-store'
    return activity_page(items, actor, view, limit, cursor)


def result_scope_limit(view):
    # Financial predicates are owned by Orders. Reserve bounded candidate
    # headroom for nonmatches instead of treating them as displayed results.
    return MAX_FINANCIAL_CANDIDATES if view in FINANCIAL_VIEWS else MAX_SCOPE


async def result_rows(request, principal, view):
    async with request.app.state.pool.acquire() as db:
        return await db.fetch(f'''SELECT {CLOSE_FIELDS} FROM l13_auction_closes c JOIN auction_lots a ON a.id=c.auction_id
            WHERE {SHOP_SCOPE} AND c.state<>'ended_legacy_review' AND {SEEN_BID}
              AND CASE $3 WHEN 'no_sale' THEN c.state='no_sale'
                WHEN 'won' THEN c.winner_id=$1 WHEN 'lost' THEN c.winner_id<>$1
                WHEN 'unpaid' THEN c.winner_id=$1 AND c.order_id IS NOT NULL
                ELSE c.order_id IS NOT NULL END
            ORDER BY a.scheduled_ends_at DESC, a.id ASC LIMIT $4''',
            principal.actor.subject_id, principal.organizations, view, result_scope_limit(view) + 1)


@router.get('/my-results')
async def my_results(request: Request, response: Response,
                     view: Literal['won', 'lost', 'no_sale', 'unpaid', 'released'] = 'won',
                     limit: int = Query(default=50, ge=1, le=50), cursor: str | None = Query(default=None, max_length=200)):
    engine = request.app.state.auction
    principal = await own_bidder(engine, request)
    buyer = str(principal.actor.subject_id)
    rows = await result_rows(request, principal, view)
    if len(rows) > result_scope_limit(view):
        raise unavailable()
    facts = await financial_facts(request, engine, rows)
    if facts and rows != await result_rows(request, principal, view):
        raise unavailable()
    project = request.app.state.hooks.get('auction.my-results.project.v2')
    if project is None:
        raise unavailable()
    items, financial_revisions = [], []
    for row in rows:
        order = row['order_id']
        allocation_denied = row['state'] == 'allocation_denied' and order is None
        if row['state'] == 'no_sale' or allocation_denied:
            financial = None
        elif row['state'] == 'allocation_pending' and order is None:
            financial = 'pending'
        elif row['state'] == 'closed' and order in facts:
            financial = facts[order].state
            financial_revisions.append((str(order), facts[order].revision))
        else:
            raise unavailable()
        if ((view == 'unpaid' and financial not in ('unpaid', 'unpaid_released'))
                or (view == 'released' and financial != 'released')):
            continue
        revision = row['result_revision']
        try:
            value = project(dict(buyer_id=buyer, auction_id=str(row['id']), listing_id=str(row['listing_id']),
                watch_id=str(row['watch_id']), is_demo=row['listing_is_demo'], currency=row['currency'],
                participated=True, result_recorded=True, sale_qualified=row['state'] != 'no_sale',
                revision=revision, source_revision=revision, ended_at=row['ended_at'].isoformat(),
                final_minor=row['closing_minor'] or None, winner_id=str(row['winner_id']) if row['winner_id'] else None,
                order_id=str(order) if order else None, financial_state=financial,
                **({'allocation_state': 'denied'} if allocation_denied else {})),
                dict(allowed=True, organization_id=None, actor_id=buyer, expected_source_revision=revision))
        except ValueError:
            raise unavailable() from None
        items.append(value)
    response.headers['Cache-Control'] = 'no-store'
    return activity_page(items, principal, view, limit, cursor, result=True, source_revisions=financial_revisions)
