"""Service-local compatibility for the published L00 through L25 inventory."""
import json
import re
import shutil
import sys
from pathlib import Path

LANE = r'L(0[0-9]|1[0-9]|2[0-5])'


def install_discovery():
    # The shared loader still owns path isolation, uniqueness and migration checks.
    # Set the same immutable grammar at startup and in the migration process.
    from bt_runtime import modules
    modules.MODULE_ID = re.compile(r'^' + LANE + r'\.[a-z][a-z0-9.-]+$')
    modules.MIGRATION = re.compile(r'^' + LANE + r'_[0-9]{4}_[a-z0-9_]+\.sql$')


def contract_inventory(root):
    registrations = root / 'contracts/registrations'
    namespaces = set()
    inventory = []
    for file in sorted(registrations.glob('L*.json')):
        data = json.loads(file.read_text())
        if data.get('version') != 1 or data.get('lane') != file.stem or not re.fullmatch(LANE, file.stem):
            raise ValueError('Invalid contract lane')
        for item in data.get('contracts', []):
            namespace = item['namespace']
            if not re.fullmatch(r'[a-z][a-z0-9.-]*\.v[1-9][0-9]*', namespace) or namespace in namespaces:
                raise ValueError('Invalid or duplicate contract namespace')
            namespaces.add(namespace)
            source = (root / item['path']).resolve()
            packages = (root / 'packages').resolve()
            if not source.is_relative_to(packages) or not source.exists():
                raise ValueError('Contract source must be an existing package path')
            if not source.relative_to(packages).parts[0].startswith('contracts-'):
                raise ValueError('Contract source must belong to a domain contract package')
            for fixture in item.get('fixtures', []):
                target = (root / fixture).resolve()
                if not target.is_relative_to(root.resolve()) or not target.is_file():
                    raise ValueError('Fixture must be an existing repository file')
                json.loads(target.read_text())
            inventory.append(source)
    return inventory


def package_contracts(root, output):
    # Validate the complete inventory before producing any output.
    inventory = contract_inventory(root)
    targets = {}
    for source in inventory:
        if not source.is_dir():
            continue
        package, *subpath = source.relative_to((root / 'packages').resolve()).parts
        domain = package.removeprefix('contracts-').replace('-', '_')
        for file in sorted(source.rglob('*')):
            if not file.is_file() or {'node_modules', '__pycache__'} & set(file.parts):
                continue
            if not file.resolve().is_relative_to(source):
                raise ValueError('Contract file escapes its package')
            directories = subpath + list(file.relative_to(source).parts[:-1])
            target = output / 'bt_contracts' / domain / Path(*(part.replace('-', '_') for part in directories)) / file.name
            if target in targets and targets[target].read_bytes() != file.read_bytes():
                raise ValueError('Conflicting normalized contract path')
            targets[target] = file
    for target, file in targets.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)


if __name__ == '__main__':
    package_contracts(Path(sys.argv[1]).resolve(), Path(sys.argv[2]))
