from uuid import UUID
from fastapi import APIRouter, Request
from bt_contracts.auction.policy.models import PrebidCommand, PrebidQuoteBasis, LegacyOperationSnapshot, LegacyOperationRead
from bt_contracts_core.errors import AccessDenied, PublicError
from service_app.engine import decoded, fingerprint, key_for
from .basis import quote_basis


async def legacy_view(tx, row):
    now = await tx.fetchval('SELECT clock_timestamp()')
    outcome = decoded(row['outcome'])
    review = row['review_state']
    if review != 'reservation_recorded':
        outcome = {**outcome, 'status': 'pending', 'code': row['review_code']}
    if decoded(row['allocation']).get('currency') != 'USD':
        outcome = {**outcome, 'status': 'pending', 'code': 'legacy_currency_review'}
    return {**outcome, 'version': 2, 'financial_state': 'held',
        'schedule_state': 'ended_legacy_review' if now >= row['scheduled_ends_at'] else 'within_schedule',
        'scheduled_ends_at': row['scheduled_ends_at'].isoformat()}

router=APIRouter()
router.add_api_route('/internal/v1/auctions/{auction_id}/prebid-basis',quote_basis,methods=['GET'],response_model=PrebidQuoteBasis)


def buyer(principal):
    if 'buyer' not in principal.roles or principal.actor.organization_id is not None:
        raise AccessDenied('An individual buyer is required')


async def existing(tx, subject, key, digest=None):
    row=await tx.fetchrow('SELECT * FROM auction_prebid_operations WHERE subject_id=$1 AND operation_key=$2',subject,key)
    if row and digest is not None and row['request_hash']!=digest:
        raise PublicError('idempotency_conflict','This key belongs to another request.',status=409)
    return row


@router.get('/v1/prebid-operations/{operation_key}')
async def operation(operation_key:str,request:Request):
    if not 1<=len(operation_key)<=128:
        raise PublicError('invalid_key','Invalid operation key.',status=422)
    principal=await request.app.state.auction.dependencies.principal(request)
    buyer(principal)
    async with request.app.state.pool.acquire() as tx:
        row=await existing(tx,principal.actor.subject_id,operation_key)
        if not row:
            raise PublicError('not_found','Operation not found.',status=404)
        return decoded(row['outcome'])


@router.get('/v1/auctions/{auction_id}/my-prebid')
async def my_operation(auction_id:UUID,request:Request):
    principal=await request.app.state.auction.dependencies.principal(request)
    buyer(principal)
    async with request.app.state.pool.acquire() as tx:
        row=await tx.fetchrow('SELECT outcome FROM auction_prebid_operations WHERE auction_id=$1 AND subject_id=$2',auction_id,principal.actor.subject_id)
        return {'operation':decoded(row['outcome']) if row else None}


@router.get('/v2/prebid-operations/{operation_key}', response_model=LegacyOperationSnapshot)
async def operation_v2(operation_key: str, request: Request):
    if not 1 <= len(operation_key) <= 128:
        raise PublicError('invalid_key', 'Invalid operation key.', status=422)
    principal = await request.app.state.auction.dependencies.principal(request)
    buyer(principal)
    async with request.app.state.pool.acquire() as tx:
        row = await existing(tx, principal.actor.subject_id, operation_key)
        if not row:
            raise PublicError('not_found', 'Operation not found.', status=404)
        return await legacy_view(tx, row)


@router.get('/v2/auctions/{auction_id}/my-prebid', response_model=LegacyOperationRead)
async def my_operation_v2(auction_id: UUID, request: Request):
    principal = await request.app.state.auction.dependencies.principal(request)
    buyer(principal)
    async with request.app.state.pool.acquire() as tx:
        row = await tx.fetchrow('SELECT * FROM auction_prebid_operations WHERE auction_id=$1 AND subject_id=$2', auction_id, principal.actor.subject_id)
        return {'operation': await legacy_view(tx, row) if row else None}


@router.post('/v1/auctions/{auction_id}/prebid-buy-now')
async def purchase(auction_id:UUID,command:PrebidCommand,request:Request):
    principal=await request.app.state.auction.dependencies.principal(request)
    buyer(principal)
    subject=principal.actor.subject_id
    key=key_for(request)
    digest=fingerprint('prebid',auction_id,command)
    async with request.app.state.pool.acquire() as tx:
        # Exact historical replay is a read, not permission for another allocation.
        replay=await existing(tx,subject,key,digest)
        if replay:
            return decoded(replay['outcome'])
    raise PublicError('auction_purchase_removed', 'Auctions do not offer Buy Now.', status=409)


@router.get('/v3/prebid-operations/{operation_key}')
async def operation_v3(operation_key: str, request: Request):
    from .recovery import Binding, MESSAGES, lookup_resolution, historical_resolution

    if not 1 <= len(operation_key) <= 128:
        raise PublicError('invalid_key', 'Invalid operation key. مرجع العملية غير صالح.', status=422)
    try:
        principal = await request.app.state.auction.dependencies.principal(request)
        buyer(principal)
    except AccessDenied:
        raise PublicError('access_denied',
            'Access denied. An individual buyer is required. الوصول مرفوض. يلزم حساب مشترٍ فردي.',
            status=403) from None
    async with request.app.state.pool.acquire() as tx:
        row = await existing(tx, principal.actor.subject_id, operation_key)
        if not row:
            raise PublicError('not_found', 'Operation not found. لم يتم العثور على العملية.', status=404)
        snapshot = await legacy_view(tx, row)
    allocation = decoded(row['allocation'])
    recovery = historical_resolution(None, None)
    if (allocation.get('currency') == 'USD' and row['admission_revision'] is not None
            and allocation.get('quote_revision') is not None and allocation.get('policy_revision') is not None):
        try:
            binding = Binding(operation_id=row['id'], subject_id=row['auction_id'],
                watch_id=allocation['watch_id'], actor_id=principal.actor.subject_id,
                organization_id=None, expected_revision=row['admission_revision'],
                quote_id=allocation['quote_id'], quote_revision=allocation['quote_revision'],
                policy_revision=allocation['policy_revision'])
        except (ValueError, KeyError):
            binding = None
        if binding is not None:
            recovery = await lookup_resolution(request.app.state.auction.dependencies, binding)
    state = recovery['state']
    en, ar = MESSAGES[state]
    return {'schema_version': 1, 'operation_id': str(row['id']), 'historical': snapshot,
            'resolution': state, 'recovery': recovery, 'message': {'en': en, 'ar': ar}}
