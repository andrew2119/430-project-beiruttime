"""Bounded Orders v2 operations. Unknown results never release the auction mode."""
from datetime import datetime
from uuid import UUID
from bt_bulkheads import Unavailable
from bt_contracts_core.errors import PublicError


async def quote(request, quote_id, auction_id, principal):
    engine = request.app.state.auction
    value = await engine.dependencies.json('pricing','GET',f'/v1/auction-quotes/{quote_id}',request)
    try:
        # Exact retained quote, not browser supplied money. Orders validates again at allocation.
        if (value['owner_id']!=str(principal.actor.subject_id) or value['subject_id']!=str(auction_id)
            or value['purpose']!='purchase' or value['kind']!='prebid' or value['reviewed_at'] is None
            or value['source']!='auction' or value['source_verified'] is not True):
            raise ValueError()
        for field in ('revision','subject_revision','listing_revision','price_minor','payable_minor'):
            if type(value[field]) is not int or not 1<=value[field]<=9_000_000_000_000_000: raise ValueError()
        if value['currency'] not in ('USD','LBP'): raise ValueError()
        expiry=datetime.fromisoformat(value['expires_at'].replace('Z','+00:00'))
        if expiry.tzinfo is None: raise ValueError()
        for field in ('id','auction_id','watch_id','listing_id'):UUID(value[field])
        if value['id']!=str(quote_id): raise ValueError()
        return value,expiry
    except (KeyError,TypeError,ValueError):
        raise PublicError('quote_invalid','Review the current exact auction Buy Now quote.',status=409) from None


async def watch(request, watch_id):
    deps=request.app.state.auction.dependencies
    return await deps.json('orders','GET',f'/internal/v2/watches/{watch_id}',request,
        headers=deps.service_headers(request,'orders'))


async def reconcile_remote(app, allocation, remote_key, request_id):
    # A Request isn't retained across restart. Reconstruct only service auth context.
    from types import SimpleNamespace
    request=SimpleNamespace(app=app,state=SimpleNamespace(request_id=request_id),headers={})
    deps=app.state.auction.dependencies
    headers={**deps.service_headers(request,'orders'),'X-Request-ID':request_id,'Idempotency-Key':remote_key}
    client=deps.clients['orders']
    result=await client.request('GET',f'/internal/v2/operations/{remote_key}',headers=headers)
    if not isinstance(result,Unavailable) and result.status_code==404:
        result=await client.request('POST','/internal/v2/allocations',headers=headers,json=allocation)
    if isinstance(result,Unavailable) or result.status_code!=200: return None
    try:
        value=result.json()
        if value.get('status') not in ('succeeded','denied'): return None
        UUID(value['id'])
        if value['status']=='succeeded':
            order=value['order']
            if (order['watch_id']!=allocation['watch_id'] or order['buyer_id']!=allocation['buyer_id']
                or order['listing_id']!=allocation['listing_id'] or order['quote_id']!=allocation['quote_id']
                or order['currency']!=allocation['currency'] or type(order['total_minor']) is not int
                or order['total_minor']!=allocation['total_minor']): return None
            UUID(order['id'])
        return value
    except (KeyError,TypeError,ValueError): return None
