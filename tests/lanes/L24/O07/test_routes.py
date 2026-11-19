import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from o07_releases.routes import router_for
from o07_releases.service import Denied


@pytest.mark.asyncio
async def test_private_route_adapter(service, journal, command, context):
    app = FastAPI()
    async def current_context():
        return context
    app.include_router(router_for(service, current_context))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.post("/v1/releases", content=b"x"*8193)
        assert invalid.status_code == 413
        assert (await client.post("/v1/releases", json={"evidence": "private"})).status_code == 422
        wrong = command.model_copy(update={"actor_id": command.watch_id})
        assert (await client.post("/v1/releases", content=wrong.model_dump_json())).status_code == 403
        assert (await client.get("/v1/releases/"+str(command.subject_id))).status_code == 200
        result = await client.post("/v1/releases", content=command.model_dump_json())
        assert result.status_code == 200 and result.json()["state"] == "pending"
        path = "/v1/releases/operations/"+str(command.operation_id)
        assert (await client.get(path)).json()["state"] == "pending"
        assert (await client.post(path+"/recover")).json()["state"] == "paid_out"
        journal.allowed = False
        for response in (await client.get(path), await client.post(path+"/recover"),
                         await client.get("/v1/releases/"+str(command.subject_id))):
            assert response.status_code == 403
            assert "475000" not in response.text


@pytest.mark.asyncio
async def test_unavailable_reads_never_guess(service, journal, command, context):
    async def unavailable(*args):
        raise ConnectionError()
    journal.current = unavailable
    journal.lookup = unavailable
    journal.reconcile = unavailable
    app = FastAPI()
    async def current_context():
        return context
    app.include_router(router_for(service, current_context))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/v1/releases/"+str(command.subject_id))).status_code == 503
        path = "/v1/releases/operations/"+str(command.operation_id)
        assert (await client.get(path)).status_code == 503
        assert (await client.post(path+"/recover")).status_code == 503
    with pytest.raises(Denied):
        await service.submit(command.model_copy(update={"actor_id": command.watch_id}))
