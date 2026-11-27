"""Every module starts from the runtime image layout, where no repository checkout sits above /app.

The image copies only service_app and modules into /app and keeps the registered contracts packaged
under bt_contracts. Loading the modules in place passes even when a module reads its contract through
a path that climbs to the checkout, so this copy places them where nothing above holds packages/.
"""
import json
import shutil

from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings


def test_modules_start_outside_the_repository(tmp_path):
    source = Settings(database_url='postgresql://unused/unused').modules_path
    modules = tmp_path / 'app/modules'
    shutil.copytree(source, modules, ignore=shutil.ignore_patterns('__pycache__'))
    assert not any((parent / 'packages').is_dir() for parent in modules.parents)
    app = create_app(Settings(database_url='postgresql://unused/unused', modules_path=modules))
    expected = sorted(json.loads(path.read_text())['id'] for path in source.rglob('module.json'))
    assert sorted(module.id for module in app.state.modules) == expected
