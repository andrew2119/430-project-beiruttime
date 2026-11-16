from uuid import UUID
from fastapi import APIRouter, Request
from bt_contracts.auction.policy.models import PrebidCommand, PrebidQuoteBasis
from bt_contracts_core.errors import AccessDenied, PublicError
from service_app.engine import decoded, fingerprint, key_for
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
    key=key_for(request)
    digest=fingerprint('prebid',auction_id,command)
    async with request.app.state.pool.acquire() as tx:
        # Exact historical replay is a read, not permission for another allocation.
        replay=await existing(tx,subject,key,digest)
        if replay: return decoded(replay['outcome'])
    raise PublicError('auction_purchase_removed', 'Auctions do not offer Buy Now.', status=409)
