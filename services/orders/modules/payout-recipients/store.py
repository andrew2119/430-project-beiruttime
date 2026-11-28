"""Durable private recipient versions and immutable transfer bindings."""
import json
import sqlite3
from threading import RLock
from contextlib import contextmanager

class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=2, isolation_level=None, check_same_thread=False)
        self.lock = RLock()
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS recipients(scope TEXT, revision INTEGER, body TEXT,
          PRIMARY KEY(scope,revision));
        CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, scope TEXT, actor TEXT,
          request TEXT, result TEXT);
        CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY, scope TEXT, revision INTEGER);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor TEXT, scope TEXT, decision TEXT);
        CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, body TEXT);
        ''')

    @contextmanager
    def transaction(self):
        if not self.lock.acquire(timeout=2):
            raise TimeoutError('recipient_store_busy')
        try:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise
        finally:
            self.lock.release()

    def decision(self, actor, scope, code):
        self.db.execute('INSERT INTO audit(actor,scope,decision) VALUES(?,?,?)', (actor,scope,code))

    def current(self, scope):
        row = self.db.execute('SELECT revision,body FROM recipients WHERE scope=? ORDER BY revision DESC LIMIT 1', (scope,)).fetchone()
        return {'revision':row[0], **json.loads(row[1])} if row else {'revision':0}

    def bind_transfer(self, transfer_id, scope, revision):
        # Internal journal boundary: never a customer-facing command.
        with self.transaction():
            old = self.db.execute('SELECT scope,revision FROM transfers WHERE id=?', (transfer_id,)).fetchone()
            if old:
                if old != (scope, revision):
                    raise ValueError('transfer_binding_conflict')
                return revision
            if not self.db.execute('SELECT 1 FROM recipients WHERE scope=? AND revision=?', (scope,revision)).fetchone():
                raise ValueError('recipient_version_unknown')
            self.db.execute('INSERT INTO transfers VALUES(?,?,?)', (transfer_id,scope,revision))
            return revision
