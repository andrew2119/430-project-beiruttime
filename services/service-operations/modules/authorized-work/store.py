"""Durable private operation store with a reconciled incident pause."""
import asyncio
import importlib.util
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import timedelta

# Composition supplies the versioned contract rather than importing another service.
def load_contract(path):
    spec = importlib.util.spec_from_file_location('work_contract_v1', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class Rejected(Exception):
    def __init__(self, code, not_applied=False):
        super().__init__(code)
        self.not_applied = not_applied

class Store:
    def __init__(self, path, provider, contract):
        self.path, self.provider, self.contract = path, provider, contract
        with self.connect() as db:
            db.executescript((Path(__file__).parent / 'migrations' / 'L19_0001_authorized_work.sql').read_text())

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def reject_before_write(self, db, operation, body, reason):
        db.execute('INSERT INTO l19_work_rejections VALUES (?,?,?)', (operation, body, reason))
        db.commit()
        raise Rejected(reason, not_applied=True)

    async def authority(self, command, actor, organization, now):
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise Rejected('invalid_time')
        if (command.actor_id, command.organization_id) != (actor, organization):
            raise Rejected('denied')
        try:
            if command.kind in ('loss', 'damage'):
                value = await asyncio.wait_for(
                    self.provider.context(command.subject_id, actor, organization, now), 2)
            else:
                value = await asyncio.wait_for(self.provider.authorize(command, actor, organization, now), 2)
            auth = self.contract.Authority.model_validate(value)
        except Exception:
            raise Rejected('unavailable') from None
        for name in ('actor_id', 'organization_id', 'subject_id', 'watch_id', 'source_revision',
                     'quote_id', 'quote_revision', 'policy_revision'):
            if getattr(auth, name) != getattr(command, name):
                raise Rejected('stale')
        if auth.valid_until <= now or auth.state == 'denied':
            raise Rejected('denied')
        if command.kind in ('loss', 'damage'):
            pass
        elif command.kind == 'declined_return':
            if auth.state != 'declined':
                raise Rejected('denied')
        elif auth.state != 'authorized' or auth.payment_state != 'paid_held':
            raise Rejected('denied')
        if command.next_actor != auth.responsible_actor_id:
            raise Rejected('responsible_actor')
        accepted = set(auth.accepted_line_ids)
        if not set(command.line_ids) <= accepted or any(p.line_id not in accepted for p in command.parts):
            raise Rejected('unaccepted_line')
        if command.kind == 'progress' and not command.line_ids:
            raise Rejected('missing_line')
        if command.kind != 'progress' and (command.parts or command.readings or command.line_ids):
            raise Rejected('unexpected_work')
        if not command.note.strip() or not command.next_action.strip():
            raise Rejected('missing_action')
        if command.observed_at > now or any(r.observed_at > now for r in command.readings):
            raise Rejected('future_observation')
        return auth

    async def context(self, subject, actor, organization, now):
        try:
            raw = await asyncio.wait_for(self.provider.context(subject, actor, organization, now), 2)
            auth = self.contract.Authority.model_validate(raw)
        except Exception:
            raise Rejected('unavailable') from None
        if (auth.subject_id, auth.actor_id, auth.organization_id) != (subject, actor, organization):
            raise Rejected('denied')
        if auth.valid_until <= now or auth.state == 'denied':
            raise Rejected('denied')
        with self.connect() as db:
            job = db.execute('SELECT revision FROM l19_work_jobs WHERE subject=?', (str(subject),)).fetchone()
        fields = ('subject_id','watch_id','actor_id','organization_id','source_revision',
                  'quote_id','quote_revision','policy_revision')
        return {**{name:str(getattr(auth,name)) if name.endswith('_id') else getattr(auth,name) for name in fields},
                'responsible_actor_id':str(auth.responsible_actor_id), 'expected_revision':job['revision'] if job else 0, 'server_now':now.isoformat(),
                'accepted_lines':[{'id':str(line),'label':str(line)} for line in auth.accepted_line_ids]}

    async def execute(self, command, actor, organization, now):
        encoded = command.model_dump_json()
        with self.connect() as db:
            retained = db.execute('SELECT * FROM l19_work_operations WHERE operation=?',
                                  (str(command.operation_id),)).fetchone()
        reconcile = retained is not None and command.kind in ('loss', 'damage', 'material_change')
        try:
            if reconcile:
                if (command.actor_id, command.organization_id) != (actor, organization):
                    raise Rejected('denied')
                current = await self.context(command.subject_id, actor, organization, now)
                if current['watch_id'] != str(command.watch_id):
                    raise Rejected('denied')
                if retained['body'] != encoded:
                    raise Rejected('duplicate_conflict')
            else:
                await self.authority(command, actor, organization, now)
        except Rejected as error:
            if str(error) in ('responsible_actor', 'stale', 'unaccepted_line', 'missing_line', 'unexpected_work', 'missing_action', 'future_observation'):
                encoded = command.model_dump_json()
                op = str(command.operation_id)
                with self.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    existing = db.execute('SELECT 1 FROM l19_work_operations WHERE operation=?', (op,)).fetchone()
                    rejected = db.execute('SELECT * FROM l19_work_rejections WHERE operation=?', (op,)).fetchone()
                    if not existing and not rejected:
                        self.reject_before_write(db, op, encoded, str(error))
                    if rejected and rejected['body'] == encoded:
                        raise Rejected(rejected['reason'], not_applied=True) from None
            raise
        encoded = command.model_dump_json()
        op, subject = str(command.operation_id), str(command.subject_id)
        hold = command.kind in ('loss', 'damage', 'material_change')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT * FROM l19_work_operations WHERE operation=?', (op,)).fetchone()
            if previous:
                if previous['body'] != encoded:
                    raise Rejected('duplicate_conflict')
                result = json.loads(previous['result'])
            else:
                rejected = db.execute('SELECT * FROM l19_work_rejections WHERE operation=?', (op,)).fetchone()
                if rejected:
                    if rejected['body'] != encoded:
                        raise Rejected('duplicate_conflict')
                    raise Rejected(rejected['reason'], not_applied=True)
                if not now < command.next_review_at <= now + timedelta(hours=24):
                    self.reject_before_write(db, op, encoded, 'review_due')
                job = db.execute('SELECT * FROM l19_work_jobs WHERE subject=?', (subject,)).fetchone()
                revision = job['revision'] if job else 0
                if command.expected_revision != revision:
                    self.reject_before_write(db, op, encoded, 'stale')
                if job and job['paused'] and not hold:
                    self.reject_before_write(db, op, encoded, 'paused')
                revision += 1
                state = 'pending' if hold else ('recorded' if command.kind == 'progress' else 'paused')
                result = dict(schema_version='authorized-work.v1', operation_id=op, subject_id=subject,
                    watch_id=str(command.watch_id), actor_id=str(actor), organization_id=str(organization),
                    expected_revision=command.expected_revision, state=state, revision=revision,
                    pending_reason='orders_hold' if hold else None, next_actor=str(command.next_actor),
                    next_review_at=command.next_review_at.isoformat(), release_eligible=False, recorded_at=now.isoformat(), since=now.isoformat(),
                    escalation_at=(now+timedelta(hours=48)).isoformat(),
                    source_revision=command.source_revision, quote_id=str(command.quote_id),
                    quote_revision=command.quote_revision, policy_revision=command.policy_revision)
                db.execute('INSERT INTO l19_work_jobs VALUES (?,?,?) ON CONFLICT(subject) DO UPDATE SET revision=excluded.revision, paused=excluded.paused',
                    (subject, revision, int(hold or command.kind == 'declined_return')))
                db.execute('INSERT INTO l19_work_operations VALUES (?,?,?,?,?,?)',
                    (op, subject, str(actor), str(organization), encoded, json.dumps(result)))
        if hold and result['state'] == 'pending' and result['pending_reason'] != 'hold_conflict':
            try:
                raw = await asyncio.wait_for(self.provider.hold(command), 2)
                receipt = self.contract.HoldReceipt.model_validate(raw)
                for name in ('operation_id', 'subject_id', 'watch_id', 'source_revision', 'actor_id', 'organization_id', 'quote_id', 'quote_revision', 'policy_revision'):
                    if getattr(receipt, name) != getattr(command, name):
                        raise ValueError('scope')
            except Exception:
                return result
            result = {**result, 'state': 'paused', 'pending_reason': None, 'hold_revision': receipt.hold_revision}
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                retained = json.loads(db.execute('SELECT result FROM l19_work_operations WHERE operation=?', (op,)).fetchone()[0])
                if retained['state'] == 'paused':
                    if retained.get('hold_revision') == receipt.hold_revision:
                        return retained
                    result = {**retained, 'state':'pending', 'pending_reason':'hold_conflict'}
                elif retained.get('pending_reason') == 'hold_conflict':
                    return retained
                db.execute('UPDATE l19_work_operations SET result=? WHERE operation=?', (json.dumps(result), op))
        return result

    async def lookup(self, operation, actor, organization, now):
        with self.connect() as db:
            row = db.execute('SELECT * FROM l19_work_operations WHERE operation=? AND actor=? AND organization=?',
                (str(operation), str(actor), str(organization))).fetchone()
        if not row:
            raise Rejected('denied')
        command = self.contract.Command.model_validate_json(row['body'])
        context = await self.context(command.subject_id, actor, organization, now)
        if context['watch_id'] != str(command.watch_id):
            raise Rejected('denied')
        return json.loads(row['result'])

    async def observations(self, command, actor, organization, now, offset=0):
        auth = await self.authority(command, actor, organization, now)
        return self._observations(auth, organization, offset)

    async def history(self, subject, actor, organization, now, offset=0):
        await self.context(subject, actor, organization, now)
        try:
            raw = await asyncio.wait_for(self.provider.context(subject, actor, organization, now), 2)
            auth = self.contract.Authority.model_validate(raw)
        except Exception:
            raise Rejected('unavailable') from None
        if (auth.subject_id, auth.actor_id, auth.organization_id) != (subject, actor, organization) or auth.state == 'denied' or auth.valid_until <= now:
            raise Rejected('denied')
        return self._observations(auth, organization, offset)

    def _observations(self, command, organization, offset):
        if type(offset) is not int or offset < 0:
            raise Rejected('invalid_page')
        values = (str(command.subject_id), str(organization), str(command.watch_id))
        with self.connect() as db:
            total = db.execute("SELECT count(*) FROM l19_work_operations WHERE subject=? AND organization=? AND json_extract(body, '$.watch_id')=?", values).fetchone()[0]
            offset = min(offset, total)
            rows = db.execute("SELECT body FROM l19_work_operations WHERE subject=? AND organization=? AND json_extract(body, '$.watch_id')=? ORDER BY rowid LIMIT 50 OFFSET ?",
                (*values, offset)).fetchall()
            completed_rows = db.execute("""SELECT DISTINCT line.value FROM l19_work_operations,
                json_each(body, '$.line_ids') AS line WHERE subject=? AND organization=?
                AND json_extract(body, '$.watch_id')=?
                AND json_extract(body, '$.kind')='progress'
                AND json_extract(body, '$.source_revision')=?
                AND json_extract(body, '$.quote_id')=?
                AND json_extract(body, '$.quote_revision')=?
                AND json_extract(body, '$.policy_revision')=?""",
                (*values, command.source_revision, str(command.quote_id), command.quote_revision, command.policy_revision)).fetchall()
        bodies = [json.loads(row['body']) for row in rows]
        completed = {row[0] for row in completed_rows}
        return dict(items=bodies, total=total, next_offset=offset+50 if offset+50 < total else None,
                    complete=set(map(str, command.required_line_ids)) <= completed, release_eligible=False)
