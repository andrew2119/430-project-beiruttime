import json
from pathlib import Path

from bt_runtime.modules import discover

ROOT = Path(__file__).resolve().parents[4]


def test_additive_schema_has_registered_lane_migrations_and_dependencies():
    modules = discover(ROOT / 'services/identity/modules')
    schema = next(module for module in modules if module.id == 'L19.account-access')
    registration = json.loads((schema.root / 'module.json').read_text())
    assert registration['migration_dependencies'] == ['L01.accounts', 'L01.private-seller']
    assert all(dependency in {module.id for module in modules}
               for dependency in registration['migration_dependencies'])
    assert [path.name for path in schema.migrations] == [
        'L19_0001_recovery_receipts.sql',
        'L19_0002_password_receipts.sql',
        'L19_0003_listing_possession.sql',
    ]
    assert not schema.routes and not schema.workers
    sql = '\n'.join(path.read_text() for path in schema.migrations)
    for table in ('recovery_receipts', 'password_receipts', 'possession',
                  'possession_receipts', 'possession_photos'):
        assert f'CREATE TABLE identity_l19_{table} (' in sql
    for module in modules:
        assert all(path.name.startswith(module.id[:3] + '_') for path in module.migrations)
    parents = ROOT / 'services/identity/modules'
    for name in ('accounts', 'private-seller'):
        assert not list((parents / name / 'migrations').glob('L19_*.sql'))
