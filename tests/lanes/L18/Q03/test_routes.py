import asyncio
from types import SimpleNamespace
from uuid import UUID
import httpx
from fastapi import FastAPI
from counteroffer_module.routes import router_for
from bt_contracts.pricing.counteroffers.current import Command, Offer, Result
from pathlib import Path
import json

FIXTURES = Path(__file__).resolve().parents[4] / 'packages/contracts-pricing/counteroffers/fixtures'

def test_fixtures_match_schema():
    for path in sorted(FIXTURES.glob('*.json')):
        fixture=json.loads(path.read_text())
        assert fixture['synthetic'] is True
        Command.model_validate(fixture['command'])
        Offer.model_validate(fixture['current'])
        Result.model_validate(fixture['operation'])
        if fixture['operation']['state']=='pending':
            from datetime import datetime, timedelta
            deadline=datetime.fromisoformat(fixture['operation']['next_review_at'].replace('Z','+00:00'))
            assert deadline==datetime.fromisoformat(fixture['now'].replace('Z','+00:00'))+timedelta(hours=24)

def test_private_routes_bind_principal_and_lookup():
    fixture=json.loads((FIXTURES/'success.v1.json').read_text())
    command=fixture['command']
    calls=[]
    class Service:
        async def command(self,body):
            calls.append(body)
            return fixture['operation']
        async def operation(self,principal,subject,operation):
            assert principal.actor_id==UUID(command['actor_id'])
            raise PermissionError
        async def current(self,principal,subject):
            raise TimeoutError
    async def principal():
        return SimpleNamespace(actor_id=UUID(command['actor_id']),organization_id=UUID(command['organization_id']))
    app=FastAPI()
    app.include_router(router_for(Service(),principal))
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            path='/v1/counteroffers/'+command['subject_id']
            assert (await client.post(path+'/commands',json=command)).status_code==200
            assert len(calls)==1
            for field in ['actor_id','organization_id','subject_id']:
                response=await client.post(path+'/commands',json={**command,field:str(UUID(int=99))})
                assert response.status_code==403
            assert len(calls)==1
            assert (await client.get(path+'/operations/'+command['operation_id'])).status_code==403
            assert (await client.get(path)).status_code==503
            assert (await client.post(path+'/commands',json={**command,'extra':'private'})).status_code==422
    asyncio.run(exercise())

def test_deterministic_decision_fixtures():
    from datetime import datetime
    from bt_contracts.pricing.counteroffers.current import Authority, Facts
    from counteroffer_module.engine import decide
    for name in ['success','denied','stale']:
        fixture=json.loads((FIXTURES/(name+'.v1.json')).read_text())
        result,_=decide(Command.model_validate(fixture['command']),Offer.model_validate(fixture['current']),
            Authority.model_validate(fixture['authority']),Facts.model_validate(fixture['facts']),
            datetime.fromisoformat(fixture['now'].replace('Z','+00:00')))
        assert result==Result.model_validate(fixture['operation'])
