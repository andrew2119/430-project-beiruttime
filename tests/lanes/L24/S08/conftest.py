import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def package(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


package('bt_contracts.service.reduction', ROOT / 'packages/contracts-service/reduction')
package('reduction_local', ROOT / 'services/service-operations/modules/reduction')
