import asyncio
import json
from uuid import UUID, uuid4
import pytest
from ..conftest import BRAND, DEALER
from ..service_operations_helpers import headers

OPTION='00000000-0011-4000-8000-000000000003'


def option(**changes):
    return {'brand_id':str(BRAND),'expected_revision':0,'label_en':'Automatic · demo','label_ar':'أوتوماتيكية · تجريبي',
        'caliber':'DEMO-A01','cases':['CASE-40'],'dials':['DIAL-3'],'hands':['HANDS-3'],'functions':['hours','minutes','seconds'],
        'quote_minor':25000,'currency':'USD','active':True,**changes}


def selection(**changes):
    return {'brand_id':str(BRAND),'option_id':OPTION,'expected_revision':0,'option_revision':1,
        'configuration':{'case':'CASE-40','dial':'DIAL-3','hands':'HANDS-3','functions':['hours','minutes']},**changes}


@pytest.mark.asyncio
async def test_brand_support_scope_money_and_identity_outage(movement):
    client,app,identity=movement
    assert (await client.put(f'/v1/options/movement/{OPTION}',json=option(),headers=headers('cross'))).status_code==403
    assert (await client.put(f'/v1/options/movement/{OPTION}',json=option(brand_id=str(DEALER)),headers=headers('dealer'))).status_code==409
    assert (await client.put(f'/v1/options/movement/{OPTION}',json=option(quote_minor=2.5),headers=headers())).status_code==422
    assert (await client.put(f'/v1/options/movement/{OPTION}',json=option(quote_minor=True),headers=headers())).status_code==422
    assert (await client.put(f'/v1/options/movement/{OPTION}',json=option(),headers=headers())).status_code==200
    items=(await client.get(f'/v1/options/movement?brand_id={BRAND}')).json()['items']
    assert items[0]['quote_minor']==25000 and items[0]['caliber']=='DEMO-A01'
    assert (await client.get(f'/v1/options/movement/{OPTION}')).json()['item']==items[0]
    assert (await client.get(f'/v1/options/movement?brand_id={DEALER}')).status_code==409
    identity.unavailable=True
    assert (await client.get(f'/v1/options/movement?brand_id={BRAND}')).status_code==503
    assert (await client.post('/v1/options/movement/selections',json=selection(),headers=headers('buyer'))).status_code==503


@pytest.mark.asyncio
async def test_selection_saved_for_review_replay_private_and_revision_bound(movement):
    client,app,identity=movement
    await client.put(f'/v1/options/movement/{OPTION}',json=option(),headers=headers())
    first=await client.post('/v1/options/movement/selections',json=selection(),headers=headers('buyer','movement-selection-v1'))
    assert first.status_code==200
    assert first.json()['status']=='supported_for_review'
    assert first.json()['physical_feasibility_pass'] is False
    assert first.json()['quote_impact']=={'minor':25000,'currency':'USD','indicative':True}
    assert (await client.post('/v1/options/movement/selections',json=selection(),headers=headers('buyer','movement-selection-v1'))).json()==first.json()
    saved=(await client.get(f'/v1/options/movement/selections/current?brand_id={BRAND}',headers=headers('buyer'))).json()['selection']
    assert saved==first.json()
    assert (await client.get(f'/v1/options/movement/selections/current?brand_id={BRAND}',headers=headers('other'))).json()['selection'] is None
    await client.put(f'/v1/options/movement/{OPTION}',json=option(expected_revision=1),headers=headers(key='movement-revise-v1'))
    stale=await client.post('/v1/options/movement/selections',json=selection(expected_revision=1),headers=headers('buyer','movement-stale-v1'))
    assert stale.status_code==409 and stale.json()['error']['code']=='stale_revision'
    async with app.state.pool.acquire() as tx:
        assert await tx.fetchval('SELECT count(*) FROM movement_selections')==1
        assert await tx.fetchval('SELECT count(*) FROM outbox')==3


@pytest.mark.asyncio
async def test_unsupported_case_dial_hands_and_complication_never_promise_feasibility(movement):
    client,app,identity=movement
    await client.put(f'/v1/options/movement/{OPTION}',json=option(),headers=headers())
    body=selection(configuration={'case':'UNSUPPORTED','dial':'UNKNOWN','hands':'WRONG','functions':['chronograph']})
    result=await client.post('/v1/options/movement/selections',json=body,headers=headers('buyer'))
    assert result.status_code==200
    assert result.json()['status']=='manual_review' and result.json()['unsupported']==['case','dial','hands','functions']
    assert result.json()['physical_feasibility_pass'] is False
    async with app.state.pool.acquire() as tx:
        event=json.loads(await tx.fetchval("SELECT envelope FROM outbox WHERE envelope->>'type'='catalog.movement-selected.v1'"))
        assert set(event['data'])=={'resource_id','revision'}
        assert 'UNSUPPORTED' not in json.dumps(event)


@pytest.mark.asyncio
async def test_concurrent_selection_serialized_and_old_key_content_refused(movement):
    client,app,identity=movement
    await client.put(f'/v1/options/movement/{OPTION}',json=option(),headers=headers())
    results=await asyncio.gather(*(client.post('/v1/options/movement/selections',json=selection(),headers=headers('buyer',f'movement-race-{i}')) for i in range(2)))
    assert sorted(result.status_code for result in results)==[200,409]
    first_index=next(i for i,result in enumerate(results) if result.status_code==200)
    assert (await client.post('/v1/options/movement/selections',json=selection(expected_revision=1),headers=headers('buyer',f'movement-race-{first_index}'))).status_code==409
    assert (await client.post('/v1/options/movement/selections',json=selection(option_id=str(uuid4()),expected_revision=1),headers=headers('buyer','unknown-option-v1'))).status_code==409


@pytest.mark.asyncio
async def test_arabic_digits_preserve_identified_references_and_paginate_all_options(movement):
    client,app,identity=movement
    for number in range(1,22):
        identifier=UUID(int=number)
        response=await client.put(f'/v1/options/movement/{identifier}',json=option(),headers=headers())
        assert response.status_code==200
    first=(await client.get(f'/v1/options/movement?brand_id={BRAND}')).json()
    assert len(first['items'])==20 and first['next_after']
    second=(await client.get(f'/v1/options/movement?brand_id={BRAND}&after={first["next_after"]}')).json()
    assert len(second['items'])==1 and second['next_after'] is None
    assert (await client.get(f'/v1/options/movement/{UUID(int=21)}')).json()['item']==second['items'][0]
    result=await client.post('/v1/options/movement/selections',json=selection(option_id=str(UUID(int=21)),configuration={
        'case':'CASE-٤٠','dial':'DIAL-۳','hands':'HANDS-٣','functions':['hours']}),headers=headers('buyer'))
    assert result.status_code==200 and result.json()['status']=='supported_for_review'
    assert result.json()['configuration']['case']=='CASE-40'


@pytest.mark.asyncio
async def test_saved_movement_keeps_exact_units_until_explicit_current_revision_save(movement):
    client,app,identity=movement
    await client.put(f'/v1/options/movement/{OPTION}',json=option(),headers=headers())
    first=(await client.post('/v1/options/movement/selections',json=selection(),headers=headers('buyer'))).json()
    assert first['quote_impact']['currency']=='USD'
    await client.put(f'/v1/options/movement/{OPTION}',json=option(expected_revision=1,quote_minor=25000000,currency='LBP'),headers=headers(key='change-currency-v1'))
    stored=(await client.get(f'/v1/options/movement/selections/current?brand_id={BRAND}',headers=headers('buyer'))).json()['selection']
    assert stored==first
    assert (await client.post('/v1/options/movement/selections',json=selection(expected_revision=1,option_revision=3),headers=headers('buyer','future-option-v1'))).status_code==409
    updated=await client.post('/v1/options/movement/selections',json=selection(expected_revision=1,option_revision=2),headers=headers('buyer','current-option-v1'))
    assert updated.status_code==200
    assert updated.json()['quote_impact']=={'currency':'LBP','minor':25000000,'indicative':True}
    assert updated.json()['physical_feasibility_pass'] is False


@pytest.mark.asyncio
async def test_movement_requires_catalog_stock_grant_and_current_customization_onboarding(movement):
    client,app,identity=movement
    identity.permissions=['business.jobs.write']
    assert (await client.put(f'/v1/options/movement/{OPTION}',json=option(),headers=headers())).status_code==403
    identity.permissions=['business.stock.write']
    assert (await client.put(f'/v1/options/movement/{OPTION}',json=option(),headers=headers())).status_code==200
    identity.capabilities[str(BRAND)]=['sales','servicing']
    assert (await client.get(f'/v1/options/movement?brand_id={BRAND}')).status_code==409
    assert (await client.post('/v1/options/movement/selections',json=selection(),headers=headers('buyer'))).status_code==409
    identity.capabilities[str(BRAND)]=['customization']
    identity.authenticated=False
    assert (await client.get(f'/v1/options/movement/{OPTION}')).status_code==409


@pytest.mark.asyncio
async def test_movement_event_uses_the_authenticated_receiver_contract(movement,monkeypatch):
    from L11.service_operations_helpers import prove_signed_delivery
    _,app,_=movement
    await prove_signed_delivery(app,monkeypatch)
