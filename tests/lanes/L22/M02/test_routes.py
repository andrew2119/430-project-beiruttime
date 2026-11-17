"""Pure route-adapter checks; current identity is supplied at the dependency boundary."""
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError

from test_saved_watches import Provider, command

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'services/communications/runtime'))
PACKAGE = 'saved_route_checks'
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / 'services/communications/modules/saved-watches')]
sys.modules[PACKAGE] = package
spec = importlib.util.spec_from_file_location(PACKAGE + '.routes', Path(package.__path__[0]) / 'routes.py')
routes = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = routes
spec.loader.exec_module(routes)
from saved_route_checks.store import Store  # noqa: E402


def test_current_owner_route_and_operation_lookup(tmp_path):
    provider = Provider()
    store = Store(tmp_path / 'route.db', provider)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(saved_watches=store)))
    for route in (routes.listing, routes.lookup, routes.save, routes.record):
        assert inspect.signature(route).parameters['owner'].default.dependency is routes.actor
    result = routes.save(routes.Command(**command()), request, 'watch-1', 'buyer-1')
    assert routes.lookup(request, 'save-1', 'buyer-1') == result
    with pytest.raises(routes.PublicError) as missing:
        routes.lookup(request, 'save-1', 'buyer-2')
    assert missing.value.status == 404
    assert routes.listing(request, 'buyer-2', 0, 20)['total'] == 0
    assert routes.record(request, 'watch-1', 'buyer-2')['revision'] == 0
    with pytest.raises(routes.PublicError) as stale:
        routes.save(routes.Command(**command(operation='save-2')), request, 'watch-1', 'buyer-1')
    assert stale.value.status == 409
    with pytest.raises(ValidationError):
        routes.Command(**{**command(), 'owner': 'buyer-2'})
    provider.allowed = False
    with pytest.raises(routes.PublicError) as denied:
        routes.listing(request, 'buyer-1', 0, 20)
    assert denied.value.status == 403
    del request.app.state.saved_watches
    with pytest.raises(routes.PublicError) as unavailable:
        routes.listing(request, 'buyer-1', 0, 20)
    assert unavailable.value.status == 503
    store.close()


def test_scheduled_worker_pages_canonical_watches(tmp_path):
    import importlib
    worker = importlib.import_module(PACKAGE + '.workers')
    provider = Provider()
    store = Store(tmp_path / 'worker.db', provider)
    store.save('buyer-1', 'buyer-1', 'watch-1', command())
    store.save('buyer-1', 'buyer-1', 'watch-2', command(operation='save-2'))
    first = worker.tick(store, '2026-11-17T11:30:00Z', limit=1)
    assert first['next'] == 'watch-1' and first['pending'] == 0
    second = worker.tick(store, '2026-11-17T11:30:01Z', after=first['next'], limit=1)
    assert second['next'] == 'watch-2' and len(provider.notices) == 2
    assert worker.tick(store, '2026-11-17T11:30:02Z', after=second['next'], limit=1)['next'] == ''
    store.close()
