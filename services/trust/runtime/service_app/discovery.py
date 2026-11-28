"""Service-local discovery and additive migration dependency ordering."""
import json
import re
from types import FunctionType

from bt_runtime.modules import discover as foundation_discover


def bind(function, **bindings):
    """Reuse the canonical implementation with service-local dependencies."""
    return FunctionType(function.__code__, {**function.__globals__, **bindings},
                        function.__name__, function.__defaults__, function.__closure__)


_discover = bind(
    foundation_discover,
    MODULE_ID=re.compile(r'^L(0[0-9]|1[0-9]|2[0-5])\.[a-z][a-z0-9.-]+$'),
    MIGRATION=re.compile(r'^L(0[0-9]|1[0-9]|2[0-5])_[0-9]{4}_[a-z0-9_]+\.sql$'),
)


def discover(root):
    modules = {module.id: module for module in _discover(root)}
    ordered, visiting, visited = [], set(), set()

    def visit(name):
        if name in visiting:
            raise ValueError('Cyclic module migration dependency')
        if name in visited:
            return
        if name not in modules:
            raise ValueError('Required module migration dependency is absent')
        visiting.add(name)
        module = modules[name]
        metadata = json.loads((module.root / 'module.json').read_text())
        dependencies = metadata.get('migration_dependencies', [])
        if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
            raise ValueError('Invalid module migration dependencies')
        for dependency in sorted(set(dependencies)):
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(module)

    for name in sorted(modules):
        visit(name)
    return ordered
