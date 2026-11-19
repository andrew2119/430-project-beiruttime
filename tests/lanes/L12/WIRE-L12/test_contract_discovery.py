import json
from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[4]


def contract_discovery(root):
    return runpy.run_path(str(ROOT / 'infra/foundation/discover-contracts.py'))['discover'](root)


def registration(root, filename_lane, **overrides):
    directory = root / 'contracts/registrations'
    directory.mkdir(parents=True, exist_ok=True)
    package = root / 'packages/contracts-fixture'
    package.mkdir(parents=True, exist_ok=True)
    (package / 'schema.json').write_text('{}')
    value = {
        'version': 1, 'lane': filename_lane,
        'contracts': [{'namespace': 'fixture.v1', 'path': 'packages/contracts-fixture/schema.json'}],
        **overrides,
    }
    (directory / f'{filename_lane}.json').write_text(json.dumps(value))


@pytest.mark.parametrize('lane', ['L00', 'L12', 'L25'])
def test_contract_lane_boundaries(tmp_path, lane):
    registration(tmp_path, lane)
    assert contract_discovery(tmp_path) == [{
        'namespace': 'fixture.v1', 'path': 'packages/contracts-fixture/schema.json', 'lane': lane,
    }]


def test_missing_contract_fragments(tmp_path):
    assert contract_discovery(tmp_path) == []
    (tmp_path / 'contracts/registrations').mkdir(parents=True)
    assert contract_discovery(tmp_path) == []


@pytest.mark.parametrize('lane,overrides', [
    ('L26', {}), ('L12', {'version': 2}), ('L12', {'lane': 'L25'}),
])
def test_invalid_contract_registration(tmp_path, lane, overrides):
    registration(tmp_path, lane, **overrides)
    with pytest.raises(ValueError, match='Invalid contract registration'):
        contract_discovery(tmp_path)


@pytest.mark.parametrize('lane', ['L00', 'L12', 'L25', 'L26'])
def test_template_runner_lane_boundaries(monkeypatch, lane):
    calls = []
    monkeypatch.setenv('BT_TEST_LANE', lane)
    monkeypatch.setenv('BT_SERVICE_NAME', 'fixture')
    monkeypatch.setattr(pytest, 'main', lambda arguments: calls.append(arguments) or 0)
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(ROOT / 'services/_template/runtime/run_tests.py'))
    if lane == 'L26':
        assert result.value.code == 'BT_TEST_LANE must be L00 through L25'
        assert calls == []
    else:
        assert result.value.code == 0
        assert len(calls) == 1
        assert '/lane-tests/L00' in calls[0]
        if lane != 'L00':
            assert f'/lane-tests/{lane}' in calls[0]
