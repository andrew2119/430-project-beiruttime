"""Transaction-local repository. The caller owns the database transaction."""
import json


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


class Store:
    def __init__(self, tx):
        self.tx = tx

    async def lock(self, subject_id, operation_id):
        # Stable ordering serializes duplicate operations even across different jobs.
        for key in (f'progress-operation:{operation_id}', f'progress-job:{subject_id}'):
            await self.tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key)

    async def job(self, subject_id):
        row = await self.tx.fetchrow('SELECT revision,reports FROM service_progress_jobs WHERE subject_id=$1', subject_id)
        return (row['revision'], decoded(row['reports'])) if row else (0, {})

    async def receipt(self, operation_id):
        row = await self.tx.fetchrow('SELECT * FROM service_progress_operations WHERE operation_id=$1', operation_id)
        return dict(row) if row else None

    async def save(self, command, access, report, reports, result, digest):
        revision = result['revision']
        await self.tx.execute('''INSERT INTO service_progress_jobs(subject_id,revision,reports) VALUES($1,$2,$3::jsonb)
            ON CONFLICT(subject_id) DO UPDATE SET revision=$2,reports=$3::jsonb''',
                              command.subject_id, revision, json.dumps(reports))
        await self.tx.execute('''INSERT INTO service_progress_operations
            (operation_id,actor_id,organization_id,subject_id,request_hash,result) VALUES($1,$2,$3,$4,$5,$6::jsonb)''',
                              command.operation_id, access.actor_id, command.organization_id,
                              command.subject_id, digest, json.dumps(result))
        await self.tx.execute('''INSERT INTO service_progress_history
            (subject_id,revision,actor_id,operation_id,report) VALUES($1,$2,$3,$4,$5::jsonb)''',
                              command.subject_id, revision, access.actor_id, command.operation_id, json.dumps(report))
        event = dict(subject_id=str(command.subject_id), watch_id=str(command.watch_id),
                     organization_id=str(command.organization_id), revision=revision, operation_id=str(command.operation_id))
        await self.tx.execute('''INSERT INTO service_progress_outbox(operation_id,event_type,payload)
            VALUES($1,'service.progress.reported.v1',$2::jsonb)''', command.operation_id, json.dumps(event))
