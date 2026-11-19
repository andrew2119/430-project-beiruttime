from uuid import UUID
from fastapi import APIRouter, Request
from bt_contracts.auction.policy.models import PolicySnapshot, SellerPolicySnapshot
from bt_contracts_core.errors import PublicError
from bt_runtime.principal import require_scope
from .kernel import get_kernel
from .policy import reserve_met

router = APIRouter()


async def snapshot(tx, lot, *, private=False):
    kernel = get_kernel()
    if any(name not in lot for name in ['end_version', 'mode']):
        raise PublicError('kernel_unavailable', 'Auction policy is temporarily unavailable.', status=503)
    now = await kernel.server_now(tx)
    end = lot['scheduled_ends_at'] if 'scheduled_ends_at' in lot else lot['ends_at']
    legacy = lot['mode'] in {'prebid_pending', 'prebid_reserved'}
    schedule = ('ended_legacy_review' if legacy else 'ended') if now >= end else (
        'scheduled' if now < lot['starts_at'] else 'live')
    value = {'policy_version': 'fixed-end.v2', 'auction_id': str(lot['id']),
        'revision': lot['revision'], 'end_version': lot['end_version'],
        'current_ends_at': end.isoformat(), 'server_time': now.isoformat(),
        'frozen': lot['accepted_sequence'] > 0 or lot['mode'] != 'bidding',
        'mode': lot['mode'], 'schedule_state': schedule, 'reserve_set': lot['reserve_minor'] is not None}
    if private:
        value.update(reserve_met=reserve_met(current_minor=lot['current_minor'],
            reserve_minor=lot['reserve_minor'], accepted_sequence=lot['accepted_sequence']),
            cancellation_eligible=lot['accepted_sequence'] == 0 and lot['mode'] == 'bidding' and now < end)
    return value


@router.get('/v1/auctions/{auction_id}/policy')
@router.get('/v2/auctions/{auction_id}/policy', response_model=PolicySnapshot)
async def get_policy(auction_id: UUID, request: Request):
    async with request.app.state.pool.acquire() as tx:
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
        if not lot:
            raise PublicError('not_found', 'Auction not found.', status=404)
        return await snapshot(tx, lot)


@router.get('/v2/seller/auctions/{auction_id}/policy', response_model=SellerPolicySnapshot)
async def seller_policy(auction_id: UUID, request: Request):
    engine = request.app.state.auction
    principal = await engine.dependencies.principal(request)
    require_scope(principal, 'identity.listings.publish', principal.actor.organization_id)
    async with request.app.state.pool.acquire() as tx:
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1', auction_id)
        if not lot:
            raise PublicError('not_found', 'Auction not found.', status=404)
        engine.owner(lot, principal)
        return await snapshot(tx, lot, private=True)


@router.patch('/v1/auctions/{auction_id}/policy')
async def configure(auction_id: UUID, request: Request):
    engine = request.app.state.auction
    principal = await engine.dependencies.principal(request)
    require_scope(principal, 'identity.listings.publish', principal.actor.organization_id)
    raise PublicError('fixed_end_policy', 'Auctions have a fixed scheduled end and no purchase option.', status=409)
