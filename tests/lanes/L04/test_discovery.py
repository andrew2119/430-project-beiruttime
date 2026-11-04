"""Isolated Catalog view + strict provider HTTP fixtures; never startup/demo seeds."""
import asyncio
import copy
import importlib
import json
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from uuid import UUID
import asyncpg
import httpx
import pytest
import pytest_asyncio
from pydantic import ValidationError
from bt_bulkheads import DependencyClient
from bt_contracts_core.errors import PublicError
from bt_runtime.app import db
from bt_runtime import testing as runtime_testing
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.modules import discover
from fixture_data import listing_id,source_row,reference,change_mode
from fixture_reads import State

module=next(m for m in discover(Path('/app/modules'))if m.id=='L04.discovery')
def loaded(file,name):return importlib.import_module(module.load(file+':'+name).__module__)
repository=loaded('search.py','candidates')
service=loaded('service.py','find')
models=loaded('models.py','WatchDetail')
dependencies=loaded('dependencies.py','Reads')
upstream=loaded('upstream.py','read_auction')
FIXTURES=Path('/opt/domain-contracts/bt_contracts/catalog/discovery/fixtures')
WATCH=json.loads((FIXTURES/'watch.v1.json').read_text())
AUCTION=json.loads((FIXTURES/'auction.v1.json').read_text())
PROVIDER_AUCTION=json.loads((FIXTURES/'provider-auction.v1.json').read_text())
PROVIDER_HISTORY=json.loads((FIXTURES/'provider-history.v1.json').read_text())

@pytest_asyncio.fixture
async def database_access(monkeypatch):
    # Module-scoped override: an external conftest would also shadow common proofs.
    monkeypatch.setenv('BT_MODULES_PATH','/app/modules/discovery')
    generator=runtime_testing.database_access.__wrapped__()
    access=await anext(generator)
    try:yield access
    finally:await generator.aclose()


async def provider(owner_url,count=1,rows=None):
    rows=rows if rows is not None else[source_row(i)for i in range(count)]
    owner=await asyncpg.connect(owner_url)
    await owner.execute('''CREATE TABLE catalog_listings(
      id uuid PRIMARY KEY,owner_subject_id uuid NOT NULL,organization_id uuid,seller_type text NOT NULL,seller_label text NOT NULL,
      physical_watch_id uuid NOT NULL,revision bigint NOT NULL,status text NOT NULL,facts jsonb NOT NULL,
      photo_ids uuid[] NOT NULL,cover_id uuid NOT NULL,is_demo boolean NOT NULL,registration jsonb NOT NULL,rules_version text NOT NULL,
      published_at timestamptz NOT NULL,is_hidden boolean NOT NULL DEFAULT false,private_possession_document text NOT NULL DEFAULT 'do-not-disclose-private-evidence');''')
    await owner.execute((Path(__file__).parent/'fixtures/public-view.sql').read_text())
    for row in rows:
        await owner.execute('''INSERT INTO catalog_listings(id,owner_subject_id,organization_id,seller_type,seller_label,physical_watch_id,revision,status,facts,photo_ids,cover_id,is_demo,registration,rules_version,published_at,is_hidden)
          VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)''',UUID(row['id']),UUID(row['owner_subject_id']),UUID(row['organization_id'])if row['organization_id']else None,row['seller_type'],row['seller_label'],UUID(row['physical_watch_id']),row['revision'],row['status'],json.dumps(row['facts']),[UUID(v)for v in row['photo_ids']],UUID(row['cover_id']),row['is_demo'],json.dumps(row['registration']),row['rules_version'],row['published_at'],row['is_hidden'])
    return owner,rows

@asynccontextmanager
async def environment(database_url,owner_url,count=1,rows=None):
    owner,rows=await provider(owner_url,count,rows)
    pool=await db.create_pool(database_url)
    state=State(rows,PROVIDER_AUCTION);clients=state.clients();reads=dependencies.Reads(**clients)
    try:yield owner,pool,state,reads
    finally:
        await asyncio.gather(*(client.aclose()for client in clients.values()))
        await pool.close();await owner.close()


def test_filter_ranges_cursors_and_exact_money():
    Filters=repository.Filters
    for values in ({'min_minor':2,'max_minor':1},{'min_minor':-1},{'max_minor':1.5},{'sort':'injected'},{'limit':25},{'q':'word '*9}):
        with pytest.raises(PublicError):Filters(**values)
    now=datetime.now(timezone.utc);filters=Filters(brand='Rolex')
    cursor=repository.encode_cursor(filters,'430000',listing_id(),now)
    assert repository.decode_cursor(cursor,filters,now)[1]==listing_id()
    for value in ('!','x'*1025,cursor[:-8]):
        with pytest.raises(PublicError):repository.decode_cursor(value,filters,now)
    with pytest.raises(PublicError):repository.decode_cursor(cursor,Filters(brand='Omega'),now)
    with pytest.raises(PublicError):repository.decode_cursor(cursor,filters,now+timedelta(days=2))
    for amount in ('NaN','Infinity','1.001','-1',1.1):
        with pytest.raises(ValidationError):models.PublicMoney(amount=amount,currency='USD')


def test_public_models_reject_private_fields_and_false_business_inspection():
    watch=copy.deepcopy(WATCH);watch['private_documents']=['never-disclose']
    with pytest.raises(ValidationError):models.WatchDetail.model_validate(watch)
    watch=copy.deepcopy(WATCH);watch['seller']['kind']='dealer'
    with pytest.raises(ValidationError):models.WatchDetail.model_validate(watch)
    watch['assurance']={'kind':'official_business','status':'onboarded'}
    assert models.WatchDetail.model_validate(watch).assurance.kind=='official_business'
    for url in ('https://host/private','/api/web/v1/catalog/v1/media/private','/demo/watches/../private','/demo/watches/%2e%2e/private'):
        with pytest.raises(ValidationError):models.Photo(id='photo',url=url,alt='Photo')


@pytest.mark.asyncio
async def test_conjunctive_arabic_filters_current_availability_and_keysets(database_url,database_owner_url):
    async with environment(database_url,database_owner_url,17)as(owner,pool,state,reads):
        filters=repository.Filters(q='رولكس بيروت',model='١٢٤٣٠٠',min_minor=430000,max_minor=430000,sort='price_asc',limit=5)
        ids=[];cursor=''
        while True:
            page=await service.find(pool,reads,filters,cursor);ids.extend(item.id for item in page.items);cursor=page.next_cursor
            if not cursor:break
        assert ids==[listing_id(i)for i in range(17)]
        for values in ({'brand':'Omega'},{'location':'Tripoli'},{'min_minor':430001},{'currency':'LBP'}):
            assert not(await service.find(pool,reads,repository.Filters(**values))).items
        await owner.execute("UPDATE catalog_listings SET facts=jsonb_set(jsonb_set(facts,'{brand}',$1::jsonb),'{location}',$2::jsonb)",json.dumps('رولكس'),json.dumps('بيروت'))
        assert len((await service.find(pool,reads,repository.Filters(brand='Rolex',location='Beirut'))).items)==12
        state.order_states[listing_id(0)]='reserved'
        assert listing_id(0)not in[item.id for item in(await service.find(pool,reads,repository.Filters())).items]


@pytest.mark.asyncio
async def test_hidden_draft_future_and_restart_never_disclose_private_content(database_url,database_owner_url):
    async with environment(database_url,database_owner_url,4)as(owner,pool,state,reads):
        first=await service.find(pool,reads,repository.Filters(limit=1))
        await owner.execute("UPDATE catalog_listings SET is_hidden=true WHERE id=$1",UUID(listing_id(1)))
        await owner.execute("UPDATE catalog_listings SET status='draft' WHERE id=$1",UUID(listing_id(2)))
        await owner.execute("UPDATE catalog_listings SET published_at=clock_timestamp()+interval '1 hour' WHERE id=$1",UUID(listing_id(3)))
        assert not(await service.find(pool,reads,repository.Filters(limit=1),first.next_cursor)).items
        for index in (1,2,3):
            with pytest.raises(PublicError)as error:await service.raw_detail(pool,listing_id(index))
            assert error.value.status==404
        await pool.close();reopened=await db.create_pool(database_url)
        try:assert str((await service.raw_detail(reopened,listing_id())).id)==listing_id()
        finally:await reopened.close()


@pytest.mark.asyncio
async def test_ending_order_comes_from_real_contract_timing_not_publication_dates(database_url,database_owner_url):
    async with environment(database_url,database_owner_url,4)as(owner,pool,state,reads):
        now=datetime.now(timezone.utc)
        for index,seconds in enumerate((-1,0,60,120)):
            state.auctions[listing_id(index)]['ends_at']=(now+timedelta(seconds=seconds)).isoformat()
            state.auctions[listing_id(index)]['status']='ended'if seconds<=0 else'live'
        state.order_states[listing_id(3)]='reserved'
        result=await service.find(pool,reads,repository.Filters(sort='ending_soon'))
        assert[item.id for item in result.items]==[listing_id(2)]
        assert result.items[0].ends_at==now+timedelta(seconds=60)
        assert(await service.view(pool,reads,listing_id(3))).sale_state=='reserved'
        state.auction_unavailable=True
        with pytest.raises(PublicError)as error:await service.find(pool,reads,repository.Filters(sort='ending_soon'))
        assert error.value.status==503


@pytest.mark.asyncio
async def test_ending_cursor_preserves_provider_order_and_filter_scope(database_url,database_owner_url):
    async with environment(database_url,database_owner_url,17)as(owner,pool,state,reads):
        filters=repository.Filters(sort='ending_soon',limit=5);ids=[];cursor=''
        while True:
            page=await service.find(pool,reads,filters,cursor);ids.extend(item.id for item in page.items);cursor=page.next_cursor
            if not cursor:break
        assert ids==[listing_id(i)for i in range(17)]
        assert len(set(ids))==17


@pytest.mark.asyncio
async def test_publication_is_not_stock_and_media_failure_does_not_invent_absence(database_url,database_owner_url):
    row=source_row();change_mode(row,'fixed_price')
    async with environment(database_url,database_owner_url,rows=[row])as(owner,pool,state,reads):
        assert(await service.view(pool,reads,listing_id())).sale_state=='available'
        state.orders_unavailable=True
        detail=await service.view(pool,reads,listing_id())
        assert detail.sale_state=='unavailable'and len(detail.photos)==2
        with pytest.raises(PublicError):await service.find(pool,reads,repository.Filters())
        state.orders_unavailable=False;state.credits_unavailable=True
        detail=await service.view(pool,reads,listing_id())
        assert detail.sale_state=='available'and detail.media_state=='unavailable'and not detail.photos
        state.auction_unavailable=True
        assert(await service.find(pool,reads,repository.Filters())).items  # fixed stock is independent of Auction


@pytest.mark.asyncio
async def test_business_assurance_is_current_and_not_an_independent_pass(database_url,database_owner_url):
    row=source_row();change_mode(row,'fixed_price');row.update(seller_type='dealer',seller_label='Sample business',organization_id=reference('3'))
    async with environment(database_url,database_owner_url,rows=[row])as(owner,pool,state,reads):
        detail=await service.view(pool,reads,listing_id())
        assert detail.assurance.kind=='official_business'and detail.assurance.status=='onboarded'
        assert detail.seller.completed_sales is None
        state.revoked_businesses.add(reference('3'))
        detail=await service.view(pool,reads,listing_id())
        assert detail.assurance.status=='unavailable'and detail.sale_state=='unavailable'
        assert not(await service.find(pool,reads,repository.Filters())).items
        state.revoked_businesses.clear();state.identity_unavailable=True
        with pytest.raises(PublicError):await service.find(pool,reads,repository.Filters())


@pytest.mark.asyncio
async def test_offer_without_listed_price_is_not_zero_or_an_order(database_url,database_owner_url):
    row=source_row();change_mode(row,'offer');row['facts']['price_minor']=None
    async with environment(database_url,database_owner_url,rows=[row])as(owner,pool,state,reads):
        item=(await service.find(pool,reads,repository.Filters())).items[0]
        assert item.price is None and item.sale_mode=='offer'and item.sale_state=='available'
        assert not(await service.find(pool,reads,repository.Filters(min_minor=1))).items


@pytest.mark.asyncio
async def test_http_canonical_scope_errors_and_no_public_commands(database_url,database_owner_url):
    app=create_app(Settings(database_url=database_url));clients={};owner=None
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test')as client:
            assert(await client.get('/v1/discovery/watches')).status_code==503
            owner,rows=await provider(database_owner_url)
            state=State(rows,PROVIDER_AUCTION);clients=state.clients()
            while not hasattr(app.state,'discovery_media'):await asyncio.sleep(0)
            for name,value in clients.items():setattr(app.state,'discovery_'+name,value)
            try:
                response=await client.get('/v1/listings/'+listing_id())
                assert response.status_code==200 and response.json()['revision']==3
                assert response.json()['registration']['revision']==1  # independent registration, NOT current fence
                assert 'do-not-disclose'in(await owner.fetchval('SELECT private_possession_document FROM catalog_listings LIMIT 1'))
                assert 'do-not-disclose'not in response.text
                assert(await client.get('/v1/discovery/watches?min_minor=١٠&max_minor=٩')).json()['error']['code']=='invalid_range'
                assert(await client.post('/v1/discovery/watches')).status_code==405
                await owner.execute('UPDATE catalog_listings SET is_hidden=true')
                assert(await client.get('/v1/listings/'+listing_id())).status_code==404
                assert(await client.get('/v1/discovery/watches/'+listing_id()+'/auction')).status_code==404
            finally:
                await owner.close();await asyncio.gather(*(value.aclose()for value in clients.values()))


@pytest.mark.asyncio
async def test_auction_core_public_mapping_private_fields_and_binding():
    async def call(payload,status=200,history=None):
        def transport(request):
            if request.url.path=='/v1/auctions':
                assert request.url.params['listing_id']==listing_id()
                return httpx.Response(status,json={'items':[payload]if payload else[]})
            assert request.url.path=='/v1/auctions/'+reference('5')+'/history'
            answer=copy.deepcopy(history or PROVIDER_HISTORY);answer['snapshot']=payload
            return httpx.Response(status,json=answer)
        client=DependencyClient('auction','http://fixture',transport=httpx.MockTransport(transport))
        try:return await upstream.read_auction(client,listing_id())
        finally:await client.aclose()
    result=await call(PROVIDER_AUCTION)
    assert result.state=='available'and result.snapshot.current_price.amount==4300 and result.snapshot.status=='open'
    assert result.snapshot.end_version==PROVIDER_AUCTION['revision']
    assert(await call({})).state=='not_started'
    assert(await call({},404)).state=='unavailable'
    for field,value in [('private_maximum','4500'),('reserve_minor',500000),('listing_id','another-watch')]:
        payload=copy.deepcopy(PROVIDER_AUCTION);payload[field]=value
        assert(await call(payload)).state=='unavailable'
    for field,value in [('bidder_id','private-account'),('bidder','00000000-0000-0000-0000-000000000001')]:
        payload=copy.deepcopy(PROVIDER_HISTORY);payload['items'][0][field]=value
        assert(await call(PROVIDER_AUCTION,history=payload)).state=='unavailable'
    payload=copy.deepcopy(PROVIDER_HISTORY);payload['items'].append(copy.deepcopy(payload['items'][0]))
    assert(await call(PROVIDER_AUCTION,history=payload)).state=='unavailable'


@pytest.mark.asyncio
async def test_auction_timeout_saturation_and_circuit_never_queue_or_acknowledge():
    released=asyncio.Event();entered=asyncio.Event()
    async def delayed(request):
        entered.set();await released.wait()
        return httpx.Response(200,json={'items':[PROVIDER_AUCTION]}if request.url.path=='/v1/auctions'else PROVIDER_HISTORY)
    client=DependencyClient('auction','http://fixture',timeout=.2,concurrency=1,transport=httpx.MockTransport(delayed))
    first=asyncio.create_task(upstream.read_auction(client,listing_id()))
    try:
        await entered.wait();assert(await upstream.read_auction(client,listing_id())).state=='unavailable'
        released.set();assert(await first).state=='available'
    finally:released.set();await client.aclose()
    attempts=0
    def failed(request):
        nonlocal attempts
        attempts+=1;return httpx.Response(503,json={'private':'must-not-leak'})
    client=DependencyClient('auction','http://fixture',failure_threshold=1,transport=httpx.MockTransport(failed))
    try:
        assert(await upstream.read_auction(client,listing_id())).state=='unavailable'
        assert(await upstream.read_auction(client,listing_id())).state=='unavailable'
        assert attempts==1
    finally:await client.aclose()


@pytest.mark.asyncio
async def test_auction_history_race_has_one_bounded_resync():
    old=copy.deepcopy(PROVIDER_AUCTION);old.update(accepted_sequence=50,revision=51,current_minor=900000,next_minimum_minor=910000)
    current=copy.deepcopy(old);current.update(accepted_sequence=51,revision=52,current_minor=910000,next_minimum_minor=920000)
    after_values=[]
    def transport(request):
        assert request.headers['X-Request-ID']=='l04-race-proof'
        if request.url.path=='/v1/auctions':return httpx.Response(200,json={'items':[old]})
        after=int(request.url.params['after_sequence']);after_values.append(after);last=50 if len(after_values)==1 else 51
        rows=[{'sequence':seq,'bidder':'bidder-abcd1234','amount_minor':400000+seq*10000,'automatic':False,'received_at':'2026-11-04T04:59:59Z'}for seq in range(after+1,last+1)]
        return httpx.Response(200,json={'items':rows,'has_more':last<51,'next_sequence':last,'snapshot':current})
    client=DependencyClient('auction','http://fixture',transport=httpx.MockTransport(transport))
    try:
        result=await upstream.read_auction(client,listing_id(),'l04-race-proof')
        assert result.state=='available'and result.snapshot.last_sequence==51 and result.snapshot.current_price.amount==9100
        assert result.snapshot.history_truncated and len(result.snapshot.bids)==50 and after_values==[0,1]
    finally:await client.aclose()


@pytest.mark.asyncio
async def test_slow_auction_is_unavailable_not_confirmation():
    async def slow(request):await asyncio.sleep(.2);return httpx.Response(200,json={'items':[PROVIDER_AUCTION]})
    client=DependencyClient('auction','http://fixture',timeout=.02,transport=httpx.MockTransport(slow))
    try:assert(await upstream.read_auction(client,listing_id())).state=='unavailable'
    finally:await client.aclose()
