"""Transaction-local receipt handling for business v2 commands."""
import hashlib
import json


class ReceiptConflict(ValueError):
    pass


async def execute(tx, command, *, authorize, apply):
    """The caller owns one transaction encompassing authority, mutation and outbox.

    authorize reloads current authority even on a retry. apply performs the
    domain transition, history and outbox writes on this same transaction.
    No network call or private evidence bytes belong in the command payload.
    """
    payload = command.model_dump(mode="json")
    actor_id = command.actor_id
    operation_id = command.operation_id
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    await tx.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
        "l20.business-command:" + str(actor_id) + ":" + str(operation_id),
    )
    await authorize(tx, command)
    receipt = await tx.fetchrow(
        "SELECT fingerprint,result FROM l20_business_command_receipts WHERE actor_id=$1 AND operation_id=$2",
        actor_id, operation_id,
    )
    if receipt:
        if receipt["fingerprint"] != fingerprint:
            raise ReceiptConflict("operation_conflict")
        result = receipt["result"]
        return json.loads(result) if isinstance(result, str) else result
    result = await apply(tx, command)
    await tx.execute(
        """INSERT INTO l20_business_command_receipts
        (actor_id,operation_id,subject_id,business_id,watch_id,expected_revision,fingerprint,result)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb)""",
        actor_id, operation_id, command.subject_id, command.organization_id,
        command.watch_id, command.expected_revision, fingerprint, json.dumps(result),
    )
    return result
