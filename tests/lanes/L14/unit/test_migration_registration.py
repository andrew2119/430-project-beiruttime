import json
from conftest import ROOT
import pytest


@pytest.mark.parametrize('module', ['services/auction/modules/rules/kernel-v2',
    'services/pricing/modules/quotes/current-state', 'services/pricing/modules/offers'])
def test_every_additive_migration_is_registered_once(module):
    directory = ROOT / module
    metadata = json.loads((directory / 'module.json').read_text())
    registered = metadata['migrations']
    assert len(set(registered)) == len(registered)
    assert {str(file.relative_to(directory)) for file in (directory/'migrations').glob('*.sql')} == set(registered)
    assert registered == sorted(registered)
