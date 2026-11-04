"""Discover lane contracts without a shared-index edit; reject path escapes."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def discover(root: Path = ROOT):
    found = []
    namespaces = set()
    for registration in sorted((root/'contracts/registrations').glob('L[0-1][0-9].json')):
        item = json.loads(registration.read_text())
        if item.get('version') != 1 or registration.stem != item.get('lane') or not re.fullmatch(r'L(0[0-9]|1[01])', item.get('lane', '')):
            raise ValueError('Invalid contract registration')
        for contract in item.get('contracts', []):
            namespace = contract['namespace']
            if not re.fullmatch(r'[a-z][a-z0-9.-]*\.v[1-9][0-9]*', namespace) or namespace in namespaces:
                raise ValueError('Duplicate contract namespace')
            namespaces.add(namespace)
            path = (root/contract['path']).resolve()
            if not path.is_relative_to((root/'packages').resolve()) or not path.exists():
                raise ValueError('Contract path must exist in packages')
            if not path.relative_to(root/'packages').parts[0].startswith('contracts-'):
                raise ValueError('Contracts must belong to a contracts-domain package')
            for fixture in contract.get('fixtures', []):
                target = (root/fixture).resolve()
                if not target.is_relative_to(root.resolve()) or not target.is_file():
                    raise ValueError('Fixture must be an existing repository file')
                json.loads(target.read_text())
            found.append({**contract, 'lane': item['lane']})
    return found

if __name__ == '__main__':
    print(json.dumps(discover(), indent=2))
