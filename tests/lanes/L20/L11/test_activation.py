"""Inactive entry points preserve current discovery contracts."""
import json
from pathlib import Path

from bt_runtime.modules import discover

ROOT = Path(__file__).resolve().parents[4]


def test_pending_import_does_not_break_catalog_discovery():
    modules = discover(ROOT / 'services/catalog/modules')
    assert modules
    assert all(module.id != 'L20.dealer-import' for module in modules)
    pending = ROOT / 'services/catalog/modules/dealer-import/module.pending.json'
    assert json.loads(pending.read_text())['id'] == 'L20.dealer-import'
    assert not pending.with_name('module.json').exists()


def test_route_activation_waits_for_shared_registration():
    route = ROOT / 'web/app/(dealer-import)/seller/import'
    assert (route / 'route-entry.tsx').is_file()
    assert not (route / 'page.tsx').exists()
