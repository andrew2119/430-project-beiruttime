from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from bt_bulkheads import DependencyClient
from bt_contracts_core.errors import PublicError
from service_app.dependencies import Dependencies


@pytest.mark.asyncio
@pytest.mark.parametrize('broken',[None,'watch','listing','sale','organization','missing'])
async def test_canonical_publication_binding(broken):
    listing, watch, seller, organization = [uuid4() for _ in range(4)]
    body={'id':str(listing),'physical_watch_id':str(watch),'seller_id':str(seller),
          'organization_id':str(organization),'status':'published','facts':{'sale_mode':'auction'},
          'registration':{'watch_id':str(watch),'listing_id':str(listing),'sale_mode':'auction','revision':1}}
    if broken=='watch': body['registration']['watch_id']=str(uuid4())
    if broken=='listing': body['registration']['listing_id']=str(uuid4())
    if broken=='sale': body['facts']['sale_mode']='fixed_price'
    if broken=='organization': body['organization_id']='invalid'
    if broken=='missing': del body['physical_watch_id']
    def response(request):
        assert request.url.path==f'/v1/listings/{listing}'
        return httpx.Response(200,json=body)
    client=DependencyClient('catalog','http://catalog',transport=httpx.MockTransport(response))
    dependencies=Dependencies({'catalog':client})
    request=SimpleNamespace(headers={'authorization':'Bearer test'},state=SimpleNamespace(request_id='test'))
    try:
        if broken:
            with pytest.raises(PublicError): await dependencies.listing(request,listing)
        else:
            result=await dependencies.listing(request,listing)
            assert result=={'id':str(listing),'watch_id':str(watch),'seller_id':str(seller),'seller_organization_id':str(organization),'status':'published'}
    finally:
        await dependencies.close()
