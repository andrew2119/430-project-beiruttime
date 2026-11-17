"""Durable private photo core; composition supplies a serialized current-access lease."""
import hashlib
import importlib.util
import io
import json
import sqlite3
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from PIL import Image, ImageOps, UnidentifiedImageError

_contract = Path(__file__).resolve().parents[4] / 'packages/contracts-comms/message-photos/current.py'
# The contract is loaded without importing another service.
_spec = importlib.util.spec_from_file_location('message_photo_contract', _contract)
c = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = c
_spec.loader.exec_module(c)

class PhotoError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def scrub(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= c.MAX_BYTES:
        raise PhotoError('unsafe_photo')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ('JPEG', 'PNG', 'WEBP') or getattr(source, 'n_frames', 1) != 1:
                    raise PhotoError('unsafe_photo')
                if source.width * source.height > c.MAX_PIXELS:
                    raise PhotoError('unsafe_photo')
                source.load()
                oriented = ImageOps.exif_transpose(source).convert('RGB')
                clean = Image.new('RGB', oriented.size)
                clean.paste(oriented)
                output = io.BytesIO()
                clean.save(output, format='JPEG', quality=85)
                result = output.getvalue()
                if len(result) > c.MAX_BYTES:
                    raise PhotoError('unsafe_photo')
                return result, clean.width, clean.height
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise PhotoError('unsafe_photo') from error


class Store:
    def __init__(self, path, authority, clock):
        self.path, self.authority, self.clock = path, authority, clock
        with self.connect() as db:
            db.executescript((Path(__file__).parent / 'migrations/l25_001_photos.sql').read_text())

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def check(self, current, scope, write=False):
        if current.scope.actor != scope.actor or current.scope.business != scope.business or current.scope.thread != scope.thread or current.scope.watch != scope.watch:
            raise PhotoError('denied')
        if not current.identity_active or not current.business_active or not current.record_access:
            raise PhotoError('denied')
        support = current.support_assignment and current.active_obligation
        if current.kind not in ('listing', 'order', 'business') or not (current.member or support) or (current.blocked and not support):
            raise PhotoError('denied')
        if write and current.scope.revision != scope.revision:
            raise PhotoError('stale_revision')

    def expire(self, db):
        db.execute('DELETE FROM l25_photos WHERE attached=0 AND created<=?',
                   (self.clock() - c.ORPHAN_SECONDS,))

    def result(self, scope, operation, state, photo=None):
        result = {'schema_version': c.VERSION, 'operation_id': operation,
                  'subject_id': scope.thread, 'watch_id': scope.watch,
                  'actor_id': scope.actor, 'organization_id': scope.business,
                  'expected_revision': scope.revision, 'state': state,
                  'revision': scope.revision,
                  'pending_reason': 'result_unknown' if state == 'pending' else None,
                  'next_actor': scope.actor if state == 'pending' else None,
                  'next_review_at': None}
        if photo is not None:
            result['photo'] = photo
        return result

    def command(self, scope, operation, kind, photo=None, raw=None, purpose='watch_detail', declaration=False):
        if not isinstance(operation, str) or not 1 <= len(operation) <= 128 or kind not in ('upload', 'attach'):
            raise PhotoError('invalid_request')
        if purpose != 'watch_detail' or declaration is not True:
            raise PhotoError('classified_route_required')
        if raw is not None and (not isinstance(raw, bytes) or len(raw) > c.MAX_BYTES):
            raise PhotoError('unsafe_photo')
        fingerprint = hashlib.sha256(json.dumps([scope.__dict__, kind, photo, purpose,
            hashlib.sha256(raw).hexdigest() if raw is not None else None], sort_keys=True).encode()).hexdigest()
        # Lease must fence membership/revision changes until this transaction completes.
        # The provider enforces a bounded acquisition and raises on timeout.
        with self.authority(scope, timeout=2) as current, self.connect() as db:
            self.check(current, scope)
            db.execute('BEGIN IMMEDIATE')
            self.expire(db)
            old = db.execute('SELECT * FROM l25_operations WHERE id=?', (operation,)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise PhotoError('operation_conflict')
                return json.loads(old['result'])
            self.check(current, scope, write=True)
            if kind == 'upload':
                data, width, height = scrub(raw)
                count = db.execute('SELECT count(*) FROM l25_photos WHERE actor=? AND business=? AND thread=?',
                                   (scope.actor, scope.business, scope.thread)).fetchone()[0]
                if count >= c.MAX_PHOTOS:
                    raise PhotoError('photo_limit')
                photo = str(uuid4())
                db.execute('INSERT INTO l25_photos VALUES(?,?,?,?,?,?,?,0,?,?,?)',
                           (photo, scope.actor, scope.business, scope.thread, scope.watch,
                            scope.revision, self.clock(), data, width, height))
                result = self.result(scope, operation, 'uploaded', photo)
            else:
                row = self.row(db, scope, photo)
                if row['actor'] != scope.actor:
                    raise PhotoError('denied')
                if row['source_revision'] != scope.revision:
                    raise PhotoError('stale_revision')
                if row['attached']:
                    raise PhotoError('already_attached')
                db.execute('UPDATE l25_photos SET attached=1 WHERE id=?', (photo,))
                result = self.result(scope, operation, 'attached', photo)
                # No evidence references enter the event payload.
                db.execute('INSERT INTO l25_outbox VALUES(?,?)', (operation, json.dumps({'type': 'communications.thread-changed.v1', 'thread': scope.thread})))
            db.execute('INSERT INTO l25_operations VALUES(?,?,?,?,?,?,?)',
                       (operation, scope.actor, scope.business, scope.thread, scope.watch, fingerprint, json.dumps(result)))
            return result

    def row(self, db, scope, photo):
        row = db.execute('SELECT * FROM l25_photos WHERE id=? AND business=? AND thread=? AND watch=?',
                         (photo, scope.business, scope.thread, scope.watch)).fetchone()
        if row is None or (not row['attached'] and (row['actor'] != scope.actor or row['created'] <= self.clock()-c.ORPHAN_SECONDS)):
            raise PhotoError('denied')
        return row

    def read(self, scope, kind, photo=None, operation=None, offset=0, limit=20):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise PhotoError('invalid_request')
        with self.authority(scope, timeout=2) as current, self.connect() as db:
            self.check(current, scope)
            db.execute('BEGIN')
            if kind == 'operation':
                row = db.execute('SELECT result FROM l25_operations WHERE id=? AND actor=? AND business=? AND thread=? AND watch=?',
                                 (operation, scope.actor, scope.business, scope.thread, scope.watch)).fetchone()
                return json.loads(row[0]) if row else self.result(scope, operation, 'pending')
            if kind == 'list':
                values = (scope.business, scope.thread, scope.watch)
                total = db.execute('SELECT count(*) FROM l25_photos WHERE business=? AND thread=? AND watch=? AND attached=1', values).fetchone()[0]
                rows = db.execute('SELECT id,width,height FROM l25_photos WHERE business=? AND thread=? AND watch=? AND attached=1 ORDER BY created,id LIMIT ? OFFSET ?', (*values, limit, offset)).fetchall()
                return {'items': [dict(row) for row in rows], 'total': total, 'next_offset': offset+limit if offset+limit < total else None}
            row = self.row(db, scope, photo)
            if kind == 'bytes':
                return row['bytes']
            if kind == 'metadata':
                return {key: row[key] for key in ('id', 'width', 'height', 'source_revision', 'attached')}
            raise PhotoError('invalid_request')

    def sweep(self):
        with self.connect() as db:
            self.expire(db)
