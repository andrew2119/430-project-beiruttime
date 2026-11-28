"""Atomic provider boundary. Uncertain calls always resolve by the same reference."""
import asyncio
from bt_contracts.orders.cancellations.v1 import Facts
from .policy import decide


class Denied(Exception):
    pass


class Conflict(Exception):
    pass


class Unavailable(Exception):
    pass


async def execute(provider, command, principal, now):
    if provider is None:
        raise Unavailable()
    try:
        async with asyncio.timeout(5):
            async with provider.transaction(command, principal) as tx:
                if principal.actor.organization_id != command.organization_id or not await tx.authorized(command.action):
                    raise Denied()
                old = await tx.receipt(command.operation_id)
                if old:
                    if old['command'] != command.model_dump(mode='json') or old['actor_id'] != str(principal.actor.subject_id):
                        raise Conflict()
                    return old['result']
                facts = Facts.model_validate(tx.facts)
                result = decide(command, facts, principal.actor.subject_id, now)
                await tx.apply(result)
                await tx.save(command, principal, result)
                return result
    except TimeoutError:
        raise Unavailable() from None


async def lookup(provider, subject_id, operation_id, principal):
    if provider is None:
        raise Unavailable()
    try:
        async with asyncio.timeout(5):
            result = await provider.lookup(subject_id, operation_id, principal)
            if result is None:
                raise Unavailable()
            return result
    except TimeoutError:
        raise Unavailable() from None
