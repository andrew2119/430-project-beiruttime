"""Host integration with merged Identity authority; no operator bootstrap or fake principal."""
import httpx
import pytest
from L11.conftest import ROOT, BRAND, module_stack
from L11.real_accounts import accounts_routes
from L11.testing_database import disposable_database
from L11.service_operations_helpers import headers
from L11.service_operations_tests_data import profile, option


@pytest.mark.skipif(not (ROOT / 'services/identity/modules/businesses/module.json').is_file(),
    reason='Host integration needs merged Identity source; domain image tests only its own service')
@pytest.mark.asyncio
async def test_real_identity_denies_unonboarded_businesses_and_revoked_sessions():
    async with disposable_database() as identity_db, disposable_database() as directory_db, disposable_database() as catalog_db:
        async with accounts_routes(identity_db, full_authority=True) as identity_app:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=identity_app),
                    base_url='http://identity.proof', headers={'Origin':'http://127.0.0.1:3111'}) as identity:
                registered=await identity.post('/v1/accounts/register',headers={'Idempotency-Key':'real-care-authority-v1'},
                    json={'email':'care-authority@example.test','password':'Synthetic-care-password-2026','display_name':'Sample care buyer'})
                assert registered.status_code==201
                session=registered.json()
                assert session['principal']['roles']==['buyer']
                assert (await identity.get('/v1/businesses')).json()=={'items':[]}
                buyer={'Authorization':'Bearer '+session['access_token'],'Idempotency-Key':'real-unonboarded-care-v1'}
                async with module_stack('directory',directory_db.runtime_url,directory_db.owner_url,identity_app,real_businesses=True) as directory:
                    async with module_stack('movement',catalog_db.runtime_url,catalog_db.owner_url,identity_app,real_businesses=True) as movement:
                        dc,directory_app,directory_transport=directory
                        mc,movement_app,movement_transport=movement
                        assert (await dc.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=buyer)).status_code==403
                        assert (await dc.put(f'/v1/directory/businesses/{BRAND}',json=profile(),headers=headers())).status_code==401
                        assert (await mc.put('/v1/options/movement/00000000-0011-4000-8000-000000000003',json=option(),headers=buyer)).status_code==403
                        assert (await mc.get(f'/v1/options/movement?brand_id={BRAND}')).status_code==409
                        chosen=await dc.post('/v1/directory/choices',headers=buyer,json={
                            'organization_id':str(BRAND),'purpose':'servicing','capability':'maintenance',
                            'expected_revision':0,'profile_revision':1})
                        assert chosen.status_code==409 and chosen.json()['error']['code']=='not_official'
                        assert (await dc.get('/v1/directory/choices/current',headers=buyer)).json()=={'choice':None}
                        assert (await mc.get(f'/v1/options/movement/selections/current?brand_id={BRAND}',headers=buyer)).json()=={'selection':None}
                        assert (await identity.post('/v1/accounts/logout')).status_code==200
                        assert (await dc.get('/v1/directory/choices/current',headers=buyer)).status_code==401
                        assert (await mc.get(f'/v1/options/movement/selections/current?brand_id={BRAND}',headers=buyer)).status_code==401
                        # No fixture authority response was consulted, and no denied effect was retained.
                        assert directory_transport.requests==movement_transport.requests==[]
                        for app,table in ((directory_app,'directory_profiles'),(movement_app,'movement_options')):
                            async with app.state.pool.acquire() as tx:
                                assert await tx.fetchval(f'SELECT count(*) FROM {table}')==0
                                assert await tx.fetchval('SELECT count(*) FROM outbox')==0
