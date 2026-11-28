"""Configuration-only unit seam; no simulated peer result authorizes a command."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
import pytest
from service_app import main


@pytest.mark.asyncio
@pytest.mark.parametrize('foundation_fails', [False, True])
async def test_hyphenated_service_uses_standard_environment_and_always_closes(monkeypatch, foundation_fails):
    created = []
    class Client:
        def __init__(self, name, url, **budgets):
            self.name, self.url, self.budgets, self.closed = name, url, budgets, False
            created.append(self)
        async def aclose(self):
            self.closed = True
    @asynccontextmanager
    async def lifespan(app):
        assert app.state.service_operations.url == 'http://configured-assessment:8000'
        assert app.state.identity.url == 'http://configured-identity:8000'
        assert all(client.budgets == {'timeout': 1.2, 'concurrency': 4} for client in created)
        if foundation_fails:
            raise RuntimeError('fixture startup failure')
        yield
    app = SimpleNamespace(router=SimpleNamespace(lifespan_context=lifespan), state=SimpleNamespace())
    monkeypatch.setenv('SERVICE_OPERATIONS_API_URL', 'http://configured-assessment:8000')
    monkeypatch.setenv('IDENTITY_API_URL', 'http://configured-identity:8000')
    monkeypatch.setattr(main, 'DependencyClient', Client)
    monkeypatch.setattr(main, 'foundation_app', lambda settings: app)
    result = main.create_app()
    if foundation_fails:
        with pytest.raises(RuntimeError, match='fixture startup failure'):
            async with result.router.lifespan_context(result):
                pass
    else:
        async with result.router.lifespan_context(result):
            assert len(created) == 6 and len({client.name for client in created}) == 6
    assert all(client.closed for client in created)
