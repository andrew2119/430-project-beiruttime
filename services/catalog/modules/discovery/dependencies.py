"""Bounded public contract reads; publication is never an availability claim."""
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator
from bt_bulkheads import Unavailable
from .models import PublicModel

class Availability(PublicModel):
    watch_id: UUID
    listing_id: UUID
    sale_mode: Literal['fixed','auction','seller_base']
    status: Literal['available','reserved','fenced']
    revision: StrictInt = Field(ge=1)
    is_demo: StrictBool

class Business(PublicModel):
    id: UUID
    public_name: str = Field(min_length=1,max_length=160)
    kind: Literal['dealer','brand']
    capabilities: list[Literal['sales','customization','servicing']]
    state: Literal['active','revoked']
    revision: StrictInt = Field(ge=1)
    sample: StrictBool
    platform_onboarded: StrictBool
    authenticated_business: StrictBool
    independent_watch_authentication_required: Literal[False] = False

class Timing(PublicModel):
    auction_id: UUID
    listing_id: UUID
    starts_at: AwareDatetime
    scheduled_ends_at: AwareDatetime
    current_ends_at: AwareDatetime
    server_time: AwareDatetime
    status: Literal['scheduled','live','ended']
    revision: StrictInt = Field(ge=1)
    rules_version: str = Field(min_length=1,max_length=100)
    extension_policy: str = Field(min_length=1,max_length=100)

    @model_validator(mode='after')
    def canonical_clock(self):
        expected='scheduled'if self.server_time<self.starts_at else'ended'if self.server_time>=self.current_ends_at else'live'
        if self.current_ends_at<=self.starts_at or self.scheduled_ends_at<=self.starts_at or self.current_ends_at<self.scheduled_ends_at or self.status!=expected:
            raise ValueError('Inconsistent canonical timing')
        if self.extension_policy=='none.v1'and self.current_ends_at!=self.scheduled_ends_at:
            raise ValueError('Ordinary auctions cannot invent an extension')
        return self

class TimingPage(PublicModel):
    version: Literal[1]
    items: list[Timing] = Field(max_length=100)
    server_time: AwareDatetime
    missing_listing_ids: list[UUID] = Field(max_length=100)
    next_cursor: UUID | None = None

class Credit(PublicModel):
    title: str = Field(max_length=500)
    author: str = Field(max_length=500)
    author_url: str = Field(max_length=1000)
    source_url: str = Field(max_length=1000)
    license: str = Field(max_length=200)
    license_url: str = Field(max_length=1000)
    changes: str = Field(max_length=1000)
    credit: str = Field(max_length=2000)
    alt_en: str = Field(max_length=500)
    alt_ar: str = Field(max_length=500)
    share_alike_required: StrictBool

class CreditItem(PublicModel):
    asset_id: UUID
    credit: Credit | None

class Credits(PublicModel):
    items: list[CreditItem] = Field(max_length=12)


async def request_model(client, path, model, *, params=None, request_id=None):
    if client is None:return None
    response=await client.request('GET',path,params=params,headers={'X-Request-ID':request_id} if request_id else {})
    if isinstance(response,Unavailable) or response.status_code!=200:return None
    try:return model.model_validate_json(response.content)
    except (ValueError,TypeError):return None


class Reads:
    def __init__(self, *, auction=None, orders=None, identity=None, media=None, request_id=None):
        self.auction,self.orders,self.identity,self.media=auction,orders,identity,media
        self.request_id=request_id

    async def availability(self, source):
        result=await request_model(self.orders,'/v1/listings/'+str(source.id)+'/availability',Availability,request_id=self.request_id)
        if result is None or result.listing_id!=source.id or result.watch_id!=source.physical_watch_id or result.sale_mode!=source.registration.sale_mode or result.is_demo!=source.is_demo:return None
        return result

    async def business(self, source):
        if source.organization_id is None:return None
        result=await request_model(self.identity,'/v1/businesses/'+str(source.organization_id),Business,request_id=self.request_id)
        return result if result and result.id==source.organization_id and result.kind==source.seller_type else None

    async def timing_batch(self, ids):
        if not ids:return {},set()
        if len(ids)>100:raise ValueError('Timing candidate budget exceeded')
        page=await request_model(self.auction,'/v1/auction-timing',TimingPage,params={'listing_ids':','.join(map(str,ids)),'status':'all','limit':100},request_id=self.request_id)
        if page is None or page.next_cursor is not None or any(item.server_time!=page.server_time for item in page.items):return None,None
        requested=set(ids);found={}
        for item in page.items:
            if item.listing_id not in requested or item.listing_id in found:return None,None
            found[item.listing_id]=item
        missing=set(page.missing_listing_ids)
        if set(found)&missing or set(found)|missing!=requested:return None,None
        return found,missing

    async def endings(self, cursor=None, limit=100):
        params={'status':'active','limit':limit}
        if cursor:params['cursor']=str(cursor)
        page=await request_model(self.auction,'/v1/auction-timing',TimingPage,params=params,request_id=self.request_id)
        if page is None or page.missing_listing_ids or any(item.server_time!=page.server_time for item in page.items):return None
        positions=[(item.current_ends_at,str(item.auction_id))for item in page.items]
        if positions!=sorted(positions) or len({item.auction_id for item in page.items})!=len(page.items) or any(item.status=='ended' for item in page.items):return None
        return page

    async def credits(self, source):
        page=await request_model(self.media,'/v1/listings/'+str(source.id)+'/photo-credits',Credits,request_id=self.request_id)
        if page is None:return None
        values={item.asset_id:item.credit for item in page.items}
        if len(values)!=len(page.items) or set(values)!=set(source.photo_ids):return None
        if source.is_demo and any(value is None for value in values.values()):return None
        return values


def from_app(app, request_id=None):
    return Reads(auction=getattr(app.state,'discovery_auction',None),orders=getattr(app.state,'discovery_orders',None),identity=getattr(app.state,'discovery_identity',None),media=getattr(app.state,'discovery_media',None),request_id=request_id)
