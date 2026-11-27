"""Bounded native auction requests and owned replica recovery."""
import asyncio
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
from tempfile import NamedTemporaryFile
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import jwt

from contract import CaseResult, Sample
from fault_transport import ResponseBarrier

ROOT = Path(__file__).resolve().parents[4]


class MissingCapability(RuntimeError):
    pass


def private_json(path):
    if path.stat().st_mode & 0o077:
        raise MissingCapability('private_configuration_mode')
    return json.loads(path.read_text())


def local_url(value, *, database=False):
    parsed = urlsplit(value)
    if (parsed.hostname != '127.0.0.1' or
            parsed.scheme not in (('postgresql', 'postgres') if database else ('http',)) or
            (database and parsed.port != 54329)):
        raise MissingCapability('loopback_provider_configuration')


class Replica:
    """Only the child created here is ever stopped or restarted."""
    def __init__(self, run_dir):
        config = private_json(run_dir / 'native-v1.json')
        if config.get('schema_version') != 1:
            raise MissingCapability('native_configuration_v1')
        configured = config['services']['auction']['env']
        if not isinstance(configured, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in configured.items()):
            raise MissingCapability('auction_runtime_environment')
        configured = {key: value for key, value in configured.items()
                      if key == 'BT_DATABASE_URL' or not (key.endswith('_URL') and
                          (key.startswith('TEST_') or 'DATABASE' in key or 'OWNER' in key))}
        local_url(configured['BT_DATABASE_URL'], database=True)
        for key, value in configured.items():
            if key.endswith('_URL') and key != 'BT_DATABASE_URL':
                local_url(value)
        contracts = run_dir / 'domain-contracts'
        if not (contracts / 'bt_contracts').is_dir():
            raise MissingCapability('packaged_contracts')
        source = ROOT / 'services/auction'
        paths = [source, source / 'runtime', contracts]
        paths += [ROOT / 'packages' / name / 'src'
                  for name in ('runtime', 'contracts-core', 'bulkheads', 'events')]
        self.env = {k: os.environ[k] for k in ('PATH', 'LANG') if k in os.environ}
        self.env.update(configured)
        self.env.update(PYTHONPATH=os.pathsep.join(map(str, paths)),
                        PYTHONDONTWRITEBYTECODE='1', BT_SERVICE_NAME='auction',
                        BT_MODULES_PATH=str(source / 'modules'))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.process = None

    async def start(self):
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'service_app.main:create_app', '--factory',
             '--host', '127.0.0.1', '--port', str(self.port), '--no-access-log'],
            cwd=ROOT, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                for _ in range(100):
                    if self.process.poll() is not None:
                        raise MissingCapability('replica_start')
                    try:
                        response = await client.get(f'http://127.0.0.1:{self.port}/health/ready')
                        if response.status_code == 200:
                            return
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(.1)
            raise MissingCapability('replica_readiness')
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        if self.process is not None:
            process, self.process = self.process, None
            if process.poll() is None:
                process.kill()
            for _ in range(100):
                if process.poll() is not None:
                    process.wait(timeout=0)
                    return
                await asyncio.sleep(.05)
            raise MissingCapability('owned_replica_cleanup')

    async def restart(self):
        await self.stop()
        await self.start()


class NativeProvider:
    def __init__(self, run_dir, inputs, replica, client):
        self.run_dir, self.inputs = run_dir, inputs
        self.replica, self.client = replica, client
        self.tokens = {}
        self.subjects = {}
        self.notice_tasks = []
        self.notice_samples = []
        self.notice_failure = None
        self.operations = []
        self.failures = {}
        self.lots = {}
        self.acknowledged = []
        self.session_emails = {}
        self.session_deadlines = {}
        self.session_locks = {}
        self.replica_writes = asyncio.Condition()
        self.owned_inflight = 0
        self.restarting = False
        self.notice_reads = asyncio.Semaphore(8)
        self.owned_acknowledged = []
        self.acknowledged_processes = {}
        self.mid_load_restarted = False
        self.gateway = 'http://127.0.0.1:3000/api/web/v1'

    async def request(self, service, method, path, *, actor=None, body=None,
                      key=None, replica=None, expected=(200, 201, 202), cookie=None,
                      session_actor=None, bearer=None, lose_response_once=False, owner_read=False):
        if actor is not None:
            await self.renew_session(actor)
        base = self.gateway + '/' + service
        if replica is not None:
            if service != 'auction':
                raise ValueError('Replica requests are auction only')
            base = f'http://127.0.0.1:{8103 if replica == 0 else self.replica.port}'
        if owner_read:
            if method != 'GET' or service not in ('auction', 'communications', 'identity'):
                raise ValueError('Owner reads require a supported read service')
            base = 'http://127.0.0.1:' + str({'auction': 8103, 'communications': 8108,
                                                'identity': 8101}[service])
        headers = {'Origin': 'http://127.0.0.1:3000', 'Cookie': ''}
        if cookie is not None:
            headers['Cookie'] = 'bt_refresh=' + cookie
        if actor is not None:
            bearer = self.tokens[actor]
        if bearer is not None:
            headers['Authorization'] = 'Bearer ' + bearer
        if method != 'GET':
            key = key or str(uuid4())
            headers['Idempotency-Key'] = key
        attempts = 1 if path in ('/v1/accounts/refresh', '/v1/accounts/logout') else 3
        for attempt in range(attempts):
            try:
                response = await self.client.request(method, base + path, json=body,
                                                     headers=headers, timeout=5)
                if response.status_code not in expected:
                    raise MissingCapability(f'{service}_http_{response.status_code}')
                if session_actor is not None:
                    successor = response.cookies.get('bt_refresh')
                    self.client.cookies.clear()
                    if not successor or successor == cookie:
                        raise MissingCapability('refresh_session_cookie')
                    self.checkpoint_session(session_actor, successor)
                if len(response.content) > 2_000_000:
                    raise MissingCapability('bounded_response')
                if lose_response_once and attempt == 0:
                    raise httpx.ReadError('Response discarded after commit')
                return response.json()
            except httpx.TransportError:
                if attempt == attempts - 1:
                    raise MissingCapability('request_transport') from None
        raise AssertionError('Request attempts exhausted')

    def session(self, actor):
        return self.inputs['sessions'][self.session_emails[actor]]

    def checkpoint_session(self, actor, cookie):
        entry = self.session(actor)
        path = self.run_dir / 'a10-input.json'
        previous = entry['refresh_cookie']
        entry['refresh_cookie'] = cookie
        try:
            with NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    json.dump(self.inputs, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            entry['refresh_cookie'] = previous
            raise MissingCapability('private_session_checkpoint') from None

    async def renew_session(self, actor):
        lock = self.session_locks.setdefault(actor, asyncio.Lock())
        async with lock:
            if time.monotonic() < self.session_deadlines.get(actor, 0):
                return
            entry = self.session(actor)
            cookie = entry['refresh_cookie']
            if not cookie:
                raise MissingCapability('refresh_session_cookie')
            # A lost response may have consumed this cookie. Invalidate it on disk
            # before sending the request so a resumed run cannot replay it.
            self.checkpoint_session(actor, None)
            result = await self.request('identity', 'POST', '/v1/accounts/refresh',
                                        cookie=cookie, session_actor=actor)
            bearer = result['access_token']
            deadline = time.monotonic() + min(result.get('expires_in', 300), 300) - 30
            account = await self.request('identity', 'GET', '/v1/accounts/me',
                                         bearer=bearer, owner_read=True)
            subject = str(UUID(entry['subject_id']))
            if account.get('id') != subject or account.get('email') != self.session_emails[actor]:
                raise MissingCapability('prepared_session_identity_mismatch')
            if actor != 'seller':
                contacts = await self.request('identity', 'GET', '/v1/contacts',
                                              bearer=bearer, owner_read=True)
                if not (contacts.get('email_verified') or contacts.get('phone_verified')):
                    raise MissingCapability('verified_buyer_contacts')
            self.subjects[actor] = subject
            self.tokens[actor] = bearer
            self.session_deadlines[actor] = deadline

    async def prepare(self):
        actors = self.inputs.get('actors', [])
        if len(actors) != 200:
            raise MissingCapability('200_distinct_authorized_sample_buyers')
        try:
            emails = [credentials['email'].strip().lower()
                      for credentials in [self.inputs['seller'], *actors]]
            sessions = self.inputs['sessions']
            subjects = {UUID(sessions[email]['subject_id']) for email in emails}
            cookies = [sessions[email]['refresh_cookie'] for email in emails]
        except (KeyError, ValueError, TypeError, AttributeError):
            raise MissingCapability('prepared_session_input') from None
        if len(set(emails)) != 201 or len(subjects) != 201:
            raise MissingCapability('distinct_current_accounts')
        if any(not isinstance(cookie, str) or not cookie for cookie in cookies):
            raise MissingCapability('refresh_session_cookie')
        if len(set(cookies)) != 201:
            raise MissingCapability('distinct_refresh_sessions')

        self.session_emails = dict(zip(['seller', *range(200)], emails))
        for actor in self.session_emails:
            await self.renew_session(actor)

    async def lot(self, name):
        if name in self.lots:
            return self.lots[name]
        listing = self.inputs.get('listings', {}).get(name)
        if not listing:
            raise MissingCapability('fresh_listing:' + name)
        UUID(listing)
        if listing in [row['listing_id'] for row in self.lots.values()]:
            raise MissingCapability('fresh_distinct_listing:' + name)
        # Use the authoritative server clock, never a client countdown.
        from datetime import datetime, timedelta
        current = await self.request('auction', 'GET', '/v1/auctions?limit=1')
        now = datetime.fromisoformat(current['server_time'])
        result = await self.request('auction', 'POST', '/v1/auctions', actor='seller', body={
            'listing_id': listing, 'currency': 'USD', 'opening_minor': 400000,
            'increment_bands': [{'from_minor': 0, 'step_minor': 10000}],
            'starts_at': (now + timedelta(seconds=1)).isoformat(),
            'ends_at': (now + (timedelta(seconds=15) if name in ('equal_end', 'after_end', 'one_winner_allocation_restart')
                               else timedelta(minutes=10))).isoformat()})
        if result.get('status') != 'succeeded':
            raise MissingCapability('auction_creation:' + name)
        identifier = result.get('auction_id') or result.get('resource_id') or result['auction']['id']
        for _ in range(30):
            lot = await self.snapshot(identifier)
            if lot['status'] == 'live':
                if lot['accepted_sequence'] != 0:
                    raise MissingCapability('unused_auction:' + name)
                self.lots[name] = lot
                return lot
            await asyncio.sleep(.1)
        raise MissingCapability('live_auction:' + name)

    async def snapshot(self, identifier, replica=None):
        return await self.request('auction', 'GET', '/v1/auctions/' + identifier, replica=replica)

    async def command(self, lot, actor, amount=None):
        amount = amount or lot['next_minimum_minor']
        body = {'subject_id': lot['id'], 'subject_revision': lot['revision'],
                'purpose': 'bid', 'source': 'sample', 'schedule_id': 'usd-v2',
                'currency': 'USD', 'price_minor': amount}
        quote = await self.request('pricing', 'POST', '/v1/quotes', actor=actor, body=body)
        reviewed = await self.request('pricing', 'POST', '/v1/quotes/' + quote['id'] + '/review',
                                      actor=actor, body={**body, 'quote_revision': quote['revision'],
                                                         'payable_minor': quote['payable_minor']})
        if not reviewed.get('reviewed_at'):
            raise MissingCapability('retained_fee_review')
        return {'amount_minor': amount, 'fee_quote_id': quote['id'],
                'expected_revision': lot['revision']}

    async def submit(self, lot, actor, body, key, replica=None, *, lose_response_once=False):
        result = await self.request('auction', 'POST', f"/v1/auctions/{lot['id']}/bids",
                                    actor=actor, body=body, key=key, replica=replica, expected=(200, 201, 202, 409),
                                    lose_response_once=lose_response_once)
        if 'error' in result:
            return {'status': 'denied', 'code': result['error']['code']}
        if 'operation_id' in result:
            self.operations.append(str(UUID(result['operation_id'])))
        return result

    async def history(self, identifier, replica):
        rows, cursor = [], 0
        for _ in range(100):
            page = await self.request('auction', 'GET',
                f'/v1/auctions/{identifier}/history?after_sequence={cursor}&limit=100', replica=replica)
            items = page['items']
            if any(row['sequence'] != cursor + i + 1 for i, row in enumerate(items)):
                raise AssertionError('History is not gap free')
            rows.extend(items)
            if not page['has_more']:
                return rows
            if not items or page['next_sequence'] <= cursor:
                raise AssertionError('History cursor did not advance')
            cursor = page['next_sequence']
        raise MissingCapability('bounded_history_pages')

    async def run_load(self, kind, dataset):
        if kind == 'notices':
            if self.notice_failure:
                raise MissingCapability(self.notice_failure)
            if len(self.notice_samples) != dataset.bidders:
                raise MissingCapability('complete_bid_notice_observations')
            return self.notice_samples
        lot = await self.lot(kind)
        if kind == 'viewers':
            body = await self.command(lot, 0)
            started = time.monotonic()
            accepted = await self.submit(lot, 0, body, str(uuid4()))
            if accepted.get('status') != 'succeeded':
                raise MissingCapability('viewer_trigger_admission')
            sequence = accepted['accepted_sequence']
            async def read_view(person, replica):
                for _ in range(20):
                    current = await self.request('auction', 'GET',
                        '/v1/auctions/' + lot['id'], actor=person)
                    if current['accepted_sequence'] >= sequence:
                        direct = await self.snapshot(lot['id'], replica)
                        if direct['accepted_sequence'] < sequence:
                            await asyncio.sleep(.05)
                            continue
                    if current['accepted_sequence'] >= sequence:
                        return Sample(person, replica, sequence, (time.monotonic() - started) * 1000)
                    await asyncio.sleep(.05)
                return Sample(person, replica, sequence, (time.monotonic() - started) * 1000, True)
            async def view(person, replica):
                try:
                    return await read_view(person, replica)
                except Exception:
                    return Sample(person, replica, sequence,
                                  (time.monotonic() - started) * 1000, True)
            return await asyncio.gather(*(view(p, r) for p in range(dataset.viewers) for r in range(2)))
        if kind != 'bidders':
            raise ValueError('Unknown load kind')
        slots = asyncio.Semaphore(8)
        async def place_bid(person):
            started = time.monotonic()
            async with slots:
                for _ in range(dataset.bidders + 1):
                    current = await self.snapshot(lot['id'])
                    body = await self.command(current, person)
                    key = str(uuid4())
                    submitted = time.monotonic()
                    writer = 1 if person % 2 else None
                    def acknowledge():
                        if result.get('status') == 'succeeded':
                            self.acknowledged.append((person, key, result))
                            self.acknowledged_processes[key] = writer or 0
                            self.notice_tasks.append(asyncio.create_task(
                                self.observe_notice(current, person, result, submitted)))
                    if writer == 1:
                        async with self.replica_writes:
                            await self.replica_writes.wait_for(lambda: not self.restarting)
                            self.owned_inflight += 1
                        try:
                            result = await self.submit(current, person, body, key, replica=writer)
                            acknowledge()
                            if result.get('status') == 'succeeded':
                                self.owned_acknowledged.append((person, key, result))
                        finally:
                            async with self.replica_writes:
                                self.owned_inflight -= 1
                                self.replica_writes.notify_all()
                        async with self.replica_writes:
                            if (len(self.owned_acknowledged) >= max(1, dataset.bidders // 4)
                                    and not self.mid_load_restarted and not self.restarting):
                                self.restarting = True
                                try:
                                    await self.replica_writes.wait_for(lambda: self.owned_inflight == 0)
                                    await self.replica.restart()
                                    self.mid_load_restarted = True
                                finally:
                                    self.restarting = False
                                    self.replica_writes.notify_all()
                    else:
                        result = await self.submit(current, person, body, key)
                        acknowledge()
                    if result.get('status') == 'denied':
                        code = result.get('code', 'unexplained_denial')
                        self.failures[code] = self.failures.get(code, 0) + 1
                    if result.get('code') != 'stale_revision':
                        break
                    # A durable denial completes this command. Rebind a new command.
                    await asyncio.sleep(.01)
            succeeded = result.get('status') == 'succeeded'
            if not succeeded and result.get('status') != 'denied':
                code = result.get('code', 'unexplained_denial')
                self.failures[code] = self.failures.get(code, 0) + 1
            return Sample(person, 0, result.get('accepted_sequence') or 1,
                          (time.monotonic() - started) * 1000, not succeeded)
        async def bid(person):
            started = time.monotonic()
            try:
                return await asyncio.wait_for(place_bid(person), dataset.timeout_seconds)
            except Exception as error:
                code = str(error) if isinstance(error, MissingCapability) else 'participant_request_failed'
                self.failures[code] = self.failures.get(code, 0) + 1
                return Sample(person, 0, 1, (time.monotonic() - started) * 1000, True)
        cancelled = False
        try:
            rows = await asyncio.gather(*(bid(p) for p in range(dataset.bidders)))
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            if cancelled:
                for task in self.notice_tasks:
                    task.cancel()
            observations = await asyncio.gather(*self.notice_tasks, return_exceptions=True)
            self.notice_tasks.clear()
            for observation in observations:
                if isinstance(observation, Sample):
                    self.notice_samples.append(observation)
        return rows

    async def notice_binding(self, lot, actor, sequence):
        """Bind source admission to the recipient's durable Inbox through owner reads."""
        source = await self.request('auction', 'GET',
            f"/v1/auctions/{lot['id']}/bid-receipts/{sequence}", actor=actor, owner_read=True)
        receipt = await self.request('communications', 'GET',
            f"/v1/bid-notice-receipts/{source['event_id']}", actor=actor, expected=(200, 404), owner_read=True)
        if 'error' in receipt:
            assert receipt['error']['code'] == 'not_found'
            return None
        assert receipt['event_id'] == source['event_id']
        assert receipt['auction_id'] == lot['id'] and receipt['sequence'] == sequence
        if receipt['inbox_id'] is None:
            return None
        return receipt['notice_id'], receipt['inbox_id']

    async def observe_notice(self, lot, actor, receipt, started):
        try:
            return await self.read_notice(lot, actor, receipt, started)
        except Exception:
            return Sample(actor, 0, receipt['accepted_sequence'],
                          (time.monotonic() - started) * 1000, True)

    async def read_notice(self, lot, actor, receipt, started):
        sequence = receipt['accepted_sequence']
        deadline = started + 35
        while time.monotonic() < deadline:
            page = await self.request('communications', 'GET', '/v1/bid-notices?limit=100',
                                      actor=actor)
            matches = [row for row in page['items'] if row['auction_id'] == lot['id']
                       and row['sequence'] == sequence and row['kind'] == 'bid_accepted']
            if matches:
                assert len(matches) == 1
                async with self.notice_reads:
                    binding = await self.notice_binding(lot, actor, sequence)
                if binding and binding[0] == matches[0]['id']:
                    identifier, inbox_id = binding
                    opened = await self.request('communications', 'GET',
                        '/v1/bid-notices/' + identifier, actor=actor)
                    assert opened['notice']['id'] == identifier
                    inbox = await self.request('communications', 'GET', '/v1/inbox?limit=50',
                                               actor=actor)
                    if not any(row['id'] == inbox_id for row in inbox['items']):
                        await asyncio.sleep(.1)
                        continue
                    return Sample(actor, 0, sequence, (time.monotonic() - started) * 1000)
            await asyncio.sleep(.1)
        raise MissingCapability('notice_recipient_event_visibility_timeout')

    async def exercise(self, case, dataset):
        supported = {'duplicate_command', 'stale_revision', 'cross_account_lookup',
                     'replica_loss_poll_resync', 'worker_restart_acknowledged_bids', 'before_end',
                     'lost_response_same_operation', 'revoked_identity',
                     'equal_end', 'after_end', 'private_maximum_redaction', 'denied_scope',
                     'timeout_pending', 'outbox_replay_duplicate_notice',
                     'one_winner_allocation_restart'}
        if case not in supported:
            raise MissingCapability('scenario:' + case)
        if case == 'worker_restart_acknowledged_bids':
            return await self.recover_load(dataset)
        lot = await self.lot(case)
        if case in ('timeout_pending', 'outbox_replay_duplicate_notice',
                    'one_winner_allocation_restart'):
            return await self.interrupted_journey(case, lot)
        if case == 'denied_scope':
            organization = self.inputs.get('scope_organization_id')
            if not organization:
                raise MissingCapability('current_scope_organization')
            organization = str(UUID(organization))
            principal = await self.request('identity', 'GET',
                '/internal/v1/principal?organization_id=' + organization,
                actor='seller', owner_read=True)
            assert principal['actor']['organization_id'] == organization
            assert principal['actor']['subject_id'] == self.subjects['seller']
            before = await self.history(lot['id'], 0)
            body = await self.command(lot, 'seller')
            await self.request('auction', 'POST',
                f"/v1/auctions/{lot['id']}/bids?organization_id={organization}",
                actor='seller', body=body, replica=1, expected=(403,))
            assert await self.history(lot['id'], 0) == before
            return CaseResult('denied', ())
        if case == 'private_maximum_redaction':
            return await self.maximum_journey(lot)
        if case == 'revoked_identity':
            actor = dataset.bidders - 1
            body = await self.command(lot, actor)
            before = await self.history(lot['id'], 0)
            await self.renew_session(actor)
            bearer = self.tokens[actor]
            cookie = self.session(actor)['refresh_cookie']
            self.checkpoint_session(actor, None)
            await self.request('identity', 'POST', '/v1/accounts/logout',
                               bearer=bearer, cookie=cookie)
            self.tokens.pop(actor)
            self.session_deadlines.pop(actor)
            await self.request('auction', 'POST', f"/v1/auctions/{lot['id']}/bids",
                               bearer=bearer, body=body, expected=(401, 403))
            assert await self.history(lot['id'], 0) == before
            return CaseResult('denied', ())
        body = await self.command(lot, 0)
        key = str(uuid4())
        if case in ('equal_end', 'after_end'):
            if case == 'equal_end':
                boundary = await self.request('auction', 'GET',
                    f"/v1/auctions/{lot['id']}/deadline-boundary",
                    actor='seller', owner_read=True)
                assert boundary['auction_id'] == lot['id']
                assert boundary['evaluated_at'] == boundary['ends_at'] == lot['ends_at']
                assert boundary['code'] in ('auction_ended', 'auction_committed')
                assert boundary['accepted_sequence'] == 0
                assert boundary['revision'] >= lot['revision']
            from datetime import datetime
            while True:
                current = await self.snapshot(lot['id'])
                if datetime.fromisoformat(current['server_time']) > datetime.fromisoformat(lot['ends_at']):
                    break
                await asyncio.sleep(.5)
            before = await self.history(lot['id'], 0)
            denied = await self.submit(lot, 0, body, key)
            assert denied['status'] == 'denied' and denied['code'] in (
                'auction_ended', 'auction_window_or_fee_expired', 'auction_committed')
            assert await self.history(lot['id'], 0) == before == []
            for replica in range(2):
                unchanged = await self.snapshot(lot['id'], replica)
                assert unchanged['ends_at'] == lot['ends_at']
                assert datetime.fromisoformat(unchanged['server_time']) >= datetime.fromisoformat(lot['ends_at'])
                assert unchanged['accepted_sequence'] == 0
                assert unchanged['current_minor'] == lot['current_minor']
                assert await self.history(lot['id'], replica) == []
                if denied['code'] == 'auction_committed' or (
                        case == 'equal_end' and boundary['code'] == 'auction_committed'):
                    closed = await self.request('auction', 'GET',
                        f"/v2/auctions/{lot['id']}", replica=replica)
                    assert closed['mode'] == 'closed_no_sale'
                    assert closed['ends_at'] == lot['ends_at']
                    assert closed['accepted_sequence'] == 0
                    assert closed['current_minor'] == lot['current_minor']
            return CaseResult('denied', ())
        accepted = await self.submit(lot, 0, body, key,
                                     lose_response_once=case == 'lost_response_same_operation')
        assert accepted['status'] == 'succeeded'
        before = await self.history(lot['id'], 0)
        snapshot = await self.snapshot(lot['id'], 0)
        if case == 'stale_revision':
            stale = await self.submit(lot, 0, body, str(uuid4()))
            assert stale['status'] == 'denied' and stale['code'] == 'stale_revision'
            assert await self.history(lot['id'], 0) == before
            return CaseResult('denied', ())
        if case == 'cross_account_lookup':
            await self.request('auction', 'GET', '/v1/auction-operations/by-key/' + key,
                               actor=1, expected=(404,))
            return CaseResult('denied', ())
        if case in ('duplicate_command', 'lost_response_same_operation'):
            assert len(before) == 1 and accepted['accepted_sequence'] == 1
            duplicate = await self.submit(lot, 0, body, key)
            assert duplicate == accepted
            assert await self.history(lot['id'], 0) == before
            return CaseResult('succeeded', ('same_operation', 'one_public_change'))
        if case == 'before_end':
            assert accepted['server_time'] < accepted['ends_at']
            assert snapshot['ends_at'] == lot['ends_at']
            return CaseResult('succeeded', ('accepted_before_end', 'unchanged_scheduled_end'))
        # Acknowledge through the owned child before killing it.
        own = await self.request('auction', 'GET', '/v1/auction-operations/by-key/' + key,
                                 actor=0, replica=1)
        assert own == accepted
        await self.replica.stop()
        assert await self.history(lot['id'], 0) == before
        await self.replica.start()
        assert await self.history(lot['id'], 1) == before
        after = await self.snapshot(lot['id'], 1)
        assert {k: v for k, v in after.items() if k != 'server_time'} == {
            k: v for k, v in snapshot.items() if k != 'server_time'}
        assert after['accepted_sequence'] == accepted['accepted_sequence']
        return CaseResult('succeeded', ('bounded_resync', 'ordered_gap_free', 'same_snapshot'))


    async def interrupted_journey(self, case, lot):
        notice_case = case == 'outbox_replay_duplicate_notice'
        dependency = 'COMMUNICATIONS' if notice_case else 'ORDERS'
        keys = [dependency + suffix for suffix in ('_URL', '_API_URL')]
        if not notice_case:
            keys.append('BT_ORDERS_URL')
        upstream = next((self.replica.env[key] for key in reversed(keys)
                         if key in self.replica.env), None)
        if upstream is None:
            raise MissingCapability('native_dependency_url:' + dependency.lower())
        local_url(upstream)
        path = ('/internal/v1/events' if notice_case else '/internal/v2/commitments'
                if case == 'timeout_pending' else '/internal/v2/allocations')

        def matches(method, target, body):
            if method != 'POST' or target != path:
                return False
            return (body.get('subject') == lot['id'] and
                    body.get('type') == 'auction.bid-accepted.v1') if notice_case else (
                        body.get('source_id') == lot['id'])

        saved = {key: self.replica.env.get(key) for key in keys}
        submission = None
        def pause():
            # Suspend only our child before its dependency timeout can write an
            # acknowledgement. The original process remains available for reads.
            self.replica.process.send_signal(signal.SIGSTOP)

        async with ResponseBarrier(upstream, matches,
                on_commit=None if case == 'timeout_pending' else pause) as barrier:
            try:
                self.replica.env.update(dict.fromkeys(keys, barrier.url))
                await self.replica.restart()
                body = await self.command(lot, 0)
                key = str(uuid4())
                if case == 'timeout_pending':
                    submission = asyncio.create_task(self.request('auction', 'POST',
                        f"/v1/auctions/{lot['id']}/bids", actor=0, body=body, key=key,
                        replica=1, expected=(200, 201, 202, 503)))
                    await asyncio.wait_for(barrier.committed.wait(), 10)
                    await submission
                    pending = await self.request('auction', 'GET',
                        '/v1/auction-operations/by-key/' + key, actor=0, replica=0)
                    assert pending['status'] == 'pending'
                    assert pending['accepted_sequence'] == 0
                    assert await self.history(lot['id'], 0) == []
                    barrier.release.set()
                    recovered = await self.submit(lot, 0, body, key, replica=1)
                    assert recovered['status'] == 'succeeded'
                    assert recovered['operation_id'] == pending['operation_id']
                    assert recovered['accepted_sequence'] == 1
                    assert await self.submit(lot, 0, body, key, replica=0) == recovered
                    assert len(await self.history(lot['id'], 0)) == 1
                    return CaseResult('pending', ())
                if notice_case:
                    submission = asyncio.create_task(self.submit(lot, 0, body, key, replica=1))
                    await asyncio.wait_for(barrier.committed.wait(), 40)
                    accepted = await self.request('auction', 'GET',
                        '/v1/auction-operations/by-key/' + key, actor=0, replica=0)
                    self.operations.append(str(UUID(accepted['operation_id'])))
                else:
                    accepted = await self.submit(lot, 0, body, key, replica=1)
                assert accepted['status'] == 'succeeded'
                # A successful upstream response is held before the child can
                # mark delivery or allocation complete. No durable row is edited.
                await asyncio.wait_for(barrier.committed.wait(), 40)
                if notice_case:
                    sample = await self.read_notice(lot, 0, accepted, time.monotonic())
                    assert not sample.error
                    binding = await self.notice_binding(lot, 0, accepted['accepted_sequence'])
                    assert binding is not None
                else:
                    close = await self.request('auction', 'GET',
                        f"/v1/auctions/{lot['id']}/fixed-end-result", replica=0)
                    assert close['status'] == 'allocation_pending' and close['winner']
                    history = await self.history(lot['id'], 0)
                    assert len(history) == 1
                    assert close['winner'] == history[0]['bidder']
                    assert close['closing_minor'] == history[0]['amount_minor']
                await self.replica.stop()
                barrier.release.set()
                if notice_case:
                    replay = await barrier.replay()
                    assert replay.status_code in (200, 201, 202)
                    assert await self.notice_binding(lot, 0, accepted['accepted_sequence']) == binding
                    page = await self.request('communications', 'GET', '/v1/bid-notices?limit=100', actor=0)
                    rows = [row for row in page['items'] if row['auction_id'] == lot['id']
                            and row['sequence'] == accepted['accepted_sequence']
                            and row['kind'] == 'bid_accepted']
                    assert len(rows) == 1 and rows[0]['id'] == binding[0]
                    inbox = await self.request('communications', 'GET', '/v1/inbox?limit=50', actor=0)
                    assert len([row for row in inbox['items'] if row['id'] == binding[1]]) == 1
                    return CaseResult('succeeded', ('one_notice_per_recipient_event', 'durable_inbox'))
                await self.replica.start()
                for _ in range(80):
                    current = await self.request('auction', 'GET',
                        f"/v1/auctions/{lot['id']}/fixed-end-result", replica=0)
                    if current['status'] == 'closed':
                        break
                    await asyncio.sleep(.5)
                else:
                    raise MissingCapability('allocation_recovery_deadline')
                assert current['winner'] == close['winner']
                assert current['closing_minor'] == close['closing_minor']
                allocation = await self.load_allocation(lot['id'], 0, lot=lot)
                await self.replica.restart()
                assert await self.load_allocation(lot['id'], 0, lot=lot) == allocation
                assert await self.submit(lot, 0, body, key, replica=1) == accepted
                assert len(await self.history(lot['id'], 0)) == 1
                return CaseResult('succeeded', ('one_winner', 'one_order', 'same_watch_commitment'))
            finally:
                barrier.release.set()
                if submission is not None:
                    if not submission.done():
                        submission.cancel()
                    await asyncio.gather(submission, return_exceptions=True)
                for key, value in saved.items():
                    if value is None:
                        self.replica.env.pop(key, None)
                    else:
                        self.replica.env[key] = value
                await self.replica.restart()

    async def maximum_journey(self, lot):
        async def ceiling(actor, amount):
            current = await self.snapshot(lot['id'])
            body = await self.command(current, actor, amount)
            result = await self.request('auction', 'POST',
                f"/v1/auctions/{lot['id']}/maximum", actor=actor, body=body)
            assert result['status'] == 'succeeded'
            return result

        await ceiling(0, 450000)
        current = await self.snapshot(lot['id'])
        assert current['current_minor'] == 400000
        body = await self.command(current, 1, 420000)
        submitted = time.monotonic()
        accepted = await self.submit(current, 1, body, str(uuid4()))
        assert accepted['status'] == 'succeeded' and accepted['current_minor'] == 430000
        notice = await self.observe_notice(current, 1, accepted, submitted)
        assert not notice.error and notice.elapsed_ms <= 30000
        current = await self.snapshot(lot['id'])
        body = await self.command(current, 1, 445000)
        accepted = await self.submit(current, 1, body, str(uuid4()))
        assert accepted['status'] == 'succeeded' and accepted['current_minor'] == 445000
        # A later equal ceiling wins because a full response step cannot fit.
        await ceiling(0, 470000)
        await ceiling(1, 470000)
        snapshot = await self.request('auction', 'GET', f"/v2/auctions/{lot['id']}", owner_read=True)
        history = await self.request('auction', 'GET',
            f"/v2/auctions/{lot['id']}/history?after_sequence=0&limit=100", owner_read=True)
        assert snapshot['bidding_version'] == 'full-step.v2'
        assert history['version'] == 2 and not history['has_more']
        rows = history['items']
        assert all(row['rules_version'] == 'full-step.v2' for row in rows)
        assert [row['sequence'] for row in rows] == list(range(1, len(rows) + 1))
        assert all(right['amount_minor'] > left['amount_minor'] for left, right in zip(rows, rows[1:]))
        assert rows[-1]['amount_minor'] == 470000
        assert rows[-1]['bidder'] != rows[-2]['bidder']
        def redacted(value):
            if isinstance(value, dict):
                assert not ({'maxima', 'maximum_minor', 'maximum', 'bidder_id', 'leader_id',
                             'actor_id', 'fee_quote_id', 'active', 'private_state'} & value.keys())
                for item in value.values():
                    redacted(item)
            elif isinstance(value, list):
                for item in value:
                    redacted(item)
        redacted(snapshot)
        redacted(history)
        assert all(set(row) == {'sequence', 'bidder', 'amount_minor', 'automatic',
                                'received_at', 'rules_version'} for row in rows)
        assert set(snapshot) == {
            'id', 'listing_id', 'currency', 'opening_minor', 'current_minor',
            'next_minimum_minor', 'increment_bands', 'starts_at', 'ends_at', 'server_time',
            'revision', 'accepted_sequence', 'rules_version', 'extension_policy',
            'high_value_minor', 'reserve_set', 'leader', 'status', 'end_version',
            'close_version', 'mode', 'bidding_version', 'first_bid_committed',
            'listing_revision', 'scheduled_ends_at'}
        return CaseResult('succeeded', ('no_private_fields', 'full_step_v2'))

    async def current_commitment(self, order_id):
        path = f'/internal/v3/orders/{UUID(order_id)}/commitment'
        upstream = self.replica.env.get('ORDERS_API_URL',
            self.replica.env.get('ORDERS_URL', 'http://127.0.0.1:8104'))
        local_url(upstream)
        service_key = self.replica.env.get('BT_SERVICE_AUTH_PRIVATE_KEY')
        if not service_key:
            raise MissingCapability('commitment_service_authorization')
        now = int(time.time())
        token = jwt.encode({'sub': 'auction', 'type': 'service',
            'iss': self.replica.env.get('BT_AUTH_ISSUER', 'beirut-time-identity'),
            'aud': 'orders', 'iat': now, 'exp': now + 60}, service_key, algorithm='RS256')
        response = await self.client.get(upstream.rstrip('/') + path,
            headers={'Authorization': 'Bearer ' + token}, timeout=5)
        if response.status_code != 200 or len(response.content) > 2_000_000:
            raise MissingCapability('current_commitment_unavailable')
        return response.json()

    async def load_allocation(self, identifier, winner, *, lot=None):
        receipts = [await self.request('auction', 'GET',
            f'/v1/auctions/{identifier}/my-fixed-end-result', actor=winner, replica=replica)
            for replica in range(2)]
        assert receipts[0] == receipts[1]
        receipt = receipts[0]
        assert receipt['won'] and receipt['order_id']
        order = (await self.request('orders', 'GET', '/v1/orders/' + receipt['order_id'],
                                    actor=winner))['order']
        assert order['buyer_id'] == self.subjects[winner]
        assert order['listing_id'] == (lot or self.lots['bidders'])['listing_id']
        orders = await self.request('orders', 'GET', '/v1/orders', actor=winner)
        matches = [row for row in orders['items'] if row['watch_id'] == order['watch_id']]
        assert len(matches) == 1 and matches[0]['id'] == order['id'] == receipt['order_id']
        watch = await self.request('orders', 'GET',
                                   f"/v1/watches/{order['watch_id']}/availability", actor=winner)
        assert watch['watch_id'] == order['watch_id'] and watch['listing_id'] == order['listing_id']
        assert watch['status'] in ('reserved', 'allocated', 'sold')
        commitment = await self.current_commitment(order['id'])
        assert commitment['order_id'] == order['id'] == receipt['order_id']
        assert commitment['watch_id'] == order['watch_id']
        assert commitment['buyer_id'] == order['buyer_id'] == self.subjects[winner]
        assert commitment['current'] is True
        assert commitment['state'] == order['state'] and commitment['state'] != 'expired_released'
        binding = {key: commitment[key] for key in
                   ('order_id', 'watch_id', 'buyer_id', 'current', 'state')}
        return receipt, order['id'], order['watch_id'], watch, binding

    async def recover_load(self, dataset):
        lot = self.lots.get('bidders')
        if not lot or len(self.acknowledged) != dataset.bidders:
            raise MissingCapability('complete_acknowledged_bidder_load')
        if not self.mid_load_restarted or not self.owned_acknowledged:
            raise MissingCapability('owned_replica_acknowledged_load_restart')
        if dataset.bidders > 1:
            assert set(self.acknowledged_processes.values()) == {0, 1}
        identifier = lot['id']
        before = await self.history(identifier, 0)
        sequences = sorted(result['accepted_sequence'] for _, _, result in self.acknowledged)
        assert sequences == list(range(1, dataset.bidders + 1))
        assert [row['sequence'] for row in before] == sequences
        assert await self.history(identifier, 1) == before
        snapshots = [await self.snapshot(identifier, replica) for replica in range(2)]
        assert {k: v for k, v in snapshots[0].items() if k != 'server_time'} == {
            k: v for k, v in snapshots[1].items() if k != 'server_time'}
        for actor, key, result in self.acknowledged:
            for replica in range(2):
                recovered = await self.request('auction', 'GET',
                    '/v1/auction-operations/by-key/' + key, actor=actor, replica=replica)
                assert recovered == result
        # Wait for the real fixed deadline and the running close worker.
        for _ in range(1500):
            result = await self.request('auction', 'GET',
                f'/v1/auctions/{identifier}/fixed-end-result', replica=0)
            if result.get('winner') and result.get('status') == 'closed':
                break
            await asyncio.sleep(1)
        else:
            raise MissingCapability('durable_load_winner_before_deadline')
        assert result['winner'] == before[-1]['bidder']
        assert result['closing_minor'] == before[-1]['amount_minor']
        winner = max(self.acknowledged, key=lambda row: row[2]['accepted_sequence'])[0]
        allocation = await self.load_allocation(identifier, winner)
        await self.replica.restart()
        assert await self.load_allocation(identifier, winner) == allocation
        other = await self.request('auction', 'GET',
            f'/v1/auctions/{identifier}/fixed-end-result', replica=1)
        assert other == result
        assert await self.history(identifier, 0) == before
        assert await self.history(identifier, 1) == before
        return CaseResult('succeeded', ('all_acknowledged_retained', 'same_sequence'))
