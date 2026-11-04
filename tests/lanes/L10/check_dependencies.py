"""Refuse a cached proof image whose installed third-party pins no longer match."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from packaging.requirements import Requirement

for file in ("requirements.txt", "requirements-dev.txt"):
    for line in (Path('/proof/template') / file).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        requirement = Requirement(line)
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            installed = ''
        if not installed or installed not in requirement.specifier:
            raise SystemExit('Cached proof dependencies differ; rebuild only the lane proof image explicitly.')
print('Cached third-party dependency pins match current runtime requirements.')
