"""Command composition for an installed owning recovery runtime."""
from contextlib import asynccontextmanager
from importlib import import_module
import inspect

from recovery_cases import RecoveryError

METHODS = ('measure', 'backup', 'command', 'restore', 'restore_rejected', 'discard',
           'effects', 'lose_response', 'dispatch', 'interrupt', 'restart', 'lookup', 'retry')


@asynccontextmanager
async def open_runtime(reference, run, operations):
    """The explicitly selected factory owns authenticated clients and processes.

    A factory returns an asynchronous context manager, never a proof summary.
    Only this command option selects executable composition; input records cannot.
    """
    module, separator, factory_name = reference.partition(':')
    if (not separator or not factory_name.isidentifier()
            or not all(part.isidentifier() for part in module.split('.'))):
        raise RecoveryError('recovery_runtime_reference')
    factory = getattr(import_module(module), factory_name)
    # Preserve the original references even if a composition mutates its input.
    bound_operations = {name: list(values) for name, values in operations.items()}
    async with factory(run=run, operations=bound_operations) as provider:
        if any(not inspect.iscoroutinefunction(getattr(provider, name, None))
               for name in METHODS):
            raise RecoveryError('recovery_runtime_methods')
        yield provider
