"""Include required contracts omitted from the shared publication inventory."""
import shutil
import sys
from pathlib import Path


def package(source, destination):
    for name in ('quality', 'brand-assessment', 'authorized-work', 'case-lines', 'job-assignments', 'test-keys'):
        target = destination / 'bt_contracts' / 'service' / name.replace('-', '_')
        target.mkdir(parents=True, exist_ok=True)
        for file in (source / name).iterdir():
            if file.suffix not in {'.py', '.json'}:
                continue
            shutil.copyfile(file, target / file.name)

if __name__ == '__main__':
    package(Path(sys.argv[1]), Path(sys.argv[2]))
