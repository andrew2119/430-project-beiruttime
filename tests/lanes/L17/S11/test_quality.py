import importlib.util
from pathlib import Path
from datetime import timedelta
from uuid import UUID
import pytest

ROOT = Path(__file__).resolve().parents[4]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core = load('quality_core', 'services/service-operations/modules/quality/core.py')
fixtures = load('quality_fixtures', 'packages/contracts-service/quality/fixtures.py')
c = core.contract


@pytest.fixture
def sample(tmp_path):
    command, current, now = fixtures.fixture()
    store = core.LocalStore(tmp_path / 'quality.db')
    yield store, c.Record(**command), c.Current(**current), now
    store.close()


def changed(model, **values):
    return type(model).model_validate({**model.model_dump(), **values})


def test_positive_duplicate_restart(sample, tmp_path):
    store, command, current, now = sample
    receipt = store.record(command, current, now)
    assert receipt['state'] == 'satisfactory'
    assert receipt['subject_id'] == str(command.job_id)
    assert receipt['expected_revision'] == command.expected_revision
    assert receipt['quote_id'] == str(command.quote_id)
    assert receipt['quote_revision'] == command.quote_revision
    assert receipt['policy_revision'] == command.policy_revision
    assert store.handover(command, current, now)
    assert store.record(command, current, now) == receipt
    second = core.LocalStore(tmp_path / 'quality.db')
    assert second.operation(command.operation_id, current, now) == receipt
    assert second.record(command, current, now) == receipt
    assert second.db.execute('SELECT count(*) FROM quality_outbox').fetchone()[0] == 1
    second.close()


@pytest.mark.parametrize('field,value', [
    ('permitted', False), ('qualified', False), ('assessor_qualified', False), ('approver_qualified', False), ('organization_id', UUID(int=44)),
    ('actor_id', UUID(int=44)), ('quality_reviewer_id', UUID(int=8)),
    ('approver_id', UUID(int=8)), ('performer_ids', {UUID(int=6)}),
    ('assignment_revision', 2), ('scope_revision', 2), ('work_revision', 2),
    ('quote_revision', 2), ('policy_revision', 2), ('watch_id', UUID(int=44)),
    ('incident_open', True), ('custody_current', False), ('payment_held', False),
    ('commitment_current', False), ('accepted_current', False), ('completed_line_ids', set()),
])
def test_denied_and_stale(sample, field, value):
    store, command, current, now = sample
    with pytest.raises(core.Refused):
        store.record(command, changed(current, **{field: value}), now)
    assert store.db.execute('SELECT count(*) FROM quality_operations').fetchone()[0] == 0


@pytest.mark.parametrize('delta,allowed', [(-1, False), (0, True), (1, True), (2, False), (3, False)])
def test_time_boundaries(sample, delta, allowed):
    store, command, current, now = sample
    if allowed:
        store.record(command, current, now + timedelta(seconds=delta))
    else:
        with pytest.raises(core.Refused):
            store.record(command, current, now + timedelta(seconds=delta))


@pytest.mark.parametrize('field', ['tests', 'condition', 'fit', 'returned_parts'])
def test_failure_rework_then_current_check(sample, field):
    store, command, current, now = sample
    line = command.lines[0].model_dump()
    if field == 'tests':
        line[field][0]['satisfactory'] = False
    else:
        line[field]['satisfactory'] = False
    failed = changed(command, lines=[line])
    assert store.record(failed, current, now)['state'] == 'rework'
    assert not store.handover(failed, current, now)
    with pytest.raises(core.Refused, match='new_work_required'):
        store.record(changed(command, operation_id=UUID(int=54), expected_revision=1), current, now)
    updated = changed(current, work_revision=2)
    passed = changed(command, operation_id=UUID(int=55), work_revision=2, expected_revision=1)
    assert store.record(passed, updated, now)['revision'] == 2
    assert store.handover(passed, updated, now)
    with pytest.raises(core.Refused):
        store.handover(passed, changed(updated, incident_open=True), now)


def test_conflict_stale_missing_and_revoked_lookup(sample):
    store, command, current, now = sample
    store.record(command, current, now)
    for candidate in [changed(command, expected_revision=1), changed(command, operation_id=UUID(int=66))]:
        with pytest.raises(core.Refused):
            store.record(candidate, current, now)
    with pytest.raises(core.Refused):
        store.operation(command.operation_id, changed(current, permitted=False), now)
    with pytest.raises(core.Refused):
        store.operation(UUID(int=999), current, now)


def test_schema_bounds(sample):
    _, command, _, _ = sample
    for fields in [dict(expected_revision=True), dict(lines=[]), dict(lines=[command.lines[0]] * 2),
                   dict(lines=[{**command.lines[0].model_dump(), 'fit': {'key':'fit','actual':' ','satisfactory':True}}])]:
        with pytest.raises(ValueError):
            changed(command, **fields)


def test_fixtures():
    assert set(fixtures.cases()) == {'success', 'denied', 'stale', 'lost_response'}


def test_missing_applicable_test(sample):
    store, command, current, now = sample
    plan = {command.lines[0].line_id: {'actual', 'pressure'}}
    with pytest.raises(core.Refused, match='required_tests'):
        store.record(command, changed(current, required_tests=plan), now)


def test_atomic_rollback(sample):
    store, command, current, now = sample
    store.db.execute("CREATE TRIGGER reject_outbox BEFORE INSERT ON quality_outbox BEGIN SELECT RAISE(ABORT,'failed'); END")
    with pytest.raises(Exception, match='failed'):
        store.record(command, current, now)
    for table in ('quality_records', 'quality_operations', 'quality_outbox'):
        assert store.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
    store.db.execute('DROP TRIGGER reject_outbox')
    assert store.record(command, current, now)['revision'] == 1


def test_timeout_retains_operation(sample):
    import asyncio
    adapter_module = load('quality_adapter', 'services/service-operations/modules/quality/adapter.py')
    store, command, current, now = sample
    class Provider:
        async def current(self, principal, job_id, organization_id):
            raise TimeoutError()
    adapter = adapter_module.Adapter(store, Provider())
    result = asyncio.run(adapter.record(command, object()))
    assert result['state'] == 'pending'
    assert result['operation_id'] == str(command.operation_id)
    assert store.db.execute('SELECT count(*) FROM quality_operations').fetchone()[0] == 0
