import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[4]
for name, path in (
    ('bt_contracts.eligibility.private_review', ROOT/'packages/contracts-eligibility/private-review'),
    ('l20_private_review', ROOT/'services/eligibility/modules/private-review'),
):
    package = ModuleType(name)
    package.__path__ = [str(path)]
    sys.modules[name] = package
