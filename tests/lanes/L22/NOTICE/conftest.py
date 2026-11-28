"""Load only the current owned contract leaves and service modules."""
from pathlib import Path
import sys
import bt_contracts.comms.inbox
import bt_contracts.comms.bid_notices

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'services/communications/runtime'))
bt_contracts.comms.inbox.__path__ = [str(ROOT / 'packages/contracts-comms/inbox'), *bt_contracts.comms.inbox.__path__]
bt_contracts.comms.bid_notices.__path__ = [str(ROOT / 'packages/contracts-comms/bid-notices'), *bt_contracts.comms.bid_notices.__path__]
