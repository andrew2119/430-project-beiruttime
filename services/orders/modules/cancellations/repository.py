"""Receipt persistence within the canonical provider's existing transaction."""
import json
from bt_contracts.orders.cancellations.v1 import Result


async def receipt(tx, operation_id):
    row = await tx.fetchrow('SELECT actor_id,command,result FROM l13_cancellation_receipts WHERE operation_id=$1', operation_id)
    if row is None:
        return None
    def decode(value):
        return json.loads(value) if isinstance(value, str) else value
    return dict(actor_id=str(row['actor_id']), command=decode(row['command']),
                result=Result.model_validate(decode(row['result'])))


async def save(tx, command, principal, facts, result):
    await tx.execute('''INSERT INTO l13_cancellation_receipts
        (operation_id,actor_id,organization_id,subject_id,watch_id,source_revision,
         quote_id,quote_revision,policy_revision,command,result)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb)''',
        command.operation_id, principal.actor.subject_id, command.organization_id,
        command.subject_id, command.watch_id, command.expected_revision,
        facts.quote_id, facts.quote_revision, facts.policy_revision,
        command.model_dump_json(), result.model_dump_json())
