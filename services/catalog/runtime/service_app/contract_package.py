"""Package validated contract fragments for the Catalog image."""

import json
from pathlib import Path
import re
import shutil
import sys

LANE = re.compile(r'L(?:0[0-9]|1[0-9]|2[0-5])')
NAMESPACE = re.compile(r'[a-z][a-z0-9.-]*\.v[1-9][0-9]*')


def registrations(root):
    namespaces = set()
    found = []
    for path in sorted((root / 'contracts/registrations').glob('L*.json')):
        data = json.loads(path.read_text())
        if data.get('version') != 1 or not LANE.fullmatch(data.get('lane', '')) or path.stem != data['lane']:
            raise ValueError('Invalid contract registration')
        for contract in data.get('contracts', []):
            namespace = contract['namespace']
            if not NAMESPACE.fullmatch(namespace) or namespace in namespaces:
                raise ValueError('Invalid or duplicate contract namespace')
            namespaces.add(namespace)
            source = (root / contract['path']).resolve()
            packages = (root / 'packages').resolve()
            if not source.is_relative_to(packages) or not source.exists():
                raise ValueError('Contract path must exist in packages')
            if not source.relative_to(packages).parts[0].startswith('contracts-'):
                raise ValueError('Contract path must belong to a domain')
            for fixture in contract.get('fixtures', []):
                target = (root / fixture).resolve()
                if not target.is_relative_to(root.resolve()) or not target.is_file():
                    raise ValueError('Fixture path must exist inside the repository')
                json.loads(target.read_text())
            found.append(source)
    return found


def package(root, output):
    # Validate every fragment before writing any package files.
    sources = registrations(root)
    for source in sources:
        if not source.is_dir():
            continue
        domain, *subpath = source.relative_to((root / 'packages').resolve()).parts
        domain = domain.removeprefix('contracts-').replace('-', '_')
        for file in sorted(source.rglob('*')):
            if not file.is_file() or {'node_modules', '__pycache__'} & set(file.parts):
                continue
            if not file.resolve().is_relative_to(source):
                raise ValueError('Contract source must remain inside its package')
            relative = [part.replace('-', '_') for part in subpath + list(file.relative_to(source).parts[:-1])]
            target = output / 'bt_contracts' / domain / Path(*relative) / file.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != file.read_bytes():
                raise ValueError('Conflicting contract sources')
            shutil.copyfile(file, target)


if __name__ == '__main__':
    package(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
