"""A module may declare only distributions its own service image installs.

Discovery reads every declared dependency's installed metadata at start and in the pre-deploy
migration, so a name missing from this service's requirements stops the deploy even when a shared
test environment holds it for another service.
"""
from importlib.metadata import distribution
import json

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from bt_runtime.app.settings import Settings


def requirements_file(modules):
    # The repository keeps it in runtime/; the image test stage copies runtime/ to /app.
    for candidate in (modules.parent / 'runtime/requirements.txt', modules.parent / 'requirements.txt'):
        if candidate.is_file():
            return candidate
    raise AssertionError(f'No requirements.txt beside {modules}')


def installed_by(lines):
    """Canonical names the requirements install, following their dependencies and requested extras."""
    names, seen = set(), set()
    pending = [Requirement(line) for line in lines]
    while pending:
        requirement = pending.pop()
        name = canonicalize_name(requirement.name)
        extras = {''} | set(requirement.extras)
        if {(name, extra) for extra in extras} <= seen:
            continue
        seen |= {(name, extra) for extra in extras}
        names.add(name)
        for text in distribution(requirement.name).requires or []:
            child = Requirement(text)
            if child.marker is None or any(child.marker.evaluate({'extra': extra}) for extra in extras):
                pending.append(child)
    return names


def test_declared_dependencies_come_from_this_service_requirements():
    modules = Settings(database_url='postgresql://unused/unused').modules_path
    declared = {}
    for registration in sorted(modules.rglob('module.json')):
        for dependency in json.loads(registration.read_text()).get('dependencies', []):
            declared.setdefault(canonicalize_name(dependency), []).append(str(registration.relative_to(modules)))
    if not declared:
        return
    lines = [line.split('#', 1)[0].strip() for line in requirements_file(modules).read_text().splitlines()]
    installed = installed_by([line for line in lines if line])
    missing = {name: where for name, where in declared.items() if name not in installed}
    assert not missing, f'Declared but not installed by this service: {missing}'
