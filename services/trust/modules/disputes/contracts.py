"""Load the owned versioned contract without cross-service imports."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[4] / 'packages/contracts-trust/disputes/v1.py'
_spec = importlib.util.spec_from_file_location('disputes_v1', _path)
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)
Command, Result = _contract.Command, _contract.Result
