"""Package discovered versioned contracts for the Orders image."""

import json
import re
import shutil
import sys
from pathlib import Path

LANE = re.compile(r'L(?:0[0-9]|1[0-9]|2[0-5])')
NAMESPACE = re.compile(r'[a-z][a-z0-9.-]*\.v[1-9][0-9]*')


def owned(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.exists():
        raise ValueError("Contract reference must exist within its root")
    return path


def discover(root):
    found, namespaces = [], set()
    for registration in sorted((root / "contracts/registrations").glob("L*.json")):
        item = json.loads(registration.read_text())
        lane = item.get("lane", "")
        if item.get("version") != 1 or registration.stem != lane or not LANE.fullmatch(lane):
            raise ValueError("Invalid contract registration")
        for contract in item.get("contracts", []):
            namespace = contract["namespace"]
            if not NAMESPACE.fullmatch(namespace) or namespace in namespaces:
                raise ValueError("Invalid or duplicate contract namespace")
            namespaces.add(namespace)
            source = owned(root, contract["path"])
            relative = source.relative_to(root / "packages")
            if not relative.parts[0].startswith("contracts-"):
                raise ValueError("Contract package required")
            for fixture in contract.get("fixtures", []):
                json.loads(owned(root, fixture).read_text())
            found.append(source)
    return found


def package(root, destination):
    for source in discover(root):
        domain, *subpath = source.relative_to(root / "packages").parts
        if source.is_file():
            subpath = subpath[:-1]
            files = [source]
            source_root = source.parent
        else:
            files = sorted(source.rglob("*"))
            source_root = source
        domain = domain.removeprefix("contracts-").replace("-", "_")
        for file in files:
            if not file.is_file() or {"node_modules", "__pycache__"}.intersection(file.parts):
                continue
            if not file.resolve().is_relative_to(source_root.resolve()):
                raise ValueError("Contract file escapes package")
            relative = file.relative_to(source_root)
            folders = [part.replace("-", "_") for part in [*subpath, *relative.parts[:-1]]]
            target = destination / "bt_contracts" / domain / Path(*folders) / file.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)


if __name__ == "__main__":
    package(Path(sys.argv[1]).resolve(), Path(sys.argv[2]))
