import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from bt_runtime.modules import discover
from bt_runtime.app.db import migration_steps


def register(root, name, dependencies=()):
    directory = root / name
    directory.mkdir()
    lane = name.split('.')[0]
    migration = f'{lane}_0001_fixture.sql'
    (directory / migration).write_text('SELECT 1;')
    (directory / 'module.json').write_text(json.dumps({
        'version': 1, 'id': name, 'migrations': [migration],
        'migration_dependencies': list(dependencies),
    }))


def test_absent_fragments(tmp_path):
    assert discover(tmp_path / 'absent') == []


def test_full_module_dependency_plan_and_concurrent_reads(tmp_path):
    register(tmp_path, 'L00.foundation')
    register(tmp_path, 'L01.consumer', ['L25.provider'])
    register(tmp_path, 'L25.provider', ['L00.foundation'])
    expected = ['L00.foundation', 'L25.provider', 'L01.consumer']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: [module.id for module in discover(tmp_path)], range(8)))
    assert results == [expected] * 8
    steps = migration_steps(tmp_path)
    assert [step[0].split('/')[0] for step in steps[-3:]] == expected


@pytest.mark.parametrize('dependencies', [['L02.absent'], ['L01.consumer'], ['L00.foundation', 'L00.foundation']])
def test_invalid_dependencies_fail_closed(tmp_path, dependencies):
    register(tmp_path, 'L00.foundation')
    register(tmp_path, 'L01.consumer', dependencies)
    with pytest.raises(ValueError):
        discover(tmp_path)


def test_cycle(tmp_path):
    register(tmp_path, 'L01.first', ['L02.second'])
    register(tmp_path, 'L02.second', ['L01.first'])
    with pytest.raises(ValueError, match='Cyclic'):
        discover(tmp_path)


def test_path_escape(tmp_path):
    register(tmp_path, 'L01.first')
    metadata = tmp_path / 'L01.first' / 'module.json'
    value = json.loads(metadata.read_text())
    value['migrations'] = ['../../outside.sql']
    metadata.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        discover(tmp_path)


@pytest.mark.parametrize('dependencies', ['L01.first', [None], [{}], ['L26.invalid']])
def test_dependency_shape(tmp_path, dependencies):
    register(tmp_path, 'L01.first')
    metadata = tmp_path / 'L01.first' / 'module.json'
    value = json.loads(metadata.read_text())
    value['migration_dependencies'] = dependencies
    metadata.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Migration dependencies'):
        discover(tmp_path)
