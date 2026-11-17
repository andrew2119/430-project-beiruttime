import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from bt_contracts.service.appointments.v1 import Authority, Command, Visit
from appointments.model import Rejected, resolve
from appointments.routes import router_for
from appointments.store import Store


def uid(n):
    return UUID(int=n)


def command(**changes):
    data = dict(operation_id=uid(1), appointment_id=uid(2), subject_id=uid(3), watch_id=uid(4),
                actor_id=uid(3), organization_id=uid(5), expected_revision=0, source_revision=1,
                policy_revision=1, assignment_revision=1, kind='request', purpose='fit',
                civil_time='2027-01-10T10:00', duration_minutes=30)
    return Command(**(data | changes))


@pytest.fixture
def scenario(tmp_path):
    now = [datetime(2027, 1, 1, tzinfo=timezone.utc)]
    flags = dict(active=True, onboarded=True, record_allowed=True)

    async def authority(actor, subject, watch, organization):
        if actor not in (uid(3), uid(6)):
            raise Rejected('denied', 403)
        return Authority(actor_id=actor, subject_id=uid(3), watch_id=uid(4), organization_id=uid(5),
                         source_revision=1, policy_revision=1, role='buyer' if actor == uid(3) else 'business',
                         purposes=('intake', 'assessment', 'fit', 'collection'), assignment_revision=1, **flags,
                         business_kind='brand')
    store = Store(tmp_path / 'visits.db', authority, lambda: now[0])
    return store, now, flags


def changed(prior, **changes):
    return command(**(dict(operation_id=uid(10), expected_revision=prior.revision,
                          kind='confirm', actor_id=uid(6)) | changes))


@pytest.mark.asyncio
@pytest.mark.parametrize('purpose', ['intake', 'assessment', 'fit', 'collection'])
async def test_request_confirm_reschedule_cancel_restart(scenario, purpose):
    store, _, _ = scenario
    request = command(purpose=purpose)
    visit = await store.execute(request, uid(3))
    assert visit.state == 'requested' and visit.confirmed_by is None
    confirmation = changed(visit, purpose=purpose)
    visit = await store.execute(confirmation, uid(6))
    assert visit.state == 'confirmed' and visit.confirmed_by == uid(6)
    assert not any((visit.physical_release_allowed, visit.custody_received, visit.work_authorized))
    moved = command(operation_id=uid(11), expected_revision=2, kind='reschedule', purpose=purpose,
                    civil_time='2027-01-11T10:00')
    visit = await store.execute(moved, uid(3))
    assert visit.state == 'requested' and visit.confirmed_by is None
    cancel = moved.model_copy(update=dict(operation_id=uid(12), expected_revision=3, kind='cancel'))
    result = await store.execute(cancel, uid(3))
    restarted = Store(store.path, store.authority, store.clock)
    assert await restarted.execute(cancel, uid(3)) == result
    assert await restarted.read(uid(2), uid(3), uid(5), uid(12)) == result
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM l20_p03_outbox').fetchone()[0] == 4


@pytest.mark.asyncio
async def test_scope_revocation_duplicates_and_stale(scenario):
    store, _, flags = scenario
    request = command()
    visit = await store.execute(request, uid(3))
    assert await store.execute(request, uid(3)) == visit
    for cmd, actor, code in [
        (command(purpose='assessment'), uid(3), 'duplicate_conflict'),
        (changed(visit, actor_id=uid(3)), uid(3), 'denied'),
        (changed(visit, organization_id=uid(8)), uid(6), 'denied'),
        (changed(visit, subject_id=uid(8)), uid(6), 'denied'),
        (changed(visit, watch_id=uid(8)), uid(6), 'denied'),
        (changed(visit, source_revision=2), uid(6), 'stale_revision'),
        (changed(visit, assignment_revision=2), uid(6), 'stale_revision'),
        (changed(visit), uid(7), 'denied'),
    ]:
        with pytest.raises(Rejected, match=code):
            await store.execute(cmd, actor)
    flags['active'] = False
    with pytest.raises(Rejected, match='denied'):
        await store.execute(request, uid(3))
    with pytest.raises(Rejected, match='denied'):
        await store.read(uid(2), uid(3), uid(5), uid(1))


@pytest.mark.asyncio
async def test_slot_boundary_and_stale_revision(scenario):
    store, _, _ = scenario
    first = await store.execute(command(), uid(3))
    await store.execute(changed(first), uid(6))
    second = await store.execute(command(operation_id=uid(21), appointment_id=uid(22)), uid(3))
    with pytest.raises(Rejected, match='slot_conflict'):
        await store.execute(changed(second, operation_id=uid(23), appointment_id=uid(22)), uid(6))
    with pytest.raises(Rejected, match='stale_revision'):
        await store.execute(changed(first, operation_id=uid(24)), uid(6))
    third = await store.execute(command(operation_id=uid(31), appointment_id=uid(32),
                                        civil_time='2027-01-10T10:30'), uid(3))
    await store.execute(changed(third, operation_id=uid(33), appointment_id=uid(32),
                                civil_time='2027-01-10T10:30'), uid(6))


@pytest.mark.asyncio
@pytest.mark.parametrize('delta,allowed', [(-1, True), (0, False), (1, False)])
async def test_server_start_boundary(scenario, delta, allowed):
    from datetime import timedelta
    store, now, _ = scenario
    now[0] = resolve(command()) + timedelta(seconds=delta)
    if allowed:
        await store.execute(command(), uid(3))
    else:
        with pytest.raises(Rejected, match='elapsed'):
            await store.execute(command(), uid(3))


def test_clock_change_requires_explicit_resolution():
    with pytest.raises(Rejected, match='missing_time'):
        resolve(command(civil_time='2027-03-28T00:30'))
    repeated = command(civil_time='2027-10-30T23:30')
    with pytest.raises(Rejected, match='repeated_time') as error:
        resolve(repeated)
    assert len(error.value.candidates) == 2
    for candidate in error.value.candidates:
        selected = Command.model_validate(repeated.model_dump() | dict(selected_instant=candidate,
                                                                       repeated_time_confirmed=True))
        assert resolve(selected).isoformat() == candidate
    with pytest.raises(Rejected, match='instant_mismatch'):
        resolve(command(selected_instant=datetime(2027, 1, 10, 10, tzinfo=timezone.utc)))


@pytest.mark.asyncio
async def test_timeout_has_no_receipt_and_retry_is_stable(scenario):
    store, _, _ = scenario
    provider = store.authority

    async def unavailable(*args):
        raise TimeoutError
    store.authority = unavailable
    with pytest.raises(Rejected, match='unavailable'):
        await store.execute(command(), uid(3))
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM l20_p03_receipts').fetchone()[0] == 0
    store.authority = provider
    results = await asyncio.gather(*(store.execute(command(), uid(3)) for _ in range(3)))
    assert all(result == results[0] for result in results)
    with pytest.raises(Rejected, match='denied'):
        await store.read(uid(2), uid(8), uid(5))


@pytest.mark.parametrize('changes', [dict(duration_minutes=True), dict(duration_minutes=121),
                                   dict(expected_revision=-1), dict(civil_time='2027-02-30T10:00'),
                                   dict(quote_id=uid(7)), dict(private_file='bytes')])
def test_contract_bounds(changes):
    with pytest.raises(ValidationError):
        command(**changes)


@pytest.mark.asyncio
async def test_route_limits_and_lookup(scenario):
    store, _, flags = scenario
    fixtures = json.loads((Path(__file__).resolve().parents[4] /
                          'packages/contracts-service/appointments/fixtures.json').read_text())
    app = FastAPI()
    async def actor():
        return SimpleNamespace(subject_id=uid(3))
    app.include_router(router_for(store, actor))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        assert (await client.post('/v1/appointments/commands', content='x' * 4097)).status_code == 413
        response = await client.post('/v1/appointments/commands', json=command().model_dump(mode='json'))
        assert response.status_code == 200
        assert response.json() == fixtures['outcomes']['request']
        assert response.headers['cache-control'] == 'no-store'
        result = await client.get(f'/v1/appointments/operations/{uid(1)}',
                                  params=dict(appointment_id=str(uid(2)), organization_id=str(uid(5))))
        assert result.json() == fixtures['outcomes']['lost_response']
        stale = await client.post('/v1/appointments/commands',
                                  json=command(operation_id=uid(90), source_revision=2).model_dump(mode='json'))
        assert stale.status_code == 409
        assert stale.json() == fixtures['outcomes']['stale']
        flags['active'] = False
        denied = await client.post('/v1/appointments/commands', json=command().model_dump(mode='json'))
        assert denied.status_code == 403
        assert denied.json() == fixtures['outcomes']['denied']
        flags['active'] = True
        assert (await client.get(f'/v1/appointments/operations/{uid(9)}',
                                params=dict(appointment_id=str(uid(2)), organization_id=str(uid(5))))).status_code == 404


def test_published_fixtures():
    path = Path(__file__).resolve().parents[4] / 'packages/contracts-service/appointments/fixtures.json'
    data = json.loads(path.read_text())
    for item in data['commands'].values():
        Command.model_validate(item)
    Visit.model_validate(data['outcomes']['request'])
    assert data['outcomes']['request'] == data['outcomes']['lost_response']
    assert data['outcomes']['denied']['error']['code'] == 'denied'
    assert data['outcomes']['stale']['error']['code'] == 'stale_revision'


@pytest.mark.asyncio
@pytest.mark.parametrize('flag', ['active', 'onboarded', 'record_allowed'])
async def test_current_authority_denial_leaves_no_write(scenario, flag):
    store, _, flags = scenario
    flags[flag] = False
    with pytest.raises(Rejected, match='denied'):
        await store.execute(command(), uid(3))
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM l20_p03_receipts').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_real_dependency_deadline(scenario):
    store, _, _ = scenario
    async def stalled(*args):
        await asyncio.Event().wait()
    store.authority = stalled
    with pytest.raises(Rejected, match='unavailable'):
        await asyncio.wait_for(store.execute(command(), uid(3)), timeout=2)


@pytest.mark.asyncio
async def test_retained_quote_and_terminal_state(scenario):
    store, _, _ = scenario
    with pytest.raises(Rejected, match='stale_revision'):
        await store.execute(command(quote_id=uid(90), quote_revision=1), uid(3))
    visit = await store.execute(command(), uid(3))
    cancel = changed(visit, actor_id=uid(3), kind='cancel')
    await store.execute(cancel, uid(3))
    with pytest.raises(Rejected, match='cancelled'):
        await store.execute(changed(visit, operation_id=uid(11), expected_revision=2), uid(6))


@pytest.mark.asyncio
async def test_private_operation_lookup_cannot_cross_actor_or_record(scenario):
    store, _, _ = scenario
    await store.execute(command(), uid(3))
    other = command(operation_id=uid(20), appointment_id=uid(21))
    await store.execute(other, uid(3))
    with pytest.raises(Rejected, match='denied'):
        await store.read(uid(21), uid(3), uid(5), uid(1))
    with pytest.raises(Rejected, match='denied'):
        await store.read(uid(2), uid(6), uid(5), uid(1))


@pytest.mark.asyncio
@pytest.mark.parametrize('actor', [uid(3), uid(6)])
@pytest.mark.parametrize('binding', ['source_revision', 'policy_revision', 'quote_revision'])
async def test_reviewed_cancellation_after_authority_change(scenario, actor, binding):
    store, _, flags = scenario
    provider = store.authority

    async def quoted(*args):
        current = await provider(*args)
        return current.model_copy(update=dict(quote_id=uid(90), quote_revision=1))

    store.authority = quoted
    visit = await store.execute(command(quote_id=uid(90), quote_revision=1), uid(3))

    async def revised(*args):
        current = await quoted(*args)
        return current.model_copy(update={binding: 2})

    store.authority = revised
    cancel = changed(visit, actor_id=actor, kind='cancel', quote_id=uid(90), quote_revision=1)
    with pytest.raises(Rejected, match='stale_revision'):
        await store.execute(cancel, actor)
    reviewed = Command.model_validate(cancel.model_dump() | {binding: 2})
    with pytest.raises(Rejected, match='stale_revision'):
        await store.execute(Command.model_validate(reviewed.model_dump() | dict(expected_revision=2)), actor)
    with pytest.raises(Rejected, match='stale_revision'):
        await store.execute(Command.model_validate(reviewed.model_dump() | dict(duration_minutes=45)), actor)
    result = await store.execute(reviewed, actor)
    assert result.state == 'cancelled' and result.revision == 2
    for name in ('source_revision', 'policy_revision', 'quote_id', 'quote_revision'):
        assert getattr(result, name) == getattr(visit, name)
    restarted = Store(store.path, store.authority, store.clock)
    assert await restarted.execute(reviewed, actor) == result
    assert await restarted.read(visit.appointment_id, actor, uid(5), reviewed.operation_id) == result
    with store.connect() as db:
        saved = db.execute('SELECT command FROM l20_p03_receipts WHERE id=?',
                           (str(reviewed.operation_id),)).fetchone()
        assert Command.model_validate_json(saved['command']) == reviewed
        assert db.execute('SELECT count(*) FROM l20_p03_outbox').fetchone()[0] == 2
    flags['active'] = False
    with pytest.raises(Rejected, match='denied'):
        await restarted.execute(reviewed, actor)
