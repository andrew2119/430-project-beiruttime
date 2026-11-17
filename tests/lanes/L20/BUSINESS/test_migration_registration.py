"""Additive schema ownership remains valid when later lanes are admitted."""
import json
import re
from pathlib import Path

from bt_runtime import modules

ROOT = Path(__file__).resolve().parents[4]


def test_additive_migrations_use_their_own_lane(monkeypatch):
    # Shared lane admission is supplied separately; retain its ownership checks.
    monkeypatch.setattr(modules, 'MODULE_ID', re.compile(r'^L(0[1-9]|1[0-9]|2[0-5])\.[a-z][a-z0-9.-]+$'))
    monkeypatch.setattr(modules, 'MIGRATION', re.compile(r'^L(0[1-9]|1[0-9]|2[0-5])_[0-9]{4}_[a-z0-9_]+\.sql$'))
    for parent, leaf in [('businesses', 'scope-confirmation'), ('membership', 'command-receipts')]:
        root = ROOT / 'services/identity/modules' / parent
        found = {module.id: module for module in modules.discover(root)}
        original = json.loads((root / 'module.json').read_text())
        additive = json.loads((root / leaf / 'module.json').read_text())
        assert additive['migration_dependencies'] == [original['id']]
        assert set(found) == {original['id'], additive['id']}
        assert all(path.name.startswith('L02_') for path in found[original['id']].migrations)
        assert len(found[additive['id']].migrations) == 1
        assert found[additive['id']].migrations[0].name.startswith('L20_')
        assert list(found) == [original['id'], additive['id']]
