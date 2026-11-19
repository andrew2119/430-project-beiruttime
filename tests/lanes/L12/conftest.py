import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
import httpx
import pytest_asyncio
from bt_bulkheads import DependencyClient
from bt_contracts_core.models import Actor
from bt_runtime.app.db import create_pool
from bt_runtime.app.settings import Settings
from bt_runtime.principal import CurrentPrincipal
from service_app.main import create_app
from service_app.dependencies import Dependencies

SELLER, BUYER, OTHER, WATCH, LISTING = [uuid4() for _ in range(5)]


class Fixtures(Dependencies):
    def __init__(self):
        self.quotes={}
        self.remote={}
        self.posts=0
        self.lose_response=False
        self.unavailable=False
        self.deny=False
        self.auction_id=None
        self.auction_committed=False
        self.watch_revision=1
        self.reserved=False
        self.actors={str(actor):CurrentPrincipal(actor=Actor(subject_id=actor,session_id='sample'),roles=['buyer','private_seller'],permissions=['identity.listings.publish']) for actor in [SELLER,BUYER,OTHER]}
        super().__init__({name:DependencyClient(name,f'http://{name}',timeout=.5,concurrency=2,transport=httpx.MockTransport(self.handle)) for name in ['pricing','orders']})

    async def principal(self,request): return self.actors[request.headers['authorization'].removeprefix('Bearer ')]
    async def listing(self,request,listing_id):
        return {'id':str(LISTING),'watch_id':str(WATCH),'seller_id':str(SELLER),'seller_organization_id':None,'status':'published','revision':1}
    async def fence(self,request,listing,auction_id,key):
        self.auction_id=str(auction_id)
        self.watch_revision=2
        return str(auction_id)
    async def check_fence(self,*args): pass
    async def fee(self,*args): return datetime.now(timezone.utc)+timedelta(minutes=5)
    def service_headers(self,*args): return {'Authorization':'Bearer fixture-service'}
    async def contact(self,*args): pass

    def handle(self,request):
        if request.url.host=='pricing':
            value=self.quotes.get(request.url.path.rsplit('/',1)[-1])
            return httpx.Response(200,json=value) if value else httpx.Response(404)
        if self.unavailable:return httpx.Response(503)
        if request.url.path.startswith('/internal/v2/watches/'):
            return httpx.Response(200,json={'watch_id':str(WATCH),'listing_id':str(LISTING),'listing_revision':1,'revision':self.watch_revision,'source_id':self.auction_id,'status':'reserved' if self.reserved else 'fenced','auction_committed':self.auction_committed})
        if request.method=='GET':
            value=self.remote.get(request.url.path.rsplit('/',1)[-1])
            return httpx.Response(200,json=value) if value else httpx.Response(404)
        body=json.loads(request.content)
        key=request.headers['idempotency-key']
        assert key==body['operation_key']
        if request.url.path=='/internal/v2/commitments':
            if key not in self.remote:
                self.auction_committed=True
                self.watch_revision+=1
                self.remote[key]={'id':str(uuid4()),'status':'succeeded'}
            return httpx.Response(200,json=self.remote[key])
        if key not in self.remote:
            self.posts+=1
            denied=self.deny or self.reserved or self.auction_committed or body['expected_revision']!=self.watch_revision
            if not denied:
                self.reserved=True
                self.watch_revision+=1
            self.remote[key]={'id':str(uuid4()),'status':'denied' if denied else 'succeeded','order':{'id':str(uuid4()),'watch_id':body['watch_id'],'listing_id':body['listing_id'],'buyer_id':body['buyer_id'],'quote_id':body['quote_id'],'currency':body['currency'],'total_minor':body['total_minor']}}
        return httpx.Response(503) if self.lose_response else httpx.Response(200,json=self.remote[key])

    def quote(self,auction,revision,**overrides):
        id=uuid4()
        self.quotes[str(id)]={'id':str(id),'owner_id':str(BUYER),'subject_id':str(auction),'subject_revision':revision,'revision':1,'purpose':'purchase','kind':'prebid','auction_id':str(auction),'watch_id':str(WATCH),'listing_id':str(LISTING),'listing_revision':1,'source':'auction','source_verified':True,'reviewed_at':datetime.now(timezone.utc).isoformat(),'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(),'price_minor':500000,'payable_minor':515000,'currency':'USD',**overrides}
        return str(id)


def headers(actor=BUYER,key=None,revision=None):
    return {'Authorization':'Bearer '+str(actor),'Idempotency-Key':key or str(uuid4()),**({'If-Match':str(revision)} if revision else {})}


@pytest_asyncio.fixture
async def api(database_url):
    fixture=Fixtures()
    app=create_app(Settings(database_url=database_url,modules_path=Path(os.environ.get('BT_MODULES_PATH','/app/modules'))),fixture)
    app.state.pool=await create_pool(database_url)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        now=datetime.now(timezone.utc)
        result=await client.post('/v1/auctions',headers=headers(SELLER),json={'listing_id':str(LISTING),'currency':'USD','opening_minor':400000,'reserve_minor':450000,'increment_bands':[{'from_minor':0,'step_minor':10000}],'starts_at':(now-timedelta(minutes=1)).isoformat(),'ends_at':(now+timedelta(minutes=10)).isoformat()})
        assert result.status_code==200,result.text
        auction=result.json()['auction_id']
        yield client,app,fixture,UUID(auction)
    await app.state.pool.close()
    await fixture.close()
