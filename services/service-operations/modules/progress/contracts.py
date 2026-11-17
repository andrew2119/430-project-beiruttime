"""Use the packaged contract namespace; source-only checks use the owned leaf."""
try:
    from bt_contracts.service.progress.v1 import Access, Source, Command, Binding
except ModuleNotFoundError as error:
    if error.name not in ('bt_contracts', 'bt_contracts.service', 'bt_contracts.service.progress',
                          'bt_contracts.service.progress.v1'):
        raise
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    root = next((parent for parent in Path(__file__).resolve().parents
                 if (parent / 'packages/contracts-service/progress/v1.py').is_file()), None)
    if root is None:
        raise RuntimeError('Progress contract unavailable') from error
    spec = spec_from_file_location('progress_v1', root / 'packages/contracts-service/progress/v1.py')
    contract = module_from_spec(spec)
    spec.loader.exec_module(contract)
    Access, Source, Command, Binding = contract.Access, contract.Source, contract.Command, contract.Binding

__all__ = ['Access', 'Source', 'Command', 'Binding']
