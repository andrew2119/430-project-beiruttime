import sys
from pathlib import Path

import bt_contracts.service

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'packages'))
sys.path.insert(0, str(ROOT / 'services/service-operations/modules'))

bt_contracts.service.__path__ = [str(ROOT / 'packages/contracts-service'), *bt_contracts.service.__path__]
