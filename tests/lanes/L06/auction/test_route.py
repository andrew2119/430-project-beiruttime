from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from bt_runtime.app.auth import require_principal
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings

ROOT = next((p for p in Path(__file__).resolve().parents if (p / 'services').is_dir()), Path('/app'))
# These proofs isolate the owned route; the complete Auction runtime has its own suite.
MODULES = ROOT / 'services/auction/modules/proxy'
if not MODULES.exists():
    MODULES = Path('/app/modules/proxy')
AUCTION = '00000000-0000-0000-0000-000000000006'
QUOTE = '00000000-0000-0000-0000-000000000007'


def app():
    application = create_app(Settings(service_name='auction', database_url='postgresql://unused/unused', modules_path=MODULES))
    application.dependency_overrides[require_principal] = lambda: SimpleNamespace(subject='buyer')
    return application


@pytest.mark.asyncio
async def test_maximum_route_delegates_exactly_once_to_authoritative_transaction():
    application, calls = app(), []
    async def submit(request, auction_id, command, *, kind):
        calls.append((request, auction_id, command, kind))
        return {'status': 'succeeded', 'current_minor': 10000, 'revision': 2}
    application.state.auction = SimpleNamespace(submit=submit)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://auction') as client:
        response = await client.post('/v1/auctions/' + AUCTION + '/maximum', headers={'Idempotency-Key': 'logical-command-6'},
                                     json={'amount_minor': 20000, 'fee_quote_id': QUOTE, 'expected_revision': 1})
    assert response.status_code == 200
    assert len(calls) == 1 and calls[0][3] == 'maximum'
    assert calls[0][0].headers['idempotency-key'] == 'logical-command-6'
    assert str(calls[0][1]) == AUCTION
    assert calls[0][2].amount_minor == 20000 and str(calls[0][2].fee_quote_id) == QUOTE
    assert '20000' not in response.text and 'amount_minor' not in response.text


@pytest.mark.asyncio
async def test_missing_runtime_never_acknowledges_a_maximum():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url='http://auction') as client:
        response = await client.post('/v1/auctions/' + AUCTION + '/maximum',
                                     json={'amount_minor': 20000, 'fee_quote_id': QUOTE, 'expected_revision': 1})
    assert response.status_code == 503 and response.json()['error']['code'] == 'unavailable'


@pytest.mark.asyncio
async def test_invalid_private_input_is_redacted_before_runtime():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url='http://auction') as client:
        response = await client.post('/v1/auctions/' + AUCTION + '/maximum',
                                     json={'amount_minor': 1234567.89, 'fee_quote_id': QUOTE, 'expected_revision': 1})
    assert response.status_code == 422 and '1234567' not in response.text
    assert response.headers['cache-control'] == 'no-store'
