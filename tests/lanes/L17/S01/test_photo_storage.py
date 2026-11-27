"""Private upload lifecycle against a disposable service database."""
import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from uuid import uuid4

import asyncpg
from fastapi import HTTPException
from PIL import Image
from bt_contracts.service.maintenance.v1 import DeliveryRecoveryCommand, Photo, Request
from bt_contracts_core.errors import PublicError
from bt_runtime.modules import discover

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / 'services/service-operations/modules/maintenance-requests'
intake, = discover(MODULE.parent / 'intake')
manifest, = discover(MODULE)
MIGRATIONS = intake.migrations + manifest.migrations
photos = sys.modules[manifest.load('photos.py:store_photo').__module__]
claim_batch = manifest.load('delivery.py:claim_batch')
deliver = manifest.load('delivery.py:deliver')
held_deliveries = manifest.load('routes.py:held_deliveries')
retry_delivery = manifest.load('routes.py:retry_delivery')
assessment_inbox = manifest.load('routes.py:assessment_inbox')
submit = manifest.load('commands.py:submit')


class ExpiryRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_retries_failed_acquisition_and_statement(self):
        stop = asyncio.Event()
        attempts = 0
        delays = []

        class Transaction:
            async def execute(self, statement):
                if attempts == 2:
                    raise asyncpg.ConnectionDoesNotExistError('Synthetic statement failure')
                self.expired_bytes = None

        tx = Transaction()
        tx.expired_bytes = b'test-overdue-photo'

        @asynccontextmanager
        async def transaction(pool):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError('Synthetic acquisition timeout')
            yield tx

        async def wait_for(wait, *, timeout):
            wait.close()
            delays.append(timeout)
            if len(delays) < 3:
                self.assertIsNotNone(tx.expired_bytes)
                raise TimeoutError
            stop.set()

        app = SimpleNamespace(state=SimpleNamespace(pool=None))
        with patch.multiple(photos, unit_of_work=transaction,
                            asyncio=SimpleNamespace(wait_for=wait_for)):
            await photos.run_expiry(app, stop)
        self.assertEqual(attempts, 3)
        self.assertEqual(delays, [3, 3, 60])
        self.assertIsNone(tx.expired_bytes)


class RequeueRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_requeue_checks_escalation_under_the_locked_hold_before_reset(self):
        event, operator = uuid4(), uuid4()
        held_at = datetime(2026, 11, 16, tzinfo=timezone.utc)
        calls = []
        receipts = set()

        class Transaction:
            async def fetchval(self, sql, *args):
                if sql == 'SELECT clock_timestamp()':
                    return datetime.now(timezone.utc)
                self_test.assertEqual(args, (event, operator, held_at))
                if 'maintenance_delivery_retry_receipts' in sql:
                    calls.append('lookup')
                    return args in receipts
                if 'FOR UPDATE' in sql:
                    calls.append('lock')
                else:
                    self_test.assertIn('held_at = NULL', sql)
                    calls.append('reset')
                return event

            async def execute(self, sql, *args):
                if 'transaction_timeout' in sql:
                    return
                if 'maintenance_delivery_responses' in sql:
                    calls.append('response')
                elif 'maintenance_delivery_retry_receipts' in sql:
                    self_test.assertEqual(args, (event, operator, held_at))
                    receipts.add(args)
                    calls.append('receipt')
                else:
                    self_test.assertIn("escalation_started_at <= statement_timestamp() - interval '48 hours'", sql)
                    self_test.assertIn('escalated_at IS NULL AND event_id = $2', sql)
                    self_test.assertIn('INSERT INTO maintenance_delivery_escalations', sql)
                    self_test.assertEqual(args, (operator, event))
                    calls.append('escalation')

        self_test = self

        @asynccontextmanager
        async def transaction(pool, *, lock_key):
            self.assertEqual(lock_key, f'maintenance:{event}')
            yield Transaction()

        async def access(actor_id):
            return datetime.now(timezone.utc)+timedelta(seconds=5) if actor_id == operator else None

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            pool=None, maintenance_delivery_operator_id=operator,
            maintenance_provider=SimpleNamespace(delivery_authority_until=access))))
        routes = sys.modules[retry_delivery.__module__]
        with patch.object(routes, 'unit_of_work', transaction):
            first = DeliveryRecoveryCommand(held_at=held_at)
            await retry_delivery(event, first, request, operator)
            held_at += timedelta(hours=1)
            await retry_delivery(event, DeliveryRecoveryCommand(held_at=held_at), request, operator)
            held_at = first.held_at
            await retry_delivery(event, first, request, operator)
        self.assertEqual(calls, ['lookup', 'lock', 'response', 'escalation', 'reset', 'receipt'] * 2 + ['lookup'])


    async def test_review_replays_only_its_recorded_hold_after_delivery_transitions(self):
        event, operator, successor = uuid4(), uuid4(), uuid4()
        origin = datetime(2026, 11, 16, tzinfo=timezone.utc)
        requeued = origin + timedelta(hours=48)
        row = {'held_at': None, 'delivered_at': None,
               'last_requeued_hold_at': requeued, 'escalation_started_at': origin}
        recorded = None
        writes = []

        class Transaction:
            async def fetchrow(self, sql, event_id):
                test.assertIn('FOR UPDATE', sql)
                test.assertEqual(event_id, event)
                return row

            async def execute(self, sql, *args):
                assert 'transaction_timeout' in sql

            async def fetchval(self, sql, *args):
                nonlocal recorded
                if sql == 'SELECT clock_timestamp()':
                    return datetime.now(timezone.utc)
                if 'UPDATE' in sql:
                    test.assertIn('reviewed_at IS NULL', sql)
                    test.assertEqual(args, (event, origin, operator, requeued))
                    writes.append(args)
                    if recorded is None:
                        recorded = (event, requeued, operator)
                        return event
                    return None
                test.assertIn('reviewed_hold_at = $2 AND reviewed_by = $3', sql)
                return args == recorded

        test = self

        @asynccontextmanager
        async def transaction(pool, *, lock_key):
            self.assertEqual(lock_key, f'maintenance:{event}')
            yield Transaction()

        async def allowed(actor_id):
            return datetime.now(timezone.utc)+timedelta(seconds=5)

        state = SimpleNamespace(pool=None, maintenance_delivery_operator_id=operator,
                                maintenance_provider=SimpleNamespace(delivery_authority_until=allowed))
        request = SimpleNamespace(app=SimpleNamespace(state=state))
        command = DeliveryRecoveryCommand(held_at=requeued, action='review_escalation')
        routes = sys.modules[retry_delivery.__module__]
        with patch.object(routes, 'unit_of_work', transaction):
            await retry_delivery(event, command, request, operator)
            for facts in ({'delivered_at': requeued + timedelta(hours=1)},
                          {'delivered_at': None, 'held_at': requeued + timedelta(hours=1)}):
                row.update(facts)
                snapshot = row.copy()
                await retry_delivery(event, command, request, operator)
                self.assertEqual(row, snapshot)
            for binding, actor, status in (
                (command.model_copy(update={'held_at': origin}), operator, 409),
                (command, successor, 409),
            ):
                state.maintenance_delivery_operator_id = actor
                with self.assertRaises(PublicError) as stale:
                    await retry_delivery(event, binding, request, actor)
                self.assertEqual(stale.exception.status, status)
            with self.assertRaises(HTTPException) as denied:
                await retry_delivery(event, command, request, operator)
            self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(len(writes), 1)


@unittest.skipUnless(os.getenv('BT_S01_TEST_DATABASE'), 'Requires a disposable service database')
class PhotoStorage(unittest.TestCase):
    def test_expiry_cleanup_and_immutable_upload_replay(self):
        asyncio.run(self.lifecycle())

    async def lifecycle(self):
        url = os.environ['BT_S01_TEST_DATABASE']
        schema = 'maintenance_test_' + uuid4().hex
        connection = await asyncpg.connect(url)

        async def use_schema(conn):
            await conn.execute(f'SET search_path TO {schema}')

        try:
            await connection.execute(f'CREATE SCHEMA {schema}')
            await use_schema(connection)
            for migration in MIGRATIONS:
                await connection.execute(migration.read_text())
            sample = BytesIO()
            Image.new('RGB', (2, 2)).save(sample, format='PNG')
            content = sample.getvalue()
            actor, organization, watch, operation, request_id, brand = (uuid4() for _ in range(6))

            def photo(key):
                return Photo(operation_id=key, request_operation_id=operation, watch_id=watch,
                             organization_id=organization, brand_id=brand, intervention='limited_maintenance',
                             watch_revision=1, capability_revision=1, policy_revision=1,
                             media_type='image/png', safe_photo_declared=True,
                             content_base64=base64.b64encode(content).decode('ascii'))

            first, second, third = (photo(uuid4()) for _ in range(3))
            async with connection.transaction():
                kept = await photos.store_photo(connection, actor, first, content)
                expired = await photos.store_photo(connection, actor, second, content)
                abandoned = await photos.store_photo(connection, actor, third, content)
                created = await connection.fetchval(
                    'SELECT uploaded_at FROM maintenance_request_photos WHERE photo_ref=$1', expired)
                self.assertEqual(await photos.store_photo(connection, actor, second, content), expired)
                self.assertEqual(await connection.fetchval(
                    'SELECT expires_at FROM maintenance_request_photos WHERE photo_ref=$1', expired),
                    created + timedelta(days=7))

                command = Request(operation_id=operation, subject_id=actor, actor_id=actor,
                                  watch_id=watch, organization_id=organization, expected_revision=0,
                                  watch_revision=1, capability_revision=1, policy_revision=1,
                                  brand_id=brand, intervention='limited_maintenance', reported_symptoms='Stopped',
                                  known_modifications='', photo_refs=[kept], limited_assessment_permission=True)
                await connection.execute('''INSERT INTO maintenance_requests
                    (id,operation_id,actor_id,organization_id,watch_id,private_request)
                    VALUES ($1,$2,$3,$4,$5,$6::jsonb)''',
                    request_id, operation, actor, organization, watch, command.model_dump_json())
                self.assertFalse(await photos.attach(connection,
                    command.model_copy(update={'watch_id': uuid4()}), request_id))
                for field, value in (
                    ('brand_id', uuid4()), ('intervention', 'overhaul_assessment'),
                    ('watch_revision', 2), ('capability_revision', 2), ('policy_revision', 2),
                ):
                    with self.subTest(field=field):
                        self.assertFalse(await photos.attach(connection,
                            command.model_copy(update={field: value}), request_id))
                self.assertTrue(await photos.attach(connection, command, request_id))
                await connection.execute('''UPDATE maintenance_request_photos
                    SET expires_at=clock_timestamp(), uploaded_at=clock_timestamp()-interval '7 days'
                    WHERE photo_ref=$1''', expired)
                self.assertFalse(await photos.attach(connection,
                    command.model_copy(update={'photo_refs': [expired]}), request_id))
                with self.assertRaises(PublicError) as unavailable:
                    await photos.store_photo(connection, actor, second, content)
                self.assertEqual(unavailable.exception.code, 'photo_expired')

            await connection.close()
            connection = await asyncpg.connect(url)
            await use_schema(connection)
            attempts = []
            delays = []
            stop = asyncio.Event()

            @asynccontextmanager
            async def expiry_transaction(pool):
                attempts.append(pool)
                if len(attempts) == 1:
                    raise TimeoutError('Synthetic acquisition timeout')
                async with connection.transaction():
                    yield connection
                    if len(attempts) == 2:
                        raise asyncpg.ConnectionDoesNotExistError('Synthetic transaction failure')

            async def wait_for(wait, *, timeout):
                wait.close()
                delays.append(timeout)
                if len(delays) == 2:
                    self.assertIsNotNone(await connection.fetchval(
                        'SELECT content FROM maintenance_request_photos WHERE photo_ref=$1', expired))
                if len(delays) < 3:
                    raise TimeoutError
                stop.set()

            app = SimpleNamespace(state=SimpleNamespace(pool=connection))
            with patch.multiple(photos, unit_of_work=expiry_transaction,
                                asyncio=SimpleNamespace(wait_for=wait_for)):
                await photos.run_expiry(app, stop)
            self.assertEqual(attempts, [connection] * 3)
            self.assertEqual(delays, [3, 3, 60])

            async with connection.transaction():
                self.assertIsNone(await connection.fetchval(
                    'SELECT content FROM maintenance_request_photos WHERE photo_ref=$1', expired))
                with self.assertRaises(PublicError) as unavailable:
                    await photos.store_photo(connection, actor, second, content)
                self.assertEqual(unavailable.exception.code, 'photo_expired')

                await connection.execute('''INSERT INTO maintenance_closed_operations
                    VALUES ($1,$2,$3)''', operation, actor, organization)
                await photos.discard_unattached(connection, operation, actor, organization)
                self.assertIsNone(await connection.fetchval(
                    'SELECT content FROM maintenance_request_photos WHERE photo_ref=$1', abandoned))
                with self.assertRaises(PublicError):
                    await photos.store_photo(connection, actor, third, content)
                with self.assertRaises(PublicError):
                    await photos.store_photo(connection, actor, photo(uuid4()), content)
                self.assertIsNotNone(await connection.fetchval(
                    'SELECT content FROM maintenance_request_photos WHERE photo_ref=$1', kept))
        finally:
            if connection.is_closed():
                connection = await asyncpg.connect(url)
            await connection.execute(f'DROP SCHEMA {schema} CASCADE')
            await connection.close()


    def test_delivery_is_atomic_restart_safe_and_assignment_scoped(self):
        asyncio.run(self.delivery())

    async def delivery(self):
        url = os.environ['BT_S01_TEST_DATABASE']
        schema = 'maintenance_test_' + uuid4().hex
        connection = await asyncpg.connect(url)
        request_ids = []
        actor, business, other_business, watch, brand = (uuid4() for _ in range(5))

        class Provider:
            routing_allowed = False

            async def current(self, body):
                return body.model_dump(include={
                    'actor_id', 'subject_id', 'watch_id', 'organization_id', 'brand_id',
                    'operation_id', 'intervention', 'watch_revision', 'capability_revision',
                    'policy_revision',
                }) | dict(identity_current=True, watch_owned=True, business_active=True,
                          assessment_supported=True, commitment_available=True, private_refs_current=True)

            async def assessment_queue_access(self, requested_actor, organization):
                if organization not in (business, other_business):
                    return False
                return dict(actor_id=requested_actor, organization_id=organization,
                            assignment_revision=1, request_ids=request_ids,
                            routing_allowed=self.routing_allowed)

        @asynccontextmanager
        async def transaction(_operation):
            async with connection.transaction():
                yield connection

        @asynccontextmanager
        async def acquire(*, timeout):
            yield connection

        provider = Provider()
        req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            maintenance_provider=provider, pool=SimpleNamespace(acquire=acquire))))
        try:
            await connection.execute(f'CREATE SCHEMA {schema}')
            await connection.execute(f'SET search_path TO {schema}')
            for migration in MIGRATIONS:
                await connection.execute(migration.read_text())
            self.assertEqual(int(await connection.fetchval('SHOW server_version_num')) // 10000, 17)
            operation = uuid4()
            body = Request(operation_id=operation, subject_id=actor, actor_id=actor,
                           watch_id=watch, organization_id=business, expected_revision=0,
                           watch_revision=1, capability_revision=1, policy_revision=1,
                           brand_id=brand, intervention='limited_maintenance',
                           reported_symptoms='Private report', known_modifications='Private note',
                           photo_refs=[], limited_assessment_permission=True)
            receipt = await submit(body, actor_id=actor, provider=provider, transaction=transaction)
            request_id = await connection.fetchval(
                'SELECT request_id FROM maintenance_request_outbox WHERE event_id=$1', operation)
            self.assertEqual(str(request_id), receipt['request_id'])
            request_ids.append(request_id)
            from sys import modules

            operator = uuid4()

            async def recovery_access(requested_actor):
                return datetime.now(timezone.utc)+timedelta(seconds=5) if requested_actor == operator else None

            provider.delivery_authority_until = recovery_access
            req.app.state.maintenance_delivery_operator_id = operator
            for attempt in range(1, 9):
                async with connection.transaction():
                    [reservation] = await claim_batch(connection, operator)
                interrupted = connection.transaction()
                await interrupted.start()
                try:
                    await deliver(connection, operation, reservation['next_attempt_at'], operator_id=operator)
                finally:
                    await interrupted.rollback()
                self.assertEqual(await connection.fetchval(
                    'SELECT attempts FROM maintenance_request_outbox WHERE event_id=$1', operation), attempt)
                self.assertEqual(await assessment_inbox(business, req, actor_id=actor),
                                 await assessment_inbox(other_business, req, actor_id=actor))
                await connection.execute(
                    'UPDATE maintenance_request_outbox SET next_attempt_at=clock_timestamp() WHERE event_id=$1',
                    operation)
            await connection.close()
            connection = await asyncpg.connect(url)
            await connection.execute(f'SET search_path TO {schema}')
            async with connection.transaction():
                self.assertEqual(await claim_batch(connection, operator), [])
            routes = modules[held_deliveries.__module__]
            with patch.object(routes, 'unit_of_work', lambda pool, lock_key=None: transaction(lock_key)):
                with self.assertRaises(HTTPException) as denied:
                    await held_deliveries(req, actor)
                self.assertEqual(denied.exception.status_code, 403)
                [hold] = await held_deliveries(req, operator)
                self.assertEqual(hold.operation_id, operation)
                self.assertEqual(hold.next_review_at, hold.held_at + timedelta(hours=24))
                self.assertEqual(hold.escalate_at, hold.held_at + timedelta(hours=48))
                self.assertIsNone(hold.escalated_at)
                self.assertIsNone(hold.first_response_at)
                self.assertFalse(hold.first_response_overdue)
                await connection.execute(
                    "UPDATE maintenance_request_outbox SET held_at=statement_timestamp()-interval '24 hours', escalation_started_at=statement_timestamp()-interval '24 hours' WHERE event_id=$1",
                    operation)
                [overdue] = await held_deliveries(req, operator)
                self.assertTrue(overdue.first_response_overdue)
                self.assertEqual(overdue.next_action, 'respond_to_overdue_delivery')
                response = DeliveryRecoveryCommand(held_at=overdue.held_at, action='acknowledge')
                await retry_delivery(operation, response, req, operator)
                [answered] = await held_deliveries(req, operator)
                self.assertGreaterEqual(answered.first_response_at, overdue.next_review_at)
                await retry_delivery(operation, response, req, operator)
                self.assertEqual((await held_deliveries(req, operator))[0], answered)

                # Exercise the operator winning the row lock before the delivery
                # worker. Roll back each branch to preserve the worker scenario below.
                for age, expected_escalations in [(47, 0), (49, 1)]:
                    with self.subTest(hold_age_hours=age):
                        branch = connection.transaction()
                        await branch.start()
                        try:
                            held_at = await connection.fetchval("""
                                UPDATE maintenance_request_outbox
                                SET held_at = statement_timestamp() - make_interval(hours => $2),
                                    escalation_started_at = statement_timestamp() - make_interval(hours => $2)
                                WHERE event_id = $1 RETURNING held_at
                            """, operation, age)
                            command = DeliveryRecoveryCommand(held_at=held_at)
                            await retry_delivery(operation, command, req, operator)
                            await retry_delivery(operation, command, req, operator)
                            escalation = await connection.fetch("""
                                SELECT held_at, operator_id, escalated_at
                                FROM maintenance_delivery_escalations WHERE event_id = $1
                            """, operation)
                            self.assertEqual(len(escalation), expected_escalations)
                            if escalation:
                                self.assertEqual(escalation[0]['held_at'], held_at)
                                self.assertEqual(escalation[0]['operator_id'], operator)
                                self.assertGreaterEqual(escalation[0]['escalated_at'],
                                                        held_at + timedelta(hours=48))
                            self.assertIsNone(await connection.fetchval(
                                'SELECT held_at FROM maintenance_request_outbox WHERE event_id=$1', operation))
                        finally:
                            await branch.rollback()

                branch = connection.transaction()
                await branch.start()
                try:
                    first = DeliveryRecoveryCommand(held_at=answered.held_at)
                    await retry_delivery(operation, first, req, operator)
                    second_hold = await connection.fetchval("""
                        UPDATE maintenance_request_outbox
                        SET held_at = clock_timestamp(), attempts = 8, operator_id = $2
                        WHERE event_id = $1 RETURNING held_at
                    """, operation, operator)
                    await retry_delivery(operation, DeliveryRecoveryCommand(held_at=second_hold), req, operator)
                    await retry_delivery(operation, first, req, operator)
                    self.assertEqual(await connection.fetchval("""
                        SELECT last_requeued_hold_at FROM maintenance_request_outbox WHERE event_id = $1
                    """, operation), second_hold)
                    with self.assertRaises(HTTPException) as denied:
                        await retry_delivery(operation, first, req, actor)
                    self.assertEqual(denied.exception.status_code, 403)
                finally:
                    await branch.rollback()

                # Requeue just before the original deadline. The next reserved
                # attempt must remain subject to that deadline.
                branch = connection.transaction()
                await branch.start()
                try:
                    origin = await connection.fetchval("""
                        UPDATE maintenance_request_outbox
                        SET escalation_started_at = statement_timestamp() - interval '47 hours 59 minutes'
                        WHERE event_id = $1 RETURNING escalation_started_at
                    """, operation)
                    await retry_delivery(operation, DeliveryRecoveryCommand(held_at=answered.held_at), req, operator)
                    pending = await connection.fetchrow("""
                        SELECT held_at, escalation_started_at, escalated_at
                        FROM maintenance_request_outbox WHERE event_id = $1
                    """, operation)
                    self.assertEqual(tuple(pending), (None, origin, None))
                    [reservation] = await claim_batch(connection, operator)
                    self.assertEqual(reservation['event_id'], operation)

                    # Advance the test clock to the deadline with the
                    # unsuccessful reservation still outstanding.
                    origin = await connection.fetchval("""
                        UPDATE maintenance_request_outbox
                        SET escalation_started_at = statement_timestamp() - interval '48 hours'
                        WHERE event_id = $1 RETURNING escalation_started_at
                    """, operation)
                    self.assertEqual(await claim_batch(connection, operator), [])
                    escalation = await connection.fetchrow("""
                        SELECT held_at, operator_id, escalated_at
                        FROM maintenance_delivery_escalations WHERE event_id = $1
                    """, operation)
                    self.assertEqual(escalation['held_at'], origin)
                    self.assertEqual(escalation['operator_id'], operator)
                    self.assertGreaterEqual(escalation['escalated_at'], origin + timedelta(hours=48))

                    [active] = await held_deliveries(req, operator)
                    self.assertEqual(active.operation_id, operation)
                    self.assertEqual(active.operator_id, operator)
                    self.assertEqual(active.held_at, answered.held_at)
                    self.assertTrue(active.retry_in_progress)
                    self.assertEqual(active.next_action, 'review_active_escalation')
                    self.assertEqual(active.escalate_at, origin + timedelta(hours=48))
                    review = DeliveryRecoveryCommand(held_at=active.held_at, action='review_escalation')
                    with self.assertRaises(HTTPException) as denied:
                        await retry_delivery(operation, review, req, actor)
                    self.assertEqual(denied.exception.status_code, 403)
                    with self.assertRaises(PublicError) as stale:
                        await retry_delivery(operation, review.model_copy(update={
                            'held_at': active.held_at - timedelta(seconds=1),
                        }), req, operator)
                    self.assertEqual(stale.exception.code, 'delivery_hold_changed')
                    await retry_delivery(operation, review, req, operator)
                    [reviewed] = await held_deliveries(req, operator)
                    self.assertEqual(reviewed.next_action, 'monitor_escalated_retry')
                    self.assertGreaterEqual(reviewed.escalation_reviewed_at, active.escalated_at)
                    await retry_delivery(operation, review, req, operator)
                    self.assertEqual(await held_deliveries(req, operator), [reviewed])
                    self.assertEqual(await connection.fetchval(
                        'SELECT attempts FROM maintenance_request_outbox WHERE event_id=$1', operation), 1)
                    self.assertEqual(await connection.fetchval(
                        'SELECT next_attempt_at FROM maintenance_request_outbox WHERE event_id=$1', operation),
                        reservation['next_attempt_at'])

                    await connection.execute("""
                        UPDATE maintenance_request_outbox
                        SET attempts = 8, next_attempt_at = statement_timestamp()
                        WHERE event_id = $1
                    """, operation)
                    self.assertEqual(await claim_batch(connection, operator), [])
                    [new_hold] = await held_deliveries(req, operator)
                    self.assertGreater(new_hold.held_at, answered.held_at)
                    self.assertEqual(new_hold.escalate_at, origin + timedelta(hours=48))
                    self.assertEqual(new_hold.escalated_at, escalation['escalated_at'])
                    self.assertEqual(new_hold.next_action, 'resolve_escalated_delivery')
                    await retry_delivery(operation, review, req, operator)
                    self.assertEqual(await held_deliveries(req, operator), [new_hold])
                    await retry_delivery(operation, DeliveryRecoveryCommand(held_at=new_hold.held_at), req, operator)
                    self.assertEqual(await connection.fetchval(
                        'SELECT count(*) FROM maintenance_delivery_escalations WHERE event_id=$1', operation), 1)
                    [reservation] = await claim_batch(connection, operator)
                    await deliver(connection, operation, reservation['next_attempt_at'], operator_id=operator)
                    await retry_delivery(operation, review, req, operator)
                    self.assertEqual(await held_deliveries(req, operator), [])
                finally:
                    await branch.rollback()

                # A successful attempt can cross the original deadline before
                # the periodic escalation scan sees it.
                branch = connection.transaction()
                await branch.start()
                try:
                    await retry_delivery(operation, DeliveryRecoveryCommand(held_at=answered.held_at), req, operator)
                    [reservation] = await claim_batch(connection, operator)
                    await connection.execute("""
                        UPDATE maintenance_request_outbox
                        SET escalation_started_at = statement_timestamp() - interval '48 hours'
                        WHERE event_id = $1
                    """, operation)
                    await deliver(connection, operation, reservation['next_attempt_at'], operator_id=operator)
                    delivery = await connection.fetchrow("""
                        SELECT o.delivered_at, e.escalated_at
                        FROM maintenance_request_outbox o
                        JOIN maintenance_delivery_escalations e USING (event_id)
                        WHERE event_id = $1
                    """, operation)
                    self.assertIsNotNone(delivery)
                    self.assertEqual(delivery['delivered_at'], delivery['escalated_at'])
                    [late] = await held_deliveries(req, operator)
                    self.assertEqual(late.held_at, answered.held_at)
                    self.assertEqual(late.next_action, 'review_delivered_escalation')
                    self.assertFalse(late.retry_in_progress)

                    wrong_hold = DeliveryRecoveryCommand(
                        held_at=late.held_at - timedelta(seconds=1), action='review_escalation')
                    with self.assertRaises(PublicError) as stale:
                        await retry_delivery(operation, wrong_hold, req, operator)
                    self.assertEqual(stale.exception.status, 409)
                    self.assertEqual(await held_deliveries(req, operator), [late])

                    review = DeliveryRecoveryCommand(held_at=late.held_at, action='review_escalation')
                    await retry_delivery(operation, review, req, operator)
                    await retry_delivery(operation, review, req, operator)
                    self.assertEqual(await held_deliveries(req, operator), [])
                    self.assertEqual(await connection.fetchval(
                        'SELECT reviewed_by FROM maintenance_delivery_escalations WHERE event_id=$1',
                        operation), operator)
                finally:
                    await branch.rollback()

                self.assertEqual(hold.next_action, 'review_and_retry_delivery')
                await connection.execute("""
                    UPDATE maintenance_request_outbox SET held_at=statement_timestamp()-interval '48 hours',
                        escalation_started_at=statement_timestamp()-interval '48 hours'
                    WHERE event_id=$1
                """, operation)
                for _ in range(2):
                    async with connection.transaction():
                        self.assertEqual(await claim_batch(connection, operator), [])
                [hold] = await held_deliveries(req, operator)
                self.assertEqual(hold.next_action, 'resolve_escalated_delivery')
                self.assertGreaterEqual(hold.escalated_at, hold.escalate_at)
                former_operator, operator = operator, uuid4()
                req.app.state.maintenance_delivery_operator_id = operator
                async with connection.transaction():
                    self.assertEqual(await claim_batch(connection, operator), [])
                with self.assertRaises(HTTPException) as denied:
                    await held_deliveries(req, former_operator)
                self.assertEqual(denied.exception.status_code, 403)
                [transferred] = await held_deliveries(req, operator)
                self.assertEqual(transferred, hold.model_copy(update={'operator_id': operator}))
                await retry_delivery(operation, DeliveryRecoveryCommand(held_at=hold.held_at), req, operator)
                await retry_delivery(operation, DeliveryRecoveryCommand(held_at=hold.held_at), req, operator)
                self.assertEqual(await connection.fetchval(
                    'SELECT count(*) FROM maintenance_delivery_escalations WHERE event_id=$1', operation), 1)
                with self.assertRaises(PublicError) as stale:
                    await retry_delivery(operation, DeliveryRecoveryCommand(held_at=hold.held_at - timedelta(seconds=1)),
                                         req, operator)
                self.assertEqual(stale.exception.code, 'delivery_hold_changed')
            async with connection.transaction():
                [reservation] = await claim_batch(connection, operator)
            for _ in range(2):
                async with connection.transaction():
                    await deliver(connection, operation, reservation['next_attempt_at'], operator_id=operator)
            page = await assessment_inbox(business, req, actor_id=actor)
            self.assertEqual([item.request_id for item in page.items], [request_id])
            self.assertEqual(page.total, 1)
            self.assertEqual(page.items[0].delivered_at, await connection.fetchval(
                'SELECT delivered_at FROM maintenance_request_outbox WHERE event_id=$1', operation))
            self.assertEqual((await assessment_inbox(other_business, req, actor_id=actor)).total, 0)
            self.assertEqual((await assessment_inbox(business, req, 50, actor)).total, 1)
            request_ids.clear()
            self.assertEqual((await assessment_inbox(business, req, actor_id=actor)).total, 0)
            provider.routing_allowed = True
            self.assertEqual((await assessment_inbox(business, req, actor_id=actor)).total, 1)
            self.assertEqual((await assessment_inbox(other_business, req, actor_id=actor)).total, 0)
            with self.assertRaises(HTTPException) as denied:
                await assessment_inbox(uuid4(), req, actor_id=actor)
            self.assertEqual(denied.exception.status_code, 403)
        finally:
            if connection.is_closed():
                connection = await asyncpg.connect(url)
            await connection.execute(f'DROP SCHEMA {schema} CASCADE')
            await connection.close()
