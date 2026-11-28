"""Load only the leased additions over the installed contract namespace."""
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def load(name, path, package=False):
    spec = importlib.util.spec_from_file_location(name, path,
        submodule_search_locations=[str(path.parent)] if package else None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


namespace = types.ModuleType('bt_contracts.service.cleaning')
namespace.__path__ = [str(ROOT / 'packages/contracts-service/cleaning')]
sys.modules[namespace.__name__] = namespace
load(namespace.__name__ + '.v1', ROOT / 'packages/contracts-service/cleaning/v1.py')
load('cleaning', ROOT / 'services/service-operations/modules/cleaning/__init__.py', True)
