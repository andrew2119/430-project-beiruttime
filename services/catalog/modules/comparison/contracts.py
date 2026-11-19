"""Load the owned schema without importing another service."""
import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[4] / 'packages/contracts-catalog/comparison/schema.py'
_spec = importlib.util.spec_from_file_location('comparison_v1', _path)
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)
CompareRequest = _contract.CompareRequest
Comparison = _contract.Comparison
Column = _contract.Column
Facts = _contract.Facts
Closed = _contract.Closed
Identifier = _contract.Identifier
Revision = _contract.Revision
