"""Resolve the candidate contract leaves for isolated module checks."""
from pathlib import Path
import sys

import bt_contracts.catalog.listings

ROOT = Path(__file__).resolve().parents[4]
bt_contracts.catalog.listings.__path__ = [str(ROOT / "packages/contracts-catalog/listings"), *bt_contracts.catalog.listings.__path__]
sys.path.insert(0, str(ROOT / "services/catalog"))
sys.path.insert(0, str(ROOT / "services/catalog/runtime"))
