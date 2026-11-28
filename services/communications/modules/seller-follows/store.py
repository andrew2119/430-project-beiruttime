"""Durable personal follows and publication receipts; no delivery credentials."""
import asyncio
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from uuid import UUID, uuid5, NAMESPACE_URL
from fastapi import HTTPException


def instant(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise HTTPException(503, 'unavailable')
    return value.astimezone(timezone.utc).isoformat()


class Store:
    def __init__(self, path, identity, catalog, clock=lambda: datetime.now(timezone.utc)):
        self.path, self.identity, self.catalog, self.clock = path, identity, catalog, clock
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS follows(
              actor TEXT, seller TEXT, following INTEGER, alerts INTEGER,
              revision INTEGER, since TEXT, PRIMARY KEY(actor,seller));
            CREATE TABLE IF NOT EXISTS operations(
              id TEXT PRIMARY KEY, actor TEXT, payload TEXT, receipt TEXT);
            CREATE TABLE IF NOT EXISTS publications(
              seller TEXT, watch TEXT, revision INTEGER, payload TEXT,
              PRIMARY KEY(seller,watch,revision));
            CREATE TABLE IF NOT EXISTS notices(
              id TEXT PRIMARY KEY, actor TEXT, seller TEXT, watch TEXT,
              revision INTEGER, occurred TEXT, sample INTEGER,
              UNIQUE(actor,seller,watch,revision));
            ''')
            db.execute('BEGIN IMMEDIATE')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(notices)')}
            if 'notice_revision' not in columns:
                migration = Path(__file__).with_name('migrations') / 'L22_0001_notice_lifecycle.sql'
                for statement in migration.read_text().split(';'):
                    if statement.strip():
                        db.execute(statement)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=.3)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    async def dependency(self, call, *args):
        try:
            return await asyncio.wait_for(call(*args), timeout=.3)
        except (TimeoutError, OSError, ValueError):
            raise HTTPException(503, 'unavailable') from None

    async def authorize(self, token):
        principal = await self.dependency(self.identity, token)
        if (not principal or principal.get('organization_id') is not None or
                principal.get('active') is not True or 'buyer' not in principal.get('roles', [])):
            raise HTTPException(403, 'denied')
        try:
            return str(UUID(principal['actor_id']))
        except (KeyError, ValueError, TypeError):
            raise HTTPException(503, 'unavailable') from None

    @staticmethod
    def result(row):
        return dict(seller_id=row['seller'], following=bool(row['following']),
                    alerts_enabled=bool(row['alerts']), revision=row['revision'])

    async def command(self, token, command):
        actor = await self.authorize(token)
        if actor != str(command.actor_id) or command.organization_id is not None:
            raise HTTPException(403, 'denied')
        seller, operation = str(command.seller_id), str(command.operation_id)
        payload = command.model_dump_json()
        with self.connect() as db:
            retained = db.execute('SELECT * FROM operations WHERE id=?', (operation,)).fetchone()
            if retained:
                if retained['actor'] != actor or retained['payload'] != payload:
                    raise HTTPException(409, 'operation_conflict')
                return json.loads(retained['receipt'])
        # Admission contains no await after fresh facts; composition serializes
        # authority changes with provider admission before calling this boundary.
        if command.following:
            facts = await self.dependency(self.catalog, seller, None)
            if not facts or facts.get('public') is not True or facts.get('seller_id') != seller:
                raise HTTPException(404, 'unavailable')
        now = instant(self.clock())
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM operations WHERE id=?', (operation,)).fetchone()
            if old:
                if old['actor'] != actor or old['payload'] != payload:
                    raise HTTPException(409, 'operation_conflict')
                return json.loads(old['receipt'])
            row = db.execute('SELECT * FROM follows WHERE actor=? AND seller=?', (actor, seller)).fetchone()
            revision = row['revision'] if row else 0
            if revision != command.expected_revision:
                raise HTTPException(409, 'stale_revision')
            enabled = command.following and command.alerts_enabled
            since = row['since'] if row and row['following'] and row['alerts'] and enabled else now
            revision += 1
            db.execute('INSERT OR REPLACE INTO follows VALUES(?,?,?,?,?,?)',
                       (actor, seller, command.following, enabled, revision, since))
            result = dict(seller_id=seller, following=command.following, alerts_enabled=enabled, revision=revision)
            receipt = dict(schema_version='seller-follows.v1', operation_id=operation, actor_id=actor,
                           organization_id=None, seller_id=seller, state='accepted', revision=revision, result=result)
            db.execute('INSERT INTO operations VALUES(?,?,?,?)', (operation, actor, payload, json.dumps(receipt)))
            return receipt

    async def operation(self, token, operation):
        actor = await self.authorize(token)
        with self.connect() as db:
            row = db.execute('SELECT receipt FROM operations WHERE id=? AND actor=?', (str(operation), actor)).fetchone()
            if not row:
                raise HTTPException(404, 'unavailable')
            return json.loads(row['receipt'])

    async def page(self, token, page=0):
        actor = await self.authorize(token)
        if type(page) is not int or not 0 <= page <= 20000:
            raise HTTPException(422, 'invalid_page')
        with self.connect() as db:
            total = db.execute('SELECT count(*) FROM follows WHERE actor=? AND following=1', (actor,)).fetchone()[0]
            rows = db.execute('SELECT * FROM follows WHERE actor=? AND following=1 ORDER BY seller LIMIT 50 OFFSET ?', (actor, page*50)).fetchall()
            return dict(items=[self.result(row) for row in rows], total=total, page=page, page_size=50)

    async def publication(self, event):
        seller, watch = str(event.seller_id), str(event.watch_id)
        facts = await self.dependency(self.catalog, seller, watch)
        occurred = instant(event.published_at)
        if not isinstance(facts, dict) or type(facts.get('public')) is not bool:
            raise HTTPException(503, 'unavailable')
        if facts['public'] is False:
            return 0
        if any(facts.get(key) != value for key, value in dict(seller_id=seller, watch_id=watch,
                revision=event.revision, published_at=occurred, sample=event.sample).items()):
            raise HTTPException(409, 'stale_publication')
        if occurred > instant(self.clock()):
            raise HTTPException(409, 'future_publication')
        payload = json.dumps([seller, watch, event.revision, occurred, event.sample])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT payload FROM publications WHERE seller=? AND watch=? AND revision=?', (seller, watch, event.revision)).fetchone()
            if old:
                if old['payload'] != payload:
                    raise HTTPException(409, 'publication_conflict')
                return 0
            db.execute('INSERT INTO publications VALUES(?,?,?,?)', (seller, watch, event.revision, payload))
            followers = db.execute('SELECT actor FROM follows WHERE seller=? AND following=1 AND alerts=1 AND since<?', (seller, occurred))
            count = 0
            for row in followers:
                notice = str(uuid5(NAMESPACE_URL, f"seller-follows:{row['actor']}:{seller}:{watch}:{event.revision}"))
                db.execute('INSERT INTO notices(id,actor,seller,watch,revision,occurred,sample) VALUES(?,?,?,?,?,?,?)', (notice, row['actor'], seller, watch, event.revision, occurred, event.sample))
                count += 1
            return count

    async def notices(self, token, page=0):
        actor = await self.authorize(token)
        if type(page) is not int or not 0 <= page <= 20000:
            raise HTTPException(422, 'invalid_page')
        with self.connect() as db:
            rows = db.execute('SELECT id,watch,occurred,sample,read_at,cleared_at,notice_revision FROM notices WHERE actor=? AND cleared_at IS NULL ORDER BY occurred DESC,id LIMIT 50 OFFSET ?', (actor, page*50)).fetchall()
            total = db.execute('SELECT count(*) FROM notices WHERE actor=? AND cleared_at IS NULL', (actor,)).fetchone()[0]
            return dict(items=[dict(row) for row in rows], total=total, page=page, page_size=50)

    async def notice_command(self, token, command):
        actor = await self.authorize(token)
        if actor != str(command.actor_id) or command.organization_id is not None:
            raise HTTPException(403, 'denied')
        operation, notice = str(command.operation_id), str(command.notice_id)
        payload = command.model_dump_json()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            retained = db.execute('SELECT * FROM operations WHERE id=?', (operation,)).fetchone()
            if retained:
                if retained['actor'] != actor or retained['payload'] != payload:
                    raise HTTPException(409, 'operation_conflict')
                return json.loads(retained['receipt'])
            row = db.execute('SELECT * FROM notices WHERE id=? AND actor=?', (notice, actor)).fetchone()
            if not row:
                raise HTTPException(404, 'unavailable')
            if row['notice_revision'] != command.expected_revision:
                raise HTTPException(409, 'stale_revision')
            column = 'read_at' if command.action == 'read' else 'cleared_at'
            timestamp = row[column] or instant(self.clock())
            revision = row['notice_revision'] + 1
            db.execute(f'UPDATE notices SET {column}=?, notice_revision=? WHERE id=?',
                       (timestamp, revision, notice))
            receipt = dict(schema_version='seller-follows.v1', operation_id=operation,
                           actor_id=actor, organization_id=None, notice_id=notice,
                           state='accepted', revision=revision,
                           read_at=timestamp if column == 'read_at' else row['read_at'],
                           cleared_at=timestamp if column == 'cleared_at' else row['cleared_at'])
            db.execute('INSERT INTO operations VALUES(?,?,?,?)',
                       (operation, actor, payload, json.dumps(receipt)))
            return receipt

    async def destination(self, token, notice):
        actor = await self.authorize(token)
        with self.connect() as db:
            row = db.execute('SELECT * FROM notices WHERE actor=? AND id=?', (actor, str(notice))).fetchone()
        if not row:
            raise HTTPException(404, 'unavailable')
        facts = await self.dependency(self.catalog, row['seller'], row['watch'])
        if not facts or facts.get('public') is not True or facts.get('seller_id') != row['seller'] or facts.get('watch_id') != row['watch']:
            raise HTTPException(404, 'unavailable')
        return dict(url='/watches/' + str(UUID(row['watch'])))

    async def status(self, token, seller):
        actor = await self.authorize(token)
        seller = str(UUID(str(seller)))
        with self.connect() as db:
            row = db.execute('SELECT * FROM follows WHERE actor=? AND seller=?', (actor, seller)).fetchone()
            return self.result(row) if row else dict(seller_id=seller, following=False, alerts_enabled=False, revision=0)
