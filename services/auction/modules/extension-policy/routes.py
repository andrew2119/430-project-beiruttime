import json
from uuid import UUID, uuid4
from fastapi import APIRouter, Request
from bt_contracts.auction.policy.models import ConfigurePolicy
from bt_contracts_core.errors import PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from service_app.engine import fingerprint, key_for
from .kernel import get_kernel
from .policy import reserve_met

router = APIRouter()


async def snapshot(tx, lot):
    kernel=get_kernel()
    if any(name not in lot for name in ['end_version','mode']):
        raise PublicError('kernel_unavailable','Auction policy is temporarily unavailable.',status=503)
    price = lot['buy_now_minor'] if 'buy_now_minor' in lot else await tx.fetchval('SELECT buy_now_minor FROM auction_policy_settings WHERE auction_id=$1',lot['id'])
    return {'auction_id':str(lot['id']), 'revision':lot['revision'], 'end_version':lot['end_version'],
        'current_ends_at':lot['ends_at'].isoformat(), 'server_time':(await kernel.server_now(tx)).isoformat(),
        'extension_policy':lot['extension_policy'], 'buy_now_minor':price,
        'frozen':lot['accepted_sequence']>0 or lot['mode']!='bidding', 'mode':lot['mode'],
        'reserve_set':lot['reserve_minor'] is not None, 'reserve_met':reserve_met(current_minor=lot['current_minor'],
            reserve_minor=lot['reserve_minor'],accepted_sequence=lot['accepted_sequence'])}


@router.get('/v1/auctions/{auction_id}/policy')
async def get_policy(auction_id:UUID, request:Request):
    async with request.app.state.pool.acquire() as tx:
        lot = await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1',auction_id)
        if not lot: raise PublicError('not_found','Auction not found.',status=404)
        return await snapshot(tx,lot)


@router.patch('/v1/auctions/{auction_id}/policy')
async def configure(auction_id:UUID, command:ConfigurePolicy, request:Request):
    engine = request.app.state.auction
    principal = await engine.dependencies.principal(request)
    require_scope(principal, 'identity.listings.publish', principal.actor.organization_id)
    kernel=get_kernel()
    key = key_for(request)
    revision = request.headers.get('if-match','').strip('"')
    if not revision.isdecimal() or len(revision)>15:
        raise PublicError('revision_required','Supply the current revision.',status=422)
    digest = fingerprint('policy:'+revision,auction_id,command)
    async with unit_of_work(request.app.state.pool) as tx:
        replay = await engine.operation(tx,principal,key,digest)
        if replay: return replay
        lot = await kernel.lock_lot(tx,auction_id)
        engine.owner(lot,principal)
        kernel.require_bidding(lot)
        if lot['accepted_sequence']:
            raise PublicError('rules_frozen','Policy is frozen after the first bid.',status=409)
        if lot['revision']!=int(revision):
            raise PublicError('stale_revision','Reload the current auction.',status=409)
        if await kernel.server_now(tx)>=lot['ends_at']:
            raise PublicError('auction_ended','The auction has ended.',status=409)
        if command.buy_now_minor is not None and command.buy_now_minor < max(lot['opening_minor'],lot['reserve_minor'] or 0):
            raise PublicError('buy_now_below_reserve','Buy Now must cover opening and reserve.',status=422)
        lot = await tx.fetchrow('UPDATE auction_lots SET extension_policy=$2,buy_now_minor=$3,revision=revision+1 WHERE id=$1 RETURNING *',auction_id,command.extension_policy,command.buy_now_minor)
        await tx.execute('''INSERT INTO auction_policy_settings(auction_id,buy_now_minor) VALUES($1,$2)
            ON CONFLICT(auction_id) DO UPDATE SET buy_now_minor=excluded.buy_now_minor,updated_at=clock_timestamp()''',auction_id,command.buy_now_minor)
        value = await snapshot(tx,lot)
        outcome = {'operation_id':str(uuid4()),'status':'succeeded','code':'policy_updated','auction_id':str(auction_id),'policy':value}
        # No unsupported relay destination is enabled; the fact is durable for future receivers.
        await enqueue(tx,EventEnvelope(type='auction.policy-updated.v1',source='auction',subject=str(auction_id),
            request_id=request.state.request_id,data=value),['communications-auction-policy-v1'])
        return await engine.store(tx,principal,key,digest,outcome,auction_id)
