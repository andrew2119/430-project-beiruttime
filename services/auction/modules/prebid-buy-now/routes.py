import json
from uuid import UUID, uuid4
from fastapi import APIRouter, Request
from bt_contracts.auction.policy.models import PrebidCommand, PrebidQuoteBasis
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work
from service_app.engine import decoded, fingerprint, key_for
from .kernel import get_kernel
from . import dependencies
from .workers import tick
from .basis import quote_basis

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
    if not 1<=len(operation_key)<=128: raise PublicError('invalid_key','Invalid operation key.',status=422)
    principal=await request.app.state.auction.dependencies.principal(request)
    buyer(principal)
    async with request.app.state.pool.acquire() as tx:
        row=await existing(tx,principal.actor.subject_id,operation_key)
        if not row: raise PublicError('not_found','Operation not found.',status=404)
        return decoded(row['outcome'])


@router.get('/v1/auctions/{auction_id}/my-prebid')
async def my_operation(auction_id:UUID,request:Request):
    principal=await request.app.state.auction.dependencies.principal(request)
    buyer(principal)
    async with request.app.state.pool.acquire() as tx:
        row=await tx.fetchrow('SELECT outcome FROM auction_prebid_operations WHERE auction_id=$1 AND subject_id=$2',auction_id,principal.actor.subject_id)
        return {'operation':decoded(row['outcome']) if row else None}


@router.post('/v1/auctions/{auction_id}/prebid-buy-now')
async def purchase(auction_id:UUID,command:PrebidCommand,request:Request):
    principal=await request.app.state.auction.dependencies.principal(request)
    buyer(principal)
    subject=principal.actor.subject_id
    kernel=get_kernel()
    key=key_for(request)
    digest=fingerprint('prebid',auction_id,command)
    async with request.app.state.pool.acquire() as tx:
        replay=await existing(tx,subject,key,digest)
        if replay: return decoded(replay['outcome'])
        initial=await tx.fetchrow('SELECT * FROM auction_lots WHERE id=$1',auction_id)
        if not initial: raise PublicError('not_found','Auction not found.',status=404)
    quote,expiry=await dependencies.quote(request,command.quote_id,auction_id,principal)
    watch=await dependencies.watch(request,initial['watch_id'])
    async with unit_of_work(request.app.state.pool) as tx:
        # Same order as manual/proxy admission: operation then canonical auction.
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',f'operation:{subject}:{key}')
        replay=await existing(tx,subject,key,digest)
        if replay: return decoded(replay['outcome'])
        lot=await kernel.lock_lot(tx,auction_id)
        kernel.require_bidding(lot)
        now=await kernel.server_now(tx)
        if subject==lot['seller_id'] or lot['seller_organization_id'] in principal.organizations:
            raise AccessDenied('A seller or business member cannot buy this watch')
        if lot['accepted_sequence']:
            raise PublicError('first_bid_exists','Buy Now is unavailable after the first bid.',status=409)
        if now<lot['starts_at'] or now>=lot['ends_at']:
            raise PublicError('auction_ended','Buy Now requires a live auction.',status=409)
        if lot['revision']!=command.expected_revision or quote['subject_revision']!=lot['revision']:
            raise PublicError('stale_revision','Review the current auction.',status=409)
        price=lot['buy_now_minor']
        if price is None: raise PublicError('buy_now_disabled','Buy Now is not offered.',status=409)
        if (expiry<=now or quote['price_minor']!=price or quote['currency']!=lot['currency']
            or quote['auction_id']!=str(auction_id) or quote['listing_id']!=str(lot['listing_id'])
            or quote['watch_id']!=str(lot['watch_id']) or quote['listing_revision']!=lot['listing_revision']):
            raise PublicError('quote_invalid','Review the current exact quote.',status=409)
        try:
            if watch['watch_id']!=str(lot['watch_id']) or watch['listing_id']!=str(lot['listing_id']): raise ValueError()
            for field in ('listing_revision','revision'):
                if type(watch[field]) is not int or watch[field]<1: raise ValueError()
            if (watch['listing_revision']!=lot['listing_revision'] or watch['source_id']!=str(auction_id)
                or watch['status']!='fenced' or watch['auction_committed'] is not False):
                raise PublicError('auction_committed','The physical watch has another sale commitment.',status=409)
        except (KeyError,TypeError,ValueError):
            raise PublicError('orders_unavailable','The physical commitment is unavailable.',status=503) from None
        op_id=uuid4()
        remote_key='prebid:'+str(op_id)
        allocation={'operation_key':remote_key,'watch_id':str(lot['watch_id']),'listing_id':str(lot['listing_id']),
            'listing_revision':watch['listing_revision'],'expected_revision':watch['revision'],'source_id':str(auction_id),
            'kind':'prebid','buyer_id':str(subject),'quote_id':str(command.quote_id),'quote_revision':quote['revision'],
            'currency':quote['currency'],'total_minor':quote['payable_minor']}
        updated=await kernel.transition(tx,auction_id,expected_revision=lot['revision'],expected_end_version=lot['end_version'],from_mode='bidding',to_mode='prebid_pending')
        outcome={'operation_id':str(op_id),'auction_id':str(auction_id),'status':'pending','code':'reservation_pending','revision':updated['revision']}
        await tx.execute('''INSERT INTO auction_prebid_operations
            (id,auction_id,subject_id,operation_key,request_hash,remote_key,allocation,outcome,status,admission_revision)
            VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,'pending',$9)''',op_id,auction_id,subject,key,digest,remote_key,json.dumps(allocation),json.dumps(outcome),lot['revision'])
    # Intent + mode are committed before any allocation call. Crash here is recovered by worker.
    await tick(request.app,operation_id=op_id)
    async with request.app.state.pool.acquire() as tx:
        row=await existing(tx,subject,key,digest)
        return decoded(row['outcome'])
