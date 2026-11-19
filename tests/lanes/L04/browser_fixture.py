"""Opt-in isolated Catalog/public-HTTP fixture, NOT real bid admission or demo stock.

Every record is labeled sample content. Production never loads these routes or
transport adapters; connected owning-service acceptance is a separate gate.
"""
import asyncio
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from uuid import UUID
def repository_root(source):
    for parent in Path(source).resolve().parents:
        if (parent / 'contracts/registrations/L04.json').is_file():
            return parent
    return None


def _module(path, identifier):
    manifest = path / 'module.json'
    return manifest.is_file() and json.loads(manifest.read_text())['id'] == identifier


def catalog_modules(source):
    explicit = os.environ.get('BT_MODULES_PATH')
    repo = repository_root(source)
    candidates = [Path(explicit)] if explicit else (
        ([repo / 'services/catalog/modules'] if repo else []) + [Path('/app/modules')]
    )
    for root in candidates:
        # Discovery-only invocations must still resolve the owning Catalog tree.
        if _module(root, 'L04.discovery'):
            root = root.parent
        if all(_module(root / name, identifier) for name, identifier in (
            ('listings', 'L03.listings'), ('media', 'L03.media'), ('discovery', 'L04.discovery')
        )):
            return root
    raise RuntimeError('Verified Catalog modules unavailable')


def discovery_modules(source):
    return catalog_modules(source) / 'discovery'


def contract_fixtures(source):
    explicit = os.environ.get('BT_NATIVE_CONTRACT_ROOT')
    repo = repository_root(source)
    names = ['watch.v1.json', 'auction.v1.json', 'provider-auction.v1.json', 'provider-history.v1.json']
    native = []
    if repo:
        registration = json.loads((repo / 'contracts/registrations/L04.json').read_text())
        contract = next(c for c in registration['contracts'] if c['namespace'] == 'catalog.discovery.v1')
        names = [Path(name).name for name in contract['fixtures']]
        native = [repo / contract['path'] / 'fixtures']
    candidates = [Path(explicit) / 'bt_contracts/catalog/discovery/fixtures'] if explicit else native + [
        Path('/opt/domain-contracts/bt_contracts/catalog/discovery/fixtures'),
    ]
    for root in candidates:
        if all((root / name).is_file() for name in names):
            return root
    raise RuntimeError('Registered Discovery contract fixtures unavailable')



async def main():
    import uvicorn
    from fastapi import HTTPException,Request
    from fastapi.responses import Response
    from bt_runtime.testing import database_access
    from bt_runtime.app.main import create_app
    from bt_runtime.app.settings import Settings
    from fixture_data import source_row,listing_id,reference,change_mode
    from fixture_reads import State
    from test_discovery import provider,PROVIDER_AUCTION

    os.environ['BT_MODULES_PATH']=str(discovery_modules(__file__))
    wrapped=database_access.__wrapped__
    access_generator=wrapped(SimpleNamespace(param='service'),Path('/tmp'))if inspect.signature(wrapped).parameters else wrapped()
    access=await anext(access_generator)
    rows=[source_row(index)for index in range(18)]
    change_mode(rows[1],'fixed_price');rows[1]['facts'].update(modified=True,reference='REF-TEST-36',modifications=[{'component':'Aftermarket strap','provenance':'aftermarket','modifier':'Declared sample modifier','warranty_issuer':'No manufacturer warranty claimed','notes':'Contract fixture: review seller disclosure.'}])
    for index,kind in ((2,'dealer'),(3,'brand')):
        change_mode(rows[index],'fixed_price');rows[index].update(seller_type=kind,seller_label='Sample business fixture',organization_id=reference('3',index))
    change_mode(rows[4],'fixed_price');rows[4]['facts']['price_minor']=1_000_000_000_000
    change_mode(rows[5],'offer');rows[5]['facts']['price_minor']=None
    owner,_=await provider(access.owner_url,rows=rows)
    state=State(rows,PROVIDER_AUCTION)
    state.revoked_businesses.add(rows[3]['organization_id'])
    state.order_states[listing_id(6)]='reserved'
    del state.auctions[listing_id(7)]
    # Public current_minor=0 is an empty canonical lot, not a free watch.
    empty=state.auctions[listing_id(8)]
    empty.update(current_minor=0,accepted_sequence=0,revision=1,leader=None,next_minimum_minor=empty['opening_minor'])
    state.histories[empty['id']]=[]
    # Quiet private ceiling receipts create gaps without invented public rows.
    state.auctions[listing_id(9)].update(accepted_sequence=60,revision=61)
    state.auctions[listing_id(10)].update(accepted_sequence=2,revision=3)
    clients=state.clients();app=create_app(Settings(database_url=access.runtime_url));lifespan=app.router.lifespan_context
    media_unavailable=False;media_requests=0

    @asynccontextmanager
    async def with_fixture(app):
        async with lifespan(app):
            async with asyncio.timeout(2):
                while not hasattr(app.state,'discovery_media'):await asyncio.sleep(0)
            for name,client in clients.items():setattr(app.state,'discovery_'+name,client)
            yield
    app.router.lifespan_context=with_fixture

    def guard(request):
        if request.headers.get('X-L04-Fixture-Key')!='contract-proof-only':raise HTTPException(403)

    @app.get('/v1/listings/{identifier}/photos/{asset}/{variant}')
    async def media(identifier:str,asset:str,variant:str):
        nonlocal media_requests
        media_requests+=1
        if media_unavailable or variant not in ('thumb','card','detail'):raise HTTPException(404)
        try:UUID(identifier);parsed=UUID(asset)
        except ValueError:raise HTTPException(404)from None
        async with app.state.pool.acquire(timeout=1)as conn:
            if not await conn.fetchval('SELECT 1 FROM catalog_public_listings_v1 WHERE id=$1::text::uuid AND $2::text::uuid=ANY(photo_ids)',identifier,asset):raise HTTPException(404)
        color='#b2a17b'if parsed.int%2 else'#72877b'
        image=f'<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="1400"><rect width="1400" height="1400" fill="{color}"/><circle cx="700" cy="650" r="360" fill="none" stroke="#173c34" stroke-width="30"/><text x="700" y="650" text-anchor="middle" font-family="sans-serif" font-size="48" fill="#173c34">CONTRACT TEST IMAGE</text><text x="700" y="740" text-anchor="middle" font-family="sans-serif" font-size="32" fill="#173c34">NOT A WATCH PHOTOGRAPH</text></svg>'
        return Response(image,media_type='image/svg+xml')

    @app.post('/__fixture__/advance')
    async def advance(request:Request):
        guard(request);snapshot=state.auctions[listing_id()]
        snapshot['revision']+=1;snapshot['accepted_sequence']+=1;snapshot['current_minor']+=10000;snapshot['next_minimum_minor']=snapshot['current_minor']+10000;snapshot['leader']='Bidder B20F'
        state.histories[snapshot['id']].append({'sequence':snapshot['accepted_sequence'],'bidder':'Bidder B20F','amount_minor':snapshot['current_minor'],'automatic':False,'received_at':datetime.now(timezone.utc).isoformat()})
        return {'fixture':True,'sequence':snapshot['accepted_sequence']}

    @app.post('/__fixture__/availability/{availability}')
    async def availability(availability:str,request:Request):
        guard(request);state.auction_unavailable=availability=='unavailable'
        return {'fixture':True,'unavailable':state.auction_unavailable}

    @app.post('/__fixture__/orders/{availability}')
    async def orders(availability:str,request:Request):
        guard(request);state.orders_unavailable=availability=='unavailable'
        return {'fixture':True,'unavailable':state.orders_unavailable}

    @app.post('/__fixture__/credits/{availability}')
    async def credits(availability:str,request:Request):
        guard(request);state.credits_unavailable=availability=='unavailable'
        return {'fixture':True,'unavailable':state.credits_unavailable}

    @app.post('/__fixture__/media/{availability}')
    async def media_state(availability:str,request:Request):
        nonlocal media_unavailable,media_requests
        guard(request);media_unavailable=availability=='unavailable';media_requests=0
        return {'fixture':True,'unavailable':media_unavailable}

    @app.get('/__fixture__/media')
    async def media_count(request:Request):
        guard(request);return {'fixture':True,'requests':media_requests}

    try:await uvicorn.Server(uvicorn.Config(app,host='0.0.0.0',port=8000,access_log=False)).serve()
    finally:
        await asyncio.gather(*(client.aclose()for client in clients.values()))
        await owner.close();await access_generator.aclose()

if __name__=='__main__':asyncio.run(main())
