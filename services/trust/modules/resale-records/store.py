"""Durable privacy-safe history and idempotent transfer receipts."""
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from dataclasses import asdict

class Unavailable(Exception):
    pass

class MissingProvider:
    @contextmanager
    def locked_facts(self, command, timeout_seconds):
        raise Unavailable()
        yield


def instant(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        raise ValueError('utc_required')
    return datetime.fromisoformat(value[:-1] + '+00:00')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


class Store:
    def __init__(self, path, provider=None, *, responsible_operator):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', responsible_operator):
            raise ValueError('responsible_operator_required')
        self.responsible_operator = responsible_operator
        self.path = path
        self.provider = provider or MissingProvider()
        with self.connect() as db:
            for migration in sorted((Path(__file__).parent/'migrations').glob('L24_*.sql')):
                db.executescript(migration.read_text())

    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def result(self, c, state, now, revision=None):
        pending = state == 'pending'
        started = now
        operator = self.responsible_operator
        if pending:
            with self.connect() as db:
                receipt=db.execute('SELECT started_at,responsible_operator FROM l24_requests WHERE operation=?',(c.operation_id,)).fetchone()
            if receipt:
                started,operator=instant(receipt[0]),receipt[1]
        due=lambda hours: (started+timedelta(hours=hours)).isoformat().replace('+00:00','Z')
        return dict(schema_version='resale-records.v1', operation_id=c.operation_id,
                    subject_id=c.subject_id, watch_id=c.watch_id, actor_id=c.actor_id,
                    organization_id=c.organization_id, expected_revision=c.expected_revision,
                    state=state, revision=revision, pending_reason='source_unavailable' if state=='pending' else None,
                    next_actor=operator if pending else 'requester',
                    next_review_at=due(24) if pending else None,
                    escalation_at=due(48) if pending else None)

    def retain_result(self, db, c, state, now, revision=None):
        result = self.result(c, state, now, revision)
        db.execute('INSERT OR IGNORE INTO l24_outcomes VALUES (?,?)',
                   (c.operation_id, encoded(result)))
        return result

    def transfer(self, c, now):
        if now.tzinfo != timezone.utc:
            raise ValueError('utc_required')
        values = asdict(c)
        for name, value in values.items():
            if name.endswith('revision'):
                if type(value) is not int or not 0 <= value <= 2**31-1:
                    raise ValueError('invalid_revision')
            elif not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value):
                raise ValueError('invalid_reference')
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                old_request=db.execute('SELECT binding FROM l24_requests WHERE operation=?',(c.operation_id,)).fetchone()
                if old_request and old_request[0]!=encoded(values):
                    return self.result(c,'conflict',now)
                db.execute('INSERT OR IGNORE INTO l24_requests VALUES (?,?,?,?)',
                           (c.operation_id,encoded(values),now.isoformat().replace('+00:00','Z'),self.responsible_operator))
            with self.provider.locked_facts(c, timeout_seconds=2) as f:
                if not all((f.current_authority, f.seller_owns_record, f.recipient_authorized)):
                    with self.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        return self.retain_result(db,c,'denied',now)
                if any(getattr(c,k)!=getattr(f,k) for k in ('actor_id','organization_id','subject_id','watch_id','sale_id')):
                    with self.connect() as db:
                        db.execute('BEGIN IMMEDIATE')
                        return self.retain_result(db,c,'denied',now)
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    old = db.execute('SELECT binding,result FROM l24_transfers WHERE operation=?',(c.operation_id,)).fetchone()
                    if old:
                        return json.loads(old[1]) if old[0]==encoded(values) else self.result(c,'conflict',now)
                    outcome = db.execute('SELECT result FROM l24_outcomes WHERE operation=?',(c.operation_id,)).fetchone()
                    if outcome:
                        return json.loads(outcome[0])
                    if any(getattr(c,k)!=getattr(f,k) for k in ('source_revision','quote_revision','policy_revision')) or c.expected_revision != f.revision:
                        return self.retain_result(db,c,'stale',now)
                    if not all((f.released,f.prior_signature_valid,f.independent_pass,f.actual_custody,f.commitment_matches)):
                        return self.retain_result(db,c,'denied',now)
                    if instant(f.released_at)>now or instant(f.inspected_at)>instant(f.released_at):
                        return self.retain_result(db,c,'denied',now)
                    if not re.fullmatch('[a-f0-9]{64}',f.prior_hash):
                        return self.retain_result(db,c,'denied',now)
                    current = db.execute('SELECT MAX(revision) FROM l24_history WHERE watch=?',(c.watch_id,)).fetchone()[0]
                    if db.execute('SELECT 1 FROM l24_transfers WHERE sale=?',(c.sale_id,)).fetchone():
                        return self.retain_result(db,c,'duplicate',now)
                    if current is not None and current != c.expected_revision:
                        return self.retain_result(db,c,'stale',now)
                    revision = c.expected_revision+1
                    summary = dict(issuer=f.issuer,inspected_at=f.inspected_at,scope=f.scope,
                                   watch_reference=f.public_watch_reference,signed_record_hash=f.prior_hash,prior_hash=f.prior_hash,revision=revision,
                                   qualification='historical' if f.current_watch_revision!=f.inspected_watch_revision or now>=instant(f.inspection_valid_until) else 'prior_independent_inspection')
                    if current is not None:
                        prior=json.loads(db.execute('SELECT summary FROM l24_history WHERE watch=? AND revision=?',(c.watch_id,current)).fetchone()[0])
                        summary['prior_hash']=prior['hash']
                    summary['hash']=hashlib.sha256(encoded(summary).encode()).hexdigest()
                    result=self.retain_result(db,c,'transferred',now,revision)
                    db.execute('INSERT INTO l24_history VALUES (?,?,?)',(c.watch_id,revision,encoded(summary)))
                    db.execute('INSERT INTO l24_transfers VALUES (?,?,?,?,?,?,?,?)',(c.operation_id,encoded(values),c.actor_id,c.organization_id,c.subject_id,c.watch_id,c.sale_id,encoded(result)))
                    db.execute('INSERT INTO l24_outbox(event,payload) VALUES (?,?)',(c.operation_id,encoded(summary)))
                    return result
        except (Unavailable, TimeoutError):
            return self.result(c,'pending',now)
        except sqlite3.OperationalError:
            raise Unavailable('receipt_store_unavailable') from None

    def lookup(self, operation_id, access):
        if not access.allowed:
            return None
        try:
            with self.connect() as db:
                row=db.execute('SELECT actor,organization,subject,watch,result,binding FROM l24_transfers WHERE operation=?',(operation_id,)).fetchone()
                if not row:
                    request=db.execute('SELECT r.binding,o.result FROM l24_requests r LEFT JOIN l24_outcomes o ON o.operation=r.operation WHERE r.operation=?',(operation_id,)).fetchone()
                    if request:
                        binding=json.loads(request[0])
                        row=tuple(binding[key] for key in ('actor_id','organization_id','subject_id','watch_id'))+(request[1],request[0])
            if not row or tuple(row[:4])!=(access.actor_id,access.organization_id,access.subject_id,access.watch_id):
                return None
            command=SimpleNamespace(**json.loads(row[5]))
            with self.provider.locked_facts(command, timeout_seconds=2) as facts:
                if not facts.current_authority or any(getattr(command,key)!=getattr(facts,key) for key in ('actor_id','organization_id','subject_id','watch_id','sale_id')):
                    return None
                return json.loads(row[4]) if row[4] else self.result(command,'pending',datetime.now(timezone.utc))
        except (Unavailable, TimeoutError, sqlite3.OperationalError):
            return None
