"""Declarative, service-local module discovery. Consumers never edit a central index."""
import hashlib
import importlib.metadata
import importlib.util
import json
import re
import sys
from threading import RLock
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

_LOAD_LOCK = RLock()

MODULE_ID = re.compile(r'^L(0[0-9]|1[0-9]|2[0-5])\.[a-z][a-z0-9.-]+$')
MIGRATION = re.compile(r'^L(0[0-9]|1[0-9]|2[0-5])_[0-9]{4}_[a-z0-9_]+\.sql$')


@dataclass(frozen=True)
class Module:
    id: str
    root: Path
    routes: tuple[str, ...]
    migrations: tuple[Path, ...]
    authorization: str | None
    fixtures: dict[str, str]
    hooks: dict[str, str]
    workers: tuple[str, ...]

    def load(self, reference: str) -> Any:
        with _LOAD_LOCK:
            file, separator, attribute = reference.partition(':')
            if not separator or not attribute.isidentifier() or not file.endswith('.py'):
                raise ValueError(f'Invalid entrypoint in {self.id}')
            path = owned_path(self.root, file)
            package_name = 'bt_module_' + hashlib.sha256(str(self.root).encode()).hexdigest()[:12] + '_' + self.id.replace('.', '_').replace('-', '_')
            if package_name not in sys.modules:
                package = ModuleType(package_name)
                package.__path__ = [str(self.root)]
                sys.modules[package_name] = package
            name = package_name + '.' + path.stem
            if name not in sys.modules:
                spec = importlib.util.spec_from_file_location(name, path)
                if spec is None or spec.loader is None:
                    raise ValueError(f'Cannot load {self.id}')
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
            return getattr(sys.modules[name], attribute)


def owned_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Module reference must name an existing owned file')
    return path


def discover(root: Path) -> list[Module]:
    modules = []
    prerequisites = {}
    seen: set[str] = set()
    if not root.exists():
        return []
    for registration in sorted(root.rglob('module.json')):
        if not registration.resolve().is_relative_to(root.resolve()):
            raise ValueError('Module registration must remain inside the service')
        data = json.loads(registration.read_text())
        if data.get('version') != 1 or not MODULE_ID.fullmatch(data.get('id', '')):
            raise ValueError(f'Invalid module registration: {registration}')
        if data['id'] in seen:
            raise ValueError(f'Duplicate module id: {data["id"]}')
        seen.add(data['id'])
        prerequisites[data['id']] = tuple(data.get('requires', []))
        module_root = registration.parent.resolve()
        migrations = []
        for relative in data.get('migrations', []):
            migration = owned_path(module_root, relative)
            if not MIGRATION.fullmatch(migration.name) or migration.name[:3] != data['id'][:3]:
                raise ValueError(f'Migrations must carry their lane and sequence: {migration.name}')
            migrations.append(migration)
        if [p.name for p in migrations] != sorted({p.name for p in migrations}):
            raise ValueError('Module migrations must be unique and monotonically ordered')
        for dependency in data.get('dependencies', []):
            # Local metadata declares existing dependencies; it cannot install packages at boot.
            importlib.metadata.version(dependency)
        modules.append(Module(data['id'], module_root, tuple(data.get('routes', [])), tuple(migrations),
                              data.get('authorization'), data.get('fixtures', {}), data.get('hooks', {}), tuple(data.get('workers', []))))
    ordered = []
    remaining = {module.id: module for module in modules}
    while remaining:
        ready = sorted(name for name in remaining if set(prerequisites[name]) <= {m.id for m in ordered})
        if not ready:
            raise ValueError('Missing or cyclic module prerequisite')
        for name in ready:
            ordered.append(remaining.pop(name))
    return ordered


def runtime_discover(root: Path) -> list[Module]:
    modules = discover(root)
    if any(module.id == 'L07.inbox' for module in modules):
        builtins = discover(Path(__file__).parent / 'modules')
        if {module.id for module in modules} & {module.id for module in builtins}:
            raise ValueError('Duplicate runtime module')
        # The inbox migration is a prerequisite of the additive payment notice table.
        modules.extend(builtins)
    return modules
