"""Extend existing payment fixtures with the current transaction/read contract.

Load with pytest's -p option when running the original unit checks. Their assertions
remain unchanged; unrecognized queries still fail in the original strict stub.
"""

from contextlib import asynccontextmanager

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    outcome = yield
    if fixturedef.argname == 'payment_processor':
        _, tx, order, attempt, state, _, _ = outcome.get_result()
        fetchval, fetchrow, execute = tx.fetchval, tx.fetchrow, tx.execute
        state['reconciliations'] = []

        async def current_value(sql, *args):
            if sql.startswith('SELECT operator_id FROM l13_payment_recovery_assignments'):
                return attempt['id']
            if sql.startswith('SELECT 1 FROM l13_money_reconciliations') or sql.lstrip().startswith('SELECT EXISTS'):
                return bool(state['reconciliations'])
            return await fetchval(sql, *args)

        async def current_row(sql, *args):
            if "UPDATE l13_payment_attempts SET state='held'" in sql:
                attempt.update(state='held', sequence=max(attempt['sequence'], args[1]))
                return attempt
            return await fetchrow(sql, *args)

        async def current_execute(sql, *args):
            if 'INSERT INTO l13_money_reconciliations' in sql:
                state['reconciliations'].append(args)
            elif sql.startswith('UPDATE l08_orders SET financial_revision'):
                order['financial_revision'] = order.get('financial_revision', 0) + 1
            else:
                return await execute(sql, *args)

        tx.fetchval, tx.fetchrow, tx.execute = current_value, current_row, current_execute
    elif fixturedef.argname == 'checkout_route':
        _, request_value, _, _, _, _ = outcome.get_result()
        pool = request_value.app.state.pool
        tx = pool.isolated_tx
        acquire, fetch = pool.acquire, tx.fetch

        @asynccontextmanager
        async def bounded_acquire(*, timeout):
            assert timeout == 2
            async with acquire() as connection:
                yield connection

        @asynccontextmanager
        async def transaction(*, isolation):
            assert isolation == 'read_committed'
            yield

        async def current_rows(sql, *args):
            if sql.startswith('SELECT * FROM l13_money_operations'):
                return []
            return await fetch(sql, *args)

        pool.acquire, tx.transaction, tx.fetch = bounded_acquire, transaction, current_rows
