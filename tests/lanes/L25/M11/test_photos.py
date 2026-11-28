import importlib.util
import io
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import pytest
from PIL import Image
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[4]
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

m = load('photos', 'services/communications/modules/message-photos/store.py')
r = load('photo_routes', 'services/communications/modules/message-photos/routes.py')

@pytest.fixture
def context(tmp_path):
    scope = m.c.Scope('buyer', 'business', 'thread', 'watch', 1)
    state = {'current': m.c.Authority(scope, 'listing', True, identity_active=True, business_active=True, record_access=True), 'now': 100, 'timeout': False}
    @contextmanager
    def authority(request, timeout):
        assert timeout == 2
        if state['timeout']:
            raise TimeoutError()
        yield state['current']
    store = m.Store(tmp_path / 'photos.db', authority, lambda: state['now'])
    return store, scope, state


def image():
    output = io.BytesIO()
    pic = Image.new('RGB', (40, 30), 'red')
    exif = Image.Exif()
    exif[270] = 'private location'
    pic.save(output, 'JPEG', exif=exif)
    return output.getvalue()


def upload(store, scope, op='upload'):
    return store.command(scope, op, 'upload', raw=image(), declaration=True)


def attached(store, scope):
    photo = upload(store, scope)['photo']
    store.command(scope, 'attach', 'attach', photo=photo, declaration=True)
    return photo


def test_positive_scrub_restart_duplicate(context):
    store, scope, state = context
    photo = attached(store, scope)
    pixels = store.read(scope, 'bytes', photo)
    assert b'private location' not in pixels
    assert Image.open(io.BytesIO(pixels)).getexif() == {}
    restarted = m.Store(store.path, store.authority, store.clock)
    assert restarted.command(scope, 'attach', 'attach', photo=photo, declaration=True)['state'] == 'attached'
    assert restarted.read(scope, 'operation', operation='attach')['photo'] == photo
    assert restarted.read(scope, 'list')['total'] == 1
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM l25_outbox').fetchone()[0] == 1
        assert photo not in db.execute('SELECT event FROM l25_outbox').fetchone()[0]


@pytest.mark.parametrize('change', [{'member': False}, {'blocked': True}, {'identity_active': False}, {'business_active': False}, {'record_access': False}, {'scope': m.c.Scope('other', 'business', 'thread', 'watch', 1)}, {'scope': m.c.Scope('buyer', 'other', 'thread', 'watch', 1)}])
def test_revoked_all_reads_and_retries(context, change):
    store, scope, state = context
    photo = attached(store, scope)
    state['current'] = replace(state['current'], **change)
    for kind in ('list', 'metadata', 'bytes', 'operation'):
        with pytest.raises(m.PhotoError, match='denied'):
            store.read(scope, kind, photo, 'attach')
    with pytest.raises(m.PhotoError, match='denied'):
        store.command(scope, 'attach', 'attach', photo=photo, declaration=True)


def test_stale_cross_thread_scope_conflict(context):
    store, scope, state = context
    photo = upload(store, scope)['photo']
    state['current'] = replace(state['current'], scope=replace(scope, revision=2))
    with pytest.raises(m.PhotoError, match='stale_revision'):
        store.command(scope, 'attach', 'attach', photo=photo, declaration=True)
    other = replace(scope, thread='other')
    state['current'] = replace(state['current'], scope=other)
    with pytest.raises(m.PhotoError, match='denied'):
        store.read(other, 'bytes', photo)
    with pytest.raises(m.PhotoError, match='operation_conflict'):
        upload(store, other)


@pytest.mark.parametrize('delta,exists', [(-1, True), (0, False), (1, False)])
def test_orphan_boundary(context, delta, exists):
    store, scope, state = context
    photo = upload(store, scope)['photo']
    state['now'] += m.c.ORPHAN_SECONDS + delta
    store.sweep()
    with store.connect() as db:
        assert bool(db.execute('SELECT id FROM l25_photos WHERE id=?', (photo,)).fetchone()) == exists


def test_unsafe_classified_and_limits(context):
    store, scope, state = context
    for raw in (b'not pixels', b'x' * (m.c.MAX_BYTES + 1)):
        with pytest.raises(m.PhotoError, match='unsafe_photo'):
            store.command(scope, 'unsafe', 'upload', raw=raw, declaration=True)
    with pytest.raises(m.PhotoError, match='classified_route_required'):
        store.command(scope, 'identity', 'upload', raw=image(), purpose='identity', declaration=True)
    for i in range(m.c.MAX_PHOTOS):
        upload(store, scope, str(i))
    with pytest.raises(m.PhotoError, match='photo_limit'):
        upload(store, scope, 'excess')


def test_support_assignment_is_required(context):
    store, scope, state = context
    photo = attached(store, scope)
    state['current'] = replace(state['current'], member=False, blocked=True, support_assignment=True, active_obligation=True)
    assert store.read(scope, 'bytes', photo)
    state['current'] = replace(state['current'], active_obligation=False)
    with pytest.raises(m.PhotoError, match='denied'):
        store.read(scope, 'bytes', photo)


def test_timeout_and_headers(context):
    store, scope, state = context
    app = FastAPI()
    app.include_router(r.create_router(store, lambda: scope))
    endpoints = {route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")}
    photo = attached(store, scope)
    response = endpoints['/v1/message-photos/{photo}/bytes'](photo=photo, scope=scope)
    assert response.status_code == 200
    assert 'no-store' in response.headers['cache-control']
    state['timeout'] = True
    response = endpoints['/v1/message-photos'](offset=0, limit=20, scope=scope)
    assert response.status_code == 503
    import json
    assert set(json.loads(response.body)['error']['details']['messages']) == {'en', 'ar'}
    state['timeout'] = False
    assert store.read(scope, 'operation', operation='attach')['state'] == 'attached'


@pytest.mark.parametrize('total', [0, 1, 1000])
def test_pagination_uses_server_totals(context, total):
    store, scope, state = context
    # Synthetic storage fixture exercises real list queries, not connected authority.
    with store.connect() as db:
        db.executemany('INSERT INTO l25_photos VALUES(?,?,?,?,?,?,?,1,?,?,?)',
                       [(f'synthetic-{i:04}', f'member-{i}', scope.business, scope.thread,
                         scope.watch, 1, 100, b'synthetic', 40, 30) for i in range(total)])
    ids, offset = [], 0
    while True:
        page = store.read(scope, 'list', offset=offset, limit=20)
        assert page['total'] == total
        ids.extend(item['id'] for item in page['items'])
        if page['next_offset'] is None:
            break
        offset = page['next_offset']
    assert len(ids) == len(set(ids)) == total
    with pytest.raises(m.PhotoError, match='invalid_request'):
        store.read(scope, 'list', limit=51)


def test_animation_and_decoded_pixel_limit(context):
    store, scope, state = context
    output = io.BytesIO()
    Image.new('RGB', (4000, 3001)).save(output, 'PNG')
    with pytest.raises(m.PhotoError, match='unsafe_photo'):
        store.command(scope, 'too-many-pixels', 'upload', raw=output.getvalue(), declaration=True)
    output = io.BytesIO()
    Image.new('RGB', (10, 10), 'red').save(output, 'PNG', save_all=True,
        append_images=[Image.new('RGB', (10, 10), 'blue')], duration=100)
    with pytest.raises(m.PhotoError, match='unsafe_photo'):
        store.command(scope, 'animated', 'upload', raw=output.getvalue(), declaration=True)
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM l25_photos').fetchone()[0] == 0


def test_attachment_and_outbox_rollback_together(context):
    store, scope, state = context
    photo = upload(store, scope)['photo']
    with store.connect() as db:
        db.execute("CREATE TRIGGER synthetic_failure BEFORE INSERT ON l25_outbox BEGIN SELECT RAISE(ABORT, 'unavailable'); END")
    with pytest.raises(Exception, match='unavailable'):
        store.command(scope, 'attach', 'attach', photo=photo, declaration=True)
    assert store.read(scope, 'metadata', photo)['attached'] == 0
    assert store.read(scope, 'operation', operation='attach')['state'] == 'pending'
    with store.connect() as db:
        db.execute('DROP TRIGGER synthetic_failure')
    assert store.command(scope, 'attach', 'attach', photo=photo, declaration=True)['state'] == 'attached'


def test_versioned_fixtures_match_route_errors_and_receipts(context):
    import json
    store, scope, state = context
    fixtures = json.loads((ROOT / 'packages/contracts-comms/message-photos/fixtures.json').read_text())
    assert fixtures['version'] == m.c.VERSION and fixtures['synthetic'] is True
    photo = attached(store, scope)
    receipt = store.read(scope, 'operation', operation='attach')
    assert receipt == {**fixtures['success'], 'operation_id': 'attach', 'photo': photo}
    assert receipt['schema_version'] == m.c.VERSION
    assert receipt['expected_revision'] == scope.revision
    assert fixtures['lost_response'] == store.read(scope, 'operation', operation='sample-attach-1')
    state['current'] = replace(state['current'], member=False)
    router = r.create_router(store, lambda: scope)
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith('/{photo}/bytes'))
    response = endpoint(photo=photo, scope=scope)
    assert json.loads(response.body) == fixtures['denied']
