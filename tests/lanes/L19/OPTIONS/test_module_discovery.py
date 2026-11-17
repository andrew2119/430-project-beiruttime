from pathlib import Path

from bt_runtime.modules import discover


ROOT = Path(__file__).resolve().parents[4]


def test_catalog_discovery_preserves_movement_migration_ownership():
    modules = discover(ROOT / 'services/catalog/modules')
    movement = next(module for module in modules if module.id == 'L11.movement')
    assert [path.name for path in movement.migrations] == ['L11_0001_movement.sql']
    for module in modules:
        assert all(path.name.split('_', 1)[0] == module.id.split('.', 1)[0]
                   for path in module.migrations)
