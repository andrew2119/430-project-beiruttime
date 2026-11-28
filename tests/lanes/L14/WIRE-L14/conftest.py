"""Isolated source composition without a database or external services."""
import importlib
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[4]
for package in ('contracts-core', 'bulkheads', 'events', 'runtime'):
    sys.path.insert(0, str(ROOT / 'packages' / package / 'src'))


@pytest.fixture(params=['auction', 'pricing'])
def runtime(request, monkeypatch, tmp_path):
    for name in list(sys.modules):
        if name == 'service_app' or name.startswith(('service_app.', 'bt_module_')):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.syspath_prepend(str(ROOT / 'services' / request.param / 'runtime'))
    discovery = importlib.import_module('service_app.discovery')
    discovery.package_contracts(ROOT, tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    discovery.install_discovery()
    return request.param, discovery
