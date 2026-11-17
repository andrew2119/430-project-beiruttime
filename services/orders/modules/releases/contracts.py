"""Use packaged domain contracts; allow the same source during local module tests."""
try:
    from bt_contracts.orders.releases.v1 import Command, Context, Snapshot, Operation, Preview
except ModuleNotFoundError as error:
    if error.name not in {
        "bt_contracts", "bt_contracts.orders", "bt_contracts.orders.releases", "bt_contracts.orders.releases.v1",
    }:
        raise
    import importlib.util
    from pathlib import Path
    import sys

    candidates = [
        parent / "packages/contracts-orders/releases/v1.py"
        for parent in list(Path(__file__).resolve().parents)[:6]
    ]
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise ModuleNotFoundError("orders_release_contract_unavailable") from error
    spec = importlib.util.spec_from_file_location("orders_release_v1", source)
    contract = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = contract
    spec.loader.exec_module(contract)
    Command = contract.Command
    Context = contract.Context
    Snapshot = contract.Snapshot
    Operation = contract.Operation
    Preview = contract.Preview
