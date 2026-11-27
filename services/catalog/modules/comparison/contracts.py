"""Use the packaged comparison contract; source-only checks load the owned file from a checkout."""
try:
    import bt_contracts.catalog.comparison.schema as _contract
except ModuleNotFoundError as error:
    if error.name not in ('bt_contracts', 'bt_contracts.catalog', 'bt_contracts.catalog.comparison',
                          'bt_contracts.catalog.comparison.schema'):
        raise
    import importlib.util
    from pathlib import Path

    _owned = 'packages/contracts-catalog/comparison/schema.py'
    _path = next((parent / _owned for parent in Path(__file__).resolve().parents if (parent / _owned).is_file()), None)
    if _path is None:
        raise RuntimeError('Comparison contract unavailable') from error
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
