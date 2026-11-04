"""Package registered Python contract source under bt_contracts.<domain>.<module>."""
import importlib.util
import shutil
import sys
from pathlib import Path

helper = Path(__file__).with_name('discover-contracts.py')
spec = importlib.util.spec_from_file_location('contract_discovery', helper)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
root = module.ROOT
out = Path(sys.argv[1])/'bt_contracts'
out.mkdir(parents=True, exist_ok=True)
for registration in module.discover():
    source = root/registration['path']
    if not source.is_dir():
        continue
    package, *subpath = source.relative_to(root/'packages').parts
    domain = package.removeprefix('contracts-').replace('-','_')
    for file in source.rglob('*'):
        if not file.is_file() or 'node_modules' in file.parts or '__pycache__' in file.parts:
            continue
        relative = [part.replace('-','_') for part in subpath + list(file.relative_to(source).parts[:-1])]
        target = out/domain/Path(*relative)/file.name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(file,target)
