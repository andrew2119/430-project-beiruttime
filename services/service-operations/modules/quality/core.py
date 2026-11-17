"""Private quality evaluation. Persistence callers supply fresh trusted source facts."""
import json
import sqlite3
from pathlib import Path
import importlib.util

_contract_path = Path(__file__).resolve().parents[4] / 'packages/contracts-service/quality/v1.py'
_spec = importlib.util.spec_from_file_location('quality_contract_v1', _contract_path)
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)


class Refused(ValueError):
    pass


def authorize(command, current, now):
    if not contract.current_matches(command, current, now):
        raise Refused('denied_or_stale_source')


def evaluate(command, current):
    if {line.line_id for line in command.lines} != current.required_line_ids:
        raise Refused('required_lines')
    if any({test.key for test in line.tests} != current.required_tests[line.line_id] for line in command.lines):
        raise Refused('required_tests')
    if not current.required_line_ids <= current.completed_line_ids:
        raise Refused('unfinished_work')
    if not (current.custody_current and current.payment_held and current.commitment_current
            and current.accepted_current) or current.incident_open:
        raise Refused('service_hold')
    return 'satisfactory' if all(check.satisfactory for line in command.lines
        for check in (*line.tests, line.condition, line.fit, line.returned_parts)) else 'rework'


class LocalStore:
    """Durable isolated adapter; runtime composition supplies the production repository."""
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=1, isolation_level=None)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS quality_records (
            organization TEXT NOT NULL, job TEXT NOT NULL, revision INTEGER NOT NULL,
            command TEXT NOT NULL, receipt TEXT NOT NULL, PRIMARY KEY(organization,job));
          CREATE TABLE IF NOT EXISTS quality_operations (
            operation TEXT PRIMARY KEY, organization TEXT NOT NULL, job TEXT NOT NULL,
            actor TEXT NOT NULL, command TEXT NOT NULL, receipt TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS quality_outbox (
            operation TEXT PRIMARY KEY, payload TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def record(self, command, current, now):
        authorize(command, current, now)
        raw = command.model_dump_json()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            prior = self.db.execute('SELECT command,receipt FROM quality_operations WHERE operation=?',
                                    (str(command.operation_id),)).fetchone()
            if prior:
                if prior[0] != raw:
                    raise Refused('operation_conflict')
                result = json.loads(prior[1])
            else:
                row = self.db.execute('SELECT revision,command,receipt FROM quality_records WHERE organization=? AND job=?',
                                      (str(command.organization_id), str(command.job_id))).fetchone()
                revision = row[0] if row else 0
                if command.expected_revision != revision:
                    raise Refused('stale_revision')
                if row and json.loads(row[2])['state'] == 'rework':
                    previous = contract.Record.model_validate_json(row[1])
                    if command.work_revision <= previous.work_revision:
                        raise Refused('new_work_required')
                state = evaluate(command, current)
                result = {key: str(getattr(command, key)) for key in
                          ('operation_id', 'job_id', 'watch_id', 'actor_id', 'organization_id', 'quote_id')}
                result.update(schema_version='quality.v1', state=state, revision=revision + 1,
                              subject_id=str(command.job_id), expected_revision=command.expected_revision,
                              quote_revision=command.quote_revision, policy_revision=command.policy_revision,
                              scope_revision=command.scope_revision, work_revision=command.work_revision,
                              assignment_revision=command.assignment_revision, pending_reason=None,
                              next_actor='business', next_review_at=None)
                encoded = json.dumps(result, sort_keys=True)
                self.db.execute('INSERT OR REPLACE INTO quality_records VALUES(?,?,?,?,?)',
                                (str(command.organization_id), str(command.job_id), revision + 1, raw, encoded))
                self.db.execute('INSERT INTO quality_operations VALUES(?,?,?,?,?,?)',
                                (str(command.operation_id), str(command.organization_id), str(command.job_id),
                                 str(command.actor_id), raw, encoded))
                event = {key: result[key] for key in ('schema_version', 'operation_id', 'job_id', 'revision', 'state')}
                self.db.execute('INSERT INTO quality_outbox VALUES(?,?)', (str(command.operation_id), json.dumps(event)))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def operation(self, operation_id, current, now):
        row = self.db.execute('SELECT command,receipt FROM quality_operations WHERE operation=?',
                              (str(operation_id),)).fetchone()
        if row is None:
            raise Refused('unavailable')
        command = contract.Record.model_validate_json(row[0])
        authorize(command, current, now)
        return json.loads(row[1])

    def handover(self, command, current, now):
        authorize(command, current, now)
        row = self.db.execute('SELECT command,receipt FROM quality_records WHERE organization=? AND job=?',
                              (str(command.organization_id), str(command.job_id))).fetchone()
        if not row:
            return False
        saved = contract.Record.model_validate_json(row[0])
        authorize(saved, current, now)
        return evaluate(saved, current) == 'satisfactory' and json.loads(row[1])['state'] == 'satisfactory'
