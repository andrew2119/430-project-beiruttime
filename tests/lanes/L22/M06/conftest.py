"""Use only the owned source and installed shared dependencies."""
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[4]
# The runtime image normally mounts contract leaves under their import names.
contracts = ModuleType('bt_contracts.comms.saved_searches')
contracts.__path__ = [str(ROOT / 'packages/contracts-comms/saved-searches')]
sys.modules[contracts.__name__] = contracts
module = ModuleType('saved_search_module')
module.__path__ = [str(ROOT / 'services/communications/modules/saved-searches')]
sys.modules[module.__name__] = module
sys.path.insert(0, str(ROOT / 'services/communications/runtime'))
