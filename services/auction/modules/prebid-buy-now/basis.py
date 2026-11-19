"""Private source binding for Pricing/Orders current quote validation after safe freeze."""
from uuid import UUID
import jwt
from fastapi import HTTPException, Request
from bt_contracts_core.errors import AccessDenied, PublicError
from service_app.engine import decoded
from .kernel import get_kernel


def service(request):
    settings=request.app.state.settings
    if not settings.service_auth_public_key:
        raise PublicError('service_auth_unavailable','Current quote binding is unavailable.',status=503)
    scheme,_,token=request.headers.get('authorization','').partition(' ')
    if scheme.lower()!='bearer' or not token or len(token)>8192:raise HTTPException(401)
    try:
        claims=jwt.decode(token,settings.service_auth_public_key,algorithms=['RS256'],issuer=settings.auth_issuer,
            audience='auction',options={'require':['exp','iat','iss','aud','sub','type']})
    except jwt.InvalidTokenError:raise HTTPException(401) from None
    if claims['type']!='service' or claims['sub'] not in {'pricing','orders'}:
        raise AccessDenied('Wrong quote-binding service scope')


async def quote_basis(auction_id:UUID,quote_id:UUID,buyer_id:UUID,request:Request):
    service(request)
    get_kernel()
    async with request.app.state.pool.acquire() as tx:
        # One snapshot; no private source facts cross the browser gateway or public events.
        row=await tx.fetchrow('''SELECT p.*,l.mode,l.revision AS current_revision,l.watch_id,l.listing_id,
            l.currency,l.buy_now_minor FROM auction_prebid_operations p JOIN auction_lots l ON l.id=p.auction_id
            WHERE p.auction_id=$1 AND p.subject_id=$2''',auction_id,buyer_id)
    if not row:raise PublicError('not_found','Current source binding not found.',status=404)
    value=decoded(row['allocation'])
    if value.get('quote_id')!=str(quote_id):raise PublicError('not_found','Current source binding not found.',status=404)
    if (row['admission_revision'] is None or row['status']=='denied' or row['mode'] not in {'prebid_pending','prebid_reserved'}
        or value.get('source_id')!=str(auction_id) or value.get('watch_id')!=str(row['watch_id'])
        or value.get('listing_id')!=str(row['listing_id']) or value.get('currency')!=row['currency']):
        raise PublicError('source_changed','The current purchase source cannot be confirmed.',status=409)
    return {'auction_id':str(auction_id),'buyer_id':str(buyer_id),'quote_id':str(quote_id),
        'quote_revision':value['quote_revision'],'admission_revision':row['admission_revision'],
        'current_revision':row['current_revision'],'watch_id':str(row['watch_id']),'listing_id':str(row['listing_id']),
        'listing_revision':value['listing_revision'],'currency':row['currency'],'price_minor':row['buy_now_minor'],
        'total_minor':value['total_minor'],'mode':row['mode'],'prepared_at':row['created_at'].isoformat()}
