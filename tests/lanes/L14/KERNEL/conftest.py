"""Source-only contract imports for isolated transaction checks."""
import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'packages/contracts-core/src'))
for name, relative in [('bt_contracts', 'packages'), ('bt_contracts.auction', 'packages/contracts-auction')]:
    module = types.ModuleType(name)
    module.__path__ = [str(ROOT / relative)]
    sys.modules[name] = module


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
