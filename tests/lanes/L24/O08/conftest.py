"""Load the candidate contract leaf ahead of the installed snapshot."""
import sys
from pathlib import Path
import bt_contracts.orders

ROOT = Path(__file__).resolve().parents[4]
bt_contracts.orders.__path__ = [str(ROOT / 'packages/contracts-orders'), *bt_contracts.orders.__path__]
sys.path.insert(0, str(ROOT / 'services/orders/modules'))
