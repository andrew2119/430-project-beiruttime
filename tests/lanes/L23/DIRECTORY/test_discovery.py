"""Movement schema additions retain their own lane and prerequisite."""
import json
from pathlib import Path

from bt_runtime.modules import discover

ROOT = Path(__file__).resolve().parents[4]


def test_movement_migration_registration():
    root = ROOT / 'services/catalog/modules/options/movement'
    original = json.loads((root / 'module.json').read_text())
    addition = json.loads((root / 'compatibility/module.json').read_text())
    assert original['id'] == 'L11.movement'
    assert original['migrations'] == ['migrations/L11_0001_movement.sql']
    assert addition['id'] == 'L23.movement-compatibility'
    assert addition['migration_dependencies'] == ['L11.movement']
    assert addition['migrations'] == [
        'migrations/L23_0001_compatibility.sql',
        'migrations/L23_0002_selection_archive.sql',
    ]
    for migration in addition['migrations']:
        assert (root / 'compatibility' / migration).is_file()


def test_catalog_module_discovery():
    modules = {module.id: module for module in discover(ROOT / 'services/catalog/modules')}
    assert [path.name for path in modules['L11.movement'].migrations] == ['L11_0001_movement.sql']
    assert [path.name for path in modules['L23.movement-compatibility'].migrations] == [
        'L23_0001_compatibility.sql',
        'L23_0002_selection_archive.sql',
    ]
