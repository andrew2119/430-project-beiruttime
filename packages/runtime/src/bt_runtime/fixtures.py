"""Explicit, opt-in domain fixture entrypoints; never invoked at application boot."""
import asyncio
import inspect
import sys
from .modules import discover
from .app.settings import Settings


async def main(module_id: str, fixture: str):
    settings = Settings()
    module = next((m for m in discover(settings.modules_path) if m.id == module_id), None)
    if module is None or fixture not in module.fixtures:
        raise ValueError('Unknown fixture entrypoint')
    result = module.load(module.fixtures[fixture])(settings)
    if inspect.isawaitable(result):
        await result


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python -m bt_runtime.fixtures Lxx.module fixture-name')
    asyncio.run(main(*sys.argv[1:]))
