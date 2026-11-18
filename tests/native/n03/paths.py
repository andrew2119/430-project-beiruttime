"""Load the same pure roots used by the lane proofs."""
from pathlib import Path
import runpy

_roots = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'lanes/L04/browser_fixture.py'))
repository_root = _roots['repository_root']
catalog_modules = _roots['catalog_modules']
discovery_modules = _roots['discovery_modules']
contract_fixtures = _roots['contract_fixtures']
