"""Fresh, explicitly synthetic course walkthrough against real composed services.

Run accounts, bootstrap the registered operator with Identity's local CLI, then
run onboard and publication. No SQL grants, request stubs or fabricated outcomes.
Local session evidence is ignored and mode 0600; public evidence omits credentials.
"""
import argparse
import base64
import time
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from hashlib import sha256
import selectors
import subprocess
import shutil
import stat
import sys
import tempfile
import threading
from uuid import UUID, uuid4

import httpx

ROOT = Path(__file__).resolve().parents[3]
STATE = ROOT / 'artifacts/accept'
PASSWORD = 'Course-demo-passphrase!'
ACCOUNTS = ['operator', 'seller', 'dealer', 'brand', 'colleague', 'buyer-a', 'buyer-b']


PUBLICATION_FAILURE_PREFIX = b'BT_PUBLICATION_FAILURE_V1 '
PUBLICATION_CATEGORIES = frozenset({
    'timeout', 'network', 'saturated', 'circuit_open', 'upstream',
    'identity_unavailable', 'publication_review_pending', 'pricing_unavailable',
    'orders_unavailable', 'registration_pending',
})
PUBLICATION_UPSTREAMS = frozenset({'identity', 'pricing', 'orders'})
PUBLICATION_STDERR_LIMIT = 4096


def publication_failure(stderr_tail):
    for line in reversed(stderr_tail.splitlines()):
        if not line.startswith(PUBLICATION_FAILURE_PREFIX) or len(line) > 256:
            continue
        try:
            value = json.loads(line[len(PUBLICATION_FAILURE_PREFIX):])
        except (ValueError, RecursionError):
            continue
        if not isinstance(value, dict) or set(value) != {'category', 'http_status', 'upstream'}:
            continue
        category, status, upstream = value['category'], value['http_status'], value['upstream']
        if not isinstance(category, str) or category not in PUBLICATION_CATEGORIES:
            continue
        if upstream is not None and (not isinstance(upstream, str) or upstream not in PUBLICATION_UPSTREAMS):
            continue
        if status is not None and (type(status) is not int or not 100 <= status <= 599):
            continue
        return value
    return None


def run_publication_child(command, *, cwd, env, timeout=120):
    # Keep only a bounded in-memory stderr tail for the structured failure line.
    # Never print, persist or buffer stdout; send it directly to the null sink.
    tail = bytearray()
    deadline = time.monotonic() + timeout
    with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as child:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stderr, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        return None, bytes(tail)
                    chunk = os.read(child.stderr.fileno(), PUBLICATION_STDERR_LIMIT)
                    if not chunk:
                        break
                    tail.extend(chunk)
                    del tail[:-PUBLICATION_STDERR_LIMIT]
            return child.wait(timeout=max(0, deadline - time.monotonic())), bytes(tail)
        except subprocess.TimeoutExpired:
            return None, bytes(tail)
        finally:
            if child.poll() is None:
                child.kill()


PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
# Base64 plus the command envelope must fit the gateway's 1 MiB JSON budget.
POSSESSION_PHOTO_MAX = 750 * 1024


def read_private_file(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        facts = os.fstat(stream.fileno())
        if not stat.S_ISREG(facts.st_mode) or facts.st_mode & 0o077 or facts.st_uid != os.geteuid():
            raise ValueError('Use an owner-only regular evidence file')
        content = stream.read(limit + 1)
        if len(content) > limit:
            raise ValueError('Private input exceeds its byte limit')
        return content


class Walkthrough:
    def __init__(self, origin, backend='container', run_dir=None):
        if backend == 'native' and run_dir is None:
            raise ValueError('Native execution requires --run-dir')
        self.backend = backend
        self.run_dir = Path(run_dir).resolve() if run_dir else STATE
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.origin = origin.rstrip('/')
        self.path = self.run_dir / 'walkthrough.local.json'
        if self.path.exists() and self.path.stat().st_mode & 0o077:
            raise ValueError('Walkthrough state must be private (0600)')
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.evidence = []
        self.phase = None
        self.positions = {}
        self.reconciling = False
        self.journal_lock = threading.RLock()
        self.client = httpx.Client(base_url=self.origin, headers={'Origin':self.origin}, timeout=30)

    def save(self):
        descriptor, temporary = tempfile.mkstemp(dir=self.run_dir)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(self.state, stream, indent=2)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def native_plan(self, service, arguments, extra=None):
        """Consume native-v1.json: {schema_version: 1, services: {name: {env}}}.

        The private 0600 file supplies owning runtime settings and provider URLs.
        Versioned packages must be prepared at run-dir/domain-contracts beforehand.
        No provisioning or service lifecycle operation is performed here.
        """
        config_path = self.run_dir / 'native-v1.json'
        if config_path.stat().st_mode & 0o077:
            raise ValueError('Native configuration must be private (0600)')
        config = json.loads(config_path.read_text())
        if config.get('schema_version') != 1:
            raise ValueError('Unsupported native configuration')
        configured = config['services'][service]['env']
        if not isinstance(configured, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in configured.items()
        ):
            raise ValueError('Native environment must contain string settings')
        contracts = self.run_dir / 'domain-contracts'
        if not (contracts / 'bt_contracts').is_dir():
            raise ValueError('Prepared versioned contracts are required')
        source = ROOT / 'services' / service
        paths = [source, source / 'runtime', contracts]
        paths += [ROOT / 'packages' / name / 'src'
                  for name in ('runtime', 'contracts-core', 'bulkheads', 'events')]
        env = {key: os.environ[key] for key in ('PATH', 'LANG') if key in os.environ}
        env.update(configured)
        env.update(extra or {})
        env.update({
            'PYTHONPATH': os.pathsep.join(map(str, paths)),
            'PYTHONDONTWRITEBYTECODE': '1',
            'BT_MODULES_PATH': str(source / 'modules'),
            'BT_SERVICE_NAME': service,
            'TMPDIR': str(self.run_dir),
        })
        return [sys.executable, '-m', *arguments], env

    def execute_publication(self, command, env):
        status, stderr_tail = run_publication_child(command, cwd=self.run_dir, env=env)
        self.evidence.append({'transport': self.backend, 'status': 'timeout' if status is None else status})
        if status == 0:
            return
        diagnostic = publication_failure(stderr_tail)
        record = {
            'exit_code': status,
            'timed_out': status is None,
            'exception_type': ('TimeoutExpired' if status is None else
                               'PublicationUnavailable' if diagnostic else 'ChildProcessError'),
            'failure_category': diagnostic['category'] if diagnostic else ('timeout' if status is None else None),
            'http_status': diagnostic['http_status'] if diagnostic else None,
            'upstream': diagnostic['upstream'] if diagnostic else None,
        }
        descriptor, _ = tempfile.mkstemp(prefix='publication-child-', suffix='.json', dir=self.run_dir)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(record, stream)
        if status is None:
            raise RuntimeError('Local command timed out; connected proof incomplete') from None
        raise RuntimeError('Local command failed; private diagnostic review required')

    def execute(self, command, env):
        try:
            result = subprocess.run(command, cwd=self.run_dir, env=env,
                                    capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            self.evidence.append({'transport': self.backend, 'status': 'timeout'})
            raise RuntimeError('Local command timed out; connected proof incomplete') from None
        self.evidence.append({'transport': self.backend, 'status': result.returncode})
        if result.returncode:
            raise RuntimeError('Local command failed; private diagnostic review required')

    def bootstrap(self):
        if self.backend != 'native':
            raise ValueError('Bootstrap requires native execution')
        def fresh_authority():
            self.state.get('accounts', {}).pop('operator', None)
            self.client.cookies.clear()
            self.login('operator')
            return 'identity.businesses.manage' in self.state['accounts']['operator']['principal']['permissions']

        # Current authority reconciles a committed command even without a checkpoint.
        if fresh_authority():
            self.state['operator_bootstrapped'] = True
            self.state.pop('operator_bootstrap_pending', None)
            self.save()
            return
        if self.state.get('operator_bootstrap_pending') or self.state.get('operator_bootstrapped'):
            raise RuntimeError('Operator authority unresolved; connected proof incomplete')
        command, env = self.native_plan('identity', [
            'service_app.bootstrap_operator', '--email', 'operator.s1@example.test',
            '--reason', 'Authorize initial synthetic demonstration operator'])
        self.state['operator_bootstrap_pending'] = True
        self.save()
        self.execute(command, env)
        if not fresh_authority():
            raise RuntimeError('Operator authority unresolved; connected proof incomplete')
        self.state['operator_bootstrapped'] = True
        self.state.pop('operator_bootstrap_pending', None)
        self.save()

    def run_phase(self, phase):
        """Resume the private call journal; completed phases are checkpoints only.

        Mutation receipts reconcile an interrupted sequence; reads always reach
        current services. Completed phases require current reads or remain
        incomplete. Pending calls retain their exact payload and operation key.
        Use one walkthrough process per run directory.
        """
        self.reconciling = phase in self.state.get('completed_phases', [])
        self.phase, self.positions = phase, {}
        try:
            if self.reconciling and phase != 'bootstrap':
                for name in list(self.state.get('accounts', {})):
                    self.state['accounts'].pop(name)
                    self.client.cookies.clear()
                    self.login(name)
            if self.reconciling and phase == 'contacts':
                for name in ['seller', 'dealer', 'brand', 'buyer-a', 'buyer-b']:
                    contact = self.call('identity', 'GET', '/v1/contacts', name)
                    if not contact['email_verified']:
                        raise RuntimeError('Current contact unverified; connected proof incomplete')
            elif self.reconciling and phase not in ('accounts', 'bootstrap', 'publication'):
                self.reconcile_phase(phase)
            else:
                getattr(self, phase)()
            if not self.reconciling:
                self.state.setdefault('completed_phases', []).append(phase)
            self.save()
        finally:
            self.phase = None
            self.reconciling = False

    def reconcile_phase(self, phase):
        """Read current prerequisites without replaying completed mutations."""
        if phase == 'onboard':
            operator = self.state['accounts']['operator']
            assert 'identity.businesses.manage' in operator['principal']['permissions']
            required = {'business.stock.write', 'business.jobs.write',
                        'business.records.read', 'business.staff.manage'}
            for kind in ('dealer', 'brand'):
                identifier = self.state['businesses'][kind]['id']
                business = self.call('identity', 'GET', '/v1/businesses/' + identifier)
                assert business['state'] == 'active' and business['kind'] == kind
                members = self.call('identity', 'GET',
                                    '/v1/businesses/' + identifier + '/memberships', 'operator')
                for name in [kind] + (['colleague'] if kind == 'dealer' else []):
                    subject = self.state['accounts'][name]['account']['id']
                    member = next(row for row in members['items'] if row['subject_id'] == subject)
                    assert member['state'] == 'active' and required <= set(member['capabilities'])
            application = self.call('identity', 'GET', '/v1/private-seller/applications/me', 'seller')['application']
            assert application['id'] == self.state['application']['id']
            assert application['status'] == 'approved'
        elif phase in ('auctions', 'bids'):
            for auction in self.state['auctions'].values():
                identifier = auction.get('auction_id') or auction.get('resource_id') or auction['auction']['id']
                current = self.call('auction', 'GET', '/v1/auctions/' + identifier)
                assert current['status'] in ('scheduled', 'live', 'ended')
            if phase == 'bids':
                proof = self.state['bid_proof']
                current = self.call('auction', 'GET', '/v1/auctions/' + proof['auction_id'])
                assert current['current_minor'] == proof['results'][-1]['current_minor']
                history = self.call('auction', 'GET', '/v1/auctions/' + proof['auction_id'] + '/history')
                assert history == proof['history']
        elif phase == 'purchases':
            reservation = self.state['reservation']
            current = self.call('orders', 'GET', '/v1/orders/' + reservation['resource_id'], reservation['winner'])['order']
            assert current['state'] == 'awaiting_payment'
            assert current['quote_id'] == reservation['quote']['id']
            assert current['total_minor'] == reservation['quote']['payable_minor']
        elif phase == 'directory':
            public = self.call('service-operations', 'GET', '/v1/directory/businesses')
            assert {row['organization_id'] for row in public['items']} == {
                row['id'] for row in self.state['businesses'].values()}
            current = self.call('service-operations', 'GET', '/v1/directory/choices/current', 'buyer-a')
            assert current['choice'] == self.state['service_choice']
        elif phase == 'request':
            raise RuntimeError('Current phase reconciliation unavailable; connected proof incomplete')
        else:
            raise ValueError('Unknown completed phase')

    def all(self):
        phases = ['accounts']
        if self.backend == 'native':
            phases.append('bootstrap')
        phases += ['onboard', 'contacts', 'publication', 'auctions', 'bids',
                   'purchases', 'directory', 'request']
        for phase in phases:
            self.run_phase(phase)
        print('First-sprint walkthrough only; financial and work acceptance remain unverified.')

    def call(self, service, method, route, actor=None, body=None, *, headers=None, expected=(200,201), content=None, operation=None, durable=True, raw=False):
        if raw and method != 'GET':
            raise ValueError('A binary response must be read-only')
        # Authentication always obtains current credentials and is not replayed.
        authentication = service == 'identity' and route in (
            '/v1/accounts/login', '/v1/accounts/refresh')
        entry = None
        h = dict(headers or {})
        if self.phase and not authentication and durable and method.upper() not in ('GET', 'HEAD', 'OPTIONS'):
            if content is not None:
                raise ValueError('Binary calls require a separate durable upload contract')
            with self.journal_lock:
                sequence = (service, method, route, actor)
                position = self.positions.get(sequence, 0)
                self.positions[sequence] = position + 1
                key = json.dumps([self.phase, *sequence, operation if operation is not None else position])
                journal = self.state.setdefault('call_journal', {})
                entry = journal.get(key)
                if entry is None:
                    if self.reconciling:
                        raise RuntimeError('Unrecorded mutation during reconciliation; connected proof incomplete')
                    entry = {'service': service, 'method': method, 'route': route,
                             'body': body, 'headers': h, 'operation_id': str(uuid4())}
                    journal[key] = entry
                    self.save()
                if (entry['service'], entry['method'], entry['route']) != (service, method, route):
                    raise RuntimeError('Walkthrough sequence changed; reconciliation required')
                if 'response' in entry:
                    assert entry['status'] in expected
                    return entry['response']
                body, h = entry['body'], dict(entry['headers'])
                h['Idempotency-Key'] = entry['operation_id']
        h.setdefault('Idempotency-Key', str(uuid4()))
        if actor:
            h['Authorization'] = 'Bearer ' + self.state['accounts'][actor]['access_token']
        response = self.client.request(method, f'/api/web/v1/{service}'+route, json=body, content=content, headers=h)
        self.evidence.append({'service':service,'method':method,'route':route.split('?')[0],'status':response.status_code,'request_id':response.headers.get('x-request-id')})
        if response.status_code == 401 and actor:
            # Current authority can invalidate even an unexpired access token.
            self.client.cookies.clear()
            refresh_cookie = self.state['accounts'][actor].get('refresh_cookie')
            if refresh_cookie:
                self.client.cookies.set('bt_refresh', refresh_cookie)
                result = self.call('identity', 'POST', '/v1/accounts/refresh')
            else:
                result = self.call('identity', 'POST', '/v1/accounts/login',
                                   body={'email':actor+'.s1@example.test','password':PASSWORD})
            result['refresh_cookie'] = self.client.cookies.get('bt_refresh')
            self.state['accounts'][actor] = result
            self.save()
            h['Authorization'] = 'Bearer ' + result['access_token']
            response = self.client.request(method, f'/api/web/v1/{service}'+route, json=body, content=content, headers=h)
            self.evidence.append({'service':service,'method':method,'route':route.split('?')[0],'status':response.status_code,'request_id':response.headers.get('x-request-id')})
        assert response.status_code in expected, (service,method,route.split('?')[0],response.status_code)
        if raw:
            return response
        result = response.json()
        if entry is not None:
            with self.journal_lock:
                entry.update(response=result, status=response.status_code)
                self.save()
        return result

    def login(self, name):
        existing=self.state.get('accounts',{}).get(name)
        if existing:
            payload=existing['access_token'].split('.')[1]
            expiry=json.loads(base64.urlsafe_b64decode(payload+'='*((-len(payload))%4)))['exp']
            # Client-side expiry is only a refresh hint; every service still
            # verifies the signature and fresh current Identity authority.
            if expiry > time.time()+30:
                return existing
            if existing.get('refresh_cookie'):
                self.client.cookies.clear()
                self.client.cookies.set('bt_refresh',existing['refresh_cookie'])
                result=self.call('identity','POST','/v1/accounts/refresh')
                result['refresh_cookie']=self.client.cookies.get('bt_refresh')
                self.state['accounts'][name]=result
                self.save()
                return result
        result = self.call('identity','POST','/v1/accounts/login',body={'email':name+'.s1@example.test','password':PASSWORD})
        result['refresh_cookie']=self.client.cookies.get('bt_refresh')
        self.state.setdefault('accounts',{})[name] = result
        self.save()
        return result

    def accounts(self):
        for name in ACCOUNTS:
            if name not in self.state.get('accounts',{}):
                result = self.call('identity','POST','/v1/accounts/register',body={'email':name+'.s1@example.test','password':PASSWORD,'display_name':'Sample '+name.title()}, expected=(201,409), operation='register:' + name)
                if 'account' in result:
                    self.state.setdefault('accounts',{})[name] = result
                    self.save()
            self.login(name)

    def onboard(self):
        operator = self.login('operator')
        assert 'identity.businesses.manage' in operator['principal']['permissions'], 'Run Identity first-operator CLI first'
        self.state.setdefault('businesses',{})
        for kind in ['dealer','brand']:
            self.login(kind)
            if kind not in self.state['businesses']:
                business = self.call('identity','POST','/v1/businesses','operator',{
                    'legal_name':'Sample '+kind.title()+' Demonstration','public_name':'Sample '+kind.title(),
                    'kind':kind,'capabilities':['sales','servicing']+(['customization'] if kind=='brand' else []),
                    'assurance_reference':'SAMPLE-COURSE-ONBOARDING','reason':'Synthetic course business explicitly onboarded','sample':True}, operation='business:' + kind)
                self.state['businesses'][kind]=business
                self.save()
            business = self.state['businesses'][kind]
            for name in [kind]+(['colleague'] if kind=='dealer' else []):
                self.call('identity','POST','/v1/memberships','operator',{
                    'business_id':business['id'],'subject_id':self.state['accounts'][name]['account']['id'],
                    'capabilities':['business.stock.write','business.jobs.write','business.records.read','business.staff.manage'],
                    'qualifications':['Sample authorized course colleague'],'intervention_scope':'Synthetic demonstration records only',
                    'reason':'Authorize sample business colleague for course demonstration'}, operation='membership:' + kind + ':' + name)
            self.login(kind)
        self.login('seller')
        if 'application' not in self.state:
            application=self.call('identity','POST','/v1/private-seller/applications','seller',{
                'identity_name':'DEMO Sample Seller','contact':'seller.s1@example.test','payout_reference':'DEMO-SELLER-S1',
                'identity_evidence':'DEMO: synthetic identity reference only','possession_evidence':'DEMO: illustrative sample watch possession','expected_revision':0})['application']
            self.state['application']=application
            self.save()
        if 'review' not in self.state:
            application=self.state['application']
            review=self.call('identity','POST','/v1/private-reviews','operator',{
                'application_id':application['id'],'reviewer_id':operator['account']['id'],'reason':'Review synthetic course private seller evidence'})
            self.state['review']=review
            self.save()
        if 'verdict' not in self.state:
            self.state['verdict']=self.call('identity','POST','/v1/private-reviews/'+self.state['review']['id']+'/verdict','operator',{
                'revision':self.state['review']['revision'],'application_revision':self.state['application']['revision'],
                'state':'approved','reason':'Synthetic identity and possession reviewed; not physical watch authentication'})
            self.save()
        self.login('seller')
        print('Official sample dealer/brand, scoped colleagues and reviewed private seller ready.')

    def contacts(self):
        for name in ['seller','dealer','brand','buyer-a','buyer-b']:
            self.login(name)
            contact=self.call('identity','GET','/v1/contacts',name)
            if contact['email_verified']:
                continue
            email=name+'.s1@example.test'
            proof=self.call('identity','POST','/v1/accounts/reauthenticate',name,{'password':PASSWORD,'purpose':'contact-change','binding':'email:'+email})
            challenge=self.call('identity','POST','/v1/contacts/challenges',name,{'channel':'email','recipient':email,'revision':contact['revision'],'proof':proof['proof']})
            code=self.call('identity','GET','/v1/contacts/challenges/'+challenge['id']+'/sample-code',name)
            verified=self.call('identity','POST','/v1/contacts/challenges/'+challenge['id']+'/verify',name,{'code':code['code']})
            assert verified['email_verified'] and verified['email_sample']
        print('Sample contact verification completed through password reauthentication and one-use codes.')

    def auctions(self):
        self.login('seller'); self.login('dealer')
        self.state.setdefault('auctions',{})
        for reference,name in [('DEMO-WATCH-01','seller'),('DEMO-WATCH-03','seller')]:
            if reference in self.state['auctions']:
                continue
            listing=next(row for row in self.state['listings'] if row['facts']['reference']==reference)
            org='?organization_id='+self.state['businesses']['dealer']['id'] if name=='dealer' else ''
            now=datetime.now(timezone.utc)
            result=self.call('auction','POST','/v1/auctions'+org,name,{
                'listing_id':listing['id'],'currency':'USD','opening_minor':10000,
                'increment_bands':[{'from_minor':0,'step_minor':1000}],
                'starts_at':(now+timedelta(seconds=3) if reference=='DEMO-WATCH-01' else now+timedelta(hours=1)).isoformat(),
                'ends_at':(now+timedelta(hours=2)).isoformat()}, operation='auction:' + reference)
            assert result['status']=='succeeded',result
            self.state['auctions'][reference]=result
            self.save()
        print('Real private open and scheduled auctions created with Orders sale fences.')

    def quote(self, name, subject, revision, amount, purpose='bid', source='sample'):
        body={'subject_id':subject,'subject_revision':revision,'purpose':purpose,'source':source,'schedule_id':'usd-v2','currency':'USD','price_minor':amount}
        quote=self.call('pricing','POST','/v1/quotes',name,body)
        reviewed=self.call('pricing','POST','/v1/quotes/'+quote['id']+'/review',name,{**body,'quote_revision':quote['revision'],'payable_minor':quote['payable_minor']})
        assert reviewed['reviewed_at']
        return reviewed

    def wait_for_live(self, auction_id):
        for attempt in range(10):
            lot = self.call('auction', 'GET', '/v1/auctions/' + auction_id, durable=False)
            if lot['status'] == 'live':
                return
            if lot['status'] != 'scheduled':
                raise RuntimeError('Auction is not live')
            if attempt < 9:
                time.sleep(1)
        raise RuntimeError('Auction remains scheduled; connected proof incomplete')

    def bids(self):
        for name in ['buyer-a','buyer-b']:
            self.login(name)
        auction=self.state['auctions']['DEMO-WATCH-01']
        # The call journal resumes an interrupted competition with the same keys.
        # Equal-ceiling provider compatibility remains deferred to connected proof.
        auction_id=auction.get('auction_id') or auction.get('resource_id')
        if not auction_id:
            auction_id=auction['auction']['id']
        self.wait_for_live(auction_id)
        expected_prices=[10000,11000,12000,16000,20000,20000]
        steps=[('buyer-a','bids',10000),('buyer-b','bids',11000),('buyer-a','maximum',20000),('buyer-b','maximum',15000),('buyer-b','maximum',20000),('buyer-b','maximum',22000)]
        leaders=['buyer-a','buyer-b','buyer-a','buyer-a','buyer-b','buyer-b']
        results=[]
        participants=set()
        before_raise=self.state.get('bid_history_before_raise')
        recorded = []
        for key in self.state.get('call_journal', {}):
            fields = json.loads(key)
            if fields[0] == 'bids' and fields[1] == 'auction' and fields[2] == 'POST':
                recorded.append((fields[3], fields[4], fields[5]))
        counts = {}
        furthest = -1
        for index, (name, kind, _) in enumerate(steps):
            route = f'/v1/auctions/{auction_id}/{kind}'
            sequence = (route, name)
            position = counts.get(sequence, 0)
            counts[sequence] = position + 1
            if (route, name, position) in recorded:
                furthest = index
        for index,((name,kind,amount),price,leader) in enumerate(zip(steps,expected_prices,leaders)):
            if index==len(steps)-1 and before_raise is None:
                before_raise=self.call('auction','GET',f'/v1/auctions/{auction_id}/history')
                assert before_raise['has_more'] is False
                self.state['bid_history_before_raise'] = before_raise
                self.save()
            lot=self.call('auction','GET','/v1/auctions/'+auction_id)
            quote=self.quote(name,auction_id,lot['revision'],amount)
            result=self.call('auction','POST',f'/v1/auctions/{auction_id}/{kind}',name,{'amount_minor':amount,'fee_quote_id':quote['id'],'expected_revision':lot['revision']})
            assert result['status']=='succeeded',result
            participants.add(name)
            if index < furthest:
                continue
            current=self.call('auction','GET','/v1/auctions/'+auction_id)
            assert current['current_minor']==price,current
            participants.add(name)
            for buyer in participants:
                own=self.call('auction','GET','/v1/my-bids',buyer)
                entry=next(row for row in own['items'] if row['auction_id']==auction_id)
                assert entry['my_status']==('leading' if buyer==leader else 'outbid')
            results.append({'actor':name,'kind':kind,'current_minor':price,'revision':current['revision']})
        history=self.call('auction','GET',f'/v1/auctions/{auction_id}/history')
        assert history['has_more'] is False
        assert history['items']==before_raise['items'], 'Ceiling-only raise created a public bid'
        assert 'maximum_minor' not in json.dumps(history) and 'maxima' not in json.dumps(history)
        self.state['bid_proof']={'auction_id':auction_id,'results':results,'history':history}
        self.save()
        print('Manual and private maximum bidding passed: 100,110,120,160,200,200 USD; later equal cap leads, ceiling-only raise preserves public price.')

    def purchases(self):
        from concurrent.futures import ThreadPoolExecutor
        for name in ['buyer-a','buyer-b']:
            self.login(name)
        listing=next(row for row in self.state['listings'] if row['facts']['reference']=='DEMO-WATCH-02')
        quotes={name:self.quote(name,listing['id'],listing['revision'],listing['facts']['price_minor'],'purchase','listing') for name in ['buyer-a','buyer-b']}
        available=self.call('orders','GET','/v1/listings/'+listing['id']+'/availability')
        def reserve(name):
            return name,self.call('orders','POST','/v1/reservations',name,{'watch_id':listing['physical_watch_id'],'quote_id':quotes[name]['id'],'expected_revision':available['revision']})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(reserve,['buyer-a','buyer-b']))
        assert sorted(result['status'] for _,result in results)==['denied','succeeded'],results
        name,winner=next((name,result) for name,result in results if result['status']=='succeeded')
        # The order opens awaiting its payment notice; the payment clock starts only once that notice is delivered
        # (MONEY), so wait, bounded, for the real transition instead of assuming it.
        assert winner['order']['state'] in ('awaiting_notification','awaiting_payment'), winner['order']['state']
        deadline=time.monotonic()+60
        current=winner['order']
        while current['state']=='awaiting_notification' and time.monotonic()<deadline:
            time.sleep(0.5)
            current=self.call('orders','GET','/v1/orders/'+winner['resource_id'],name,durable=False)['order']
        winner={**winner,'order':current}
        assert winner['order']['quote_id']==quotes[name]['id'] and winner['order']['state']=='awaiting_payment', winner['order']['state']
        assert winner['order']['total_minor']==quotes[name]['payable_minor'] and winner['order']['payment_authority'] is False
        self.state['reservation']={'winner':name,**winner,'quote':quotes[name]}
        self.save()
        self.call('orders','GET','/v1/orders/'+winner['resource_id'],'buyer-b' if name=='buyer-a' else 'buyer-a',expected=(403,404))
        self.call('orders','POST','/v1/orders/'+winner['resource_id']+'/transitions',name,{'state':'paid','expected_revision':winner['order']['revision'],'reason':'Premature payment must be denied'},expected=(403,409,422))
        print('Two real buyers raced: exactly one awaiting-payment reservation, retained exact quote, other buyer denied.')

    def directory(self):
        self.state.setdefault('directory',{})
        for kind in ['dealer','brand']:
            self.login(kind)
            org=self.state['businesses'][kind]['id']
            if kind not in self.state['directory']:
                profile=self.call('service-operations','PUT','/v1/directory/businesses/'+org,kind,{
                    'expected_revision':0,'capabilities':['maintenance','repair']+(['customization'] if kind=='brand' else []),
                    'contact':kind+'.s1@example.test','visit_en':'Sample visit by arrangement; no appointment booked',
                    'visit_ar':'زيارة تجريبية بالتنسيق، لم يتم حجز موعد','scope_en':'Sample official business service profile; no work authorized',
                    'scope_ar':'ملف خدمة تجريبي لمنشأة رسمية، لا عمل مصرح به','published':True})
                self.state['directory'][kind]=profile;self.save()
        public=self.call('service-operations','GET','/v1/directory/businesses')
        assert len(public['items'])==2,public
        self.login('buyer-a')
        previous=self.call('service-operations','GET','/v1/directory/choices/current','buyer-a')
        choice=previous.get('choice')
        selected=self.call('service-operations','POST','/v1/directory/choices','buyer-a',{
            'organization_id':self.state['businesses']['dealer']['id'],'capability':'maintenance','purpose':'servicing',
            'expected_revision':choice['revision'] if choice else 0,'profile_revision':self.state['directory']['dealer']['revision']})
        self.state['service_choice']=selected;self.save()
        other=self.state['businesses']['brand']['id']
        self.call('service-operations','PUT','/v1/directory/businesses/'+other,'dealer',{
            'expected_revision':1,'capabilities':['maintenance'],'contact':'denied@example.test','visit_en':'Sample denial','visit_ar':'تجريبي',
            'scope_en':'Cross-business denial','scope_ar':'رفض وصول','published':True},expected=(403,))
        print('Real onboarded dealer and brand staff published scoped profiles; buyer chose servicing, cross-business write denied.')

    def request(self):
        self.login('buyer-a')
        if 'request_draft' not in self.state:
            result=self.call('catalog','POST','/v1/request-drafts','buyer-a',{'brand_id':self.state['businesses']['brand']['id'],
                'kind':'customization','watch_context':'owned_watch','watch_reference':'SAMPLE-COURSE-WATCH',
                'scope_intent':'Sample dial/color discussion, not approval','notes':'DEMO: private course request only','options':{}})
            assert result['status']=='succeeded',result
            self.state['request_draft']=result;self.save()
        result=self.state['request_draft']; print('DRAFT',json.dumps(result)[:1600])


    def private_demo_references(self):
        fixtures = json.loads((ROOT / 'demo/listings.json').read_text())
        return {item['id'] for item in fixtures['listings'] if item['seller_type'] == 'private'}

    def listing_reviewer(self, credentials):
        if credentials is None:
            operator = self.login('operator')
            self.require_listing_permission(operator, 'identity.private-seller.review')
            return operator
        values = json.loads(read_private_file(credentials, 8192))
        if (not isinstance(values, dict) or set(values) != {'email', 'password'} or
                not all(isinstance(value, str) and value for value in values.values())):
            raise ValueError('Reviewer credentials must contain email and password only')
        self.client.cookies.clear()
        try:
            reviewer = self.call('identity', 'POST', '/v1/accounts/login', body=values, durable=False)
        finally:
            self.client.cookies.clear()
        self.require_listing_permission(reviewer, 'identity.private-seller.review')
        return reviewer

    @staticmethod
    def require_listing_permission(session, permission):
        if permission not in session['principal']['permissions']:
            raise RuntimeError('Current Identity permission required for listing review')

    def write_review_file(self, path, content):
        if path.parent.resolve() != self.run_dir:
            raise ValueError('Write private review outputs directly in the private run directory')
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)

    def review_command(self, proof, action, route, body, session):
        # Retain a request digest, not the photograph, credentials or verdict text.
        digest = sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        commands = proof['commands']
        command = commands.get(action)
        binding = {'actor': session['account']['id'], 'digest': digest, 'revision': body['revision']}
        if command is None:
            command = commands[action] = {**binding, 'key': str(uuid4())}
            self.save()
        if any(command[key] != value for key, value in binding.items()):
            raise RuntimeError('Retry listing review with the original request and actor')
        if 'result' not in command:
            response = self.call('identity', 'POST', route, body=body, durable=False, headers={
                'Authorization': 'Bearer ' + session['access_token'], 'Idempotency-Key': command['key'],
            })
            fields = ('state', 'revision', 'assignment_revision')
            if action == 'challenge':
                fields += ('challenge_id', 'code')
            command['result'] = {field: response[field] for field in fields}
            self.save()
        return command['result']

    def listing_review(self, reference, action, file, credentials=None):
        run = self.run_dir.stat()
        if run.st_mode & 0o077 or run.st_uid != os.geteuid():
            raise ValueError('Listing review requires an owner-only proof run directory')
        if reference not in self.private_demo_references():
            raise ValueError('Select an exact private demo listing reference')
        seller = self.login('seller')
        workspace = self.call('catalog', 'GET', '/v1/seller/listings?limit=50', 'seller')
        matches = [row for row in workspace['items'] if row['is_demo'] is True and
                   row['seller_type'] == 'private' and row['facts']['reference'] == reference]
        if workspace.get('next_cursor') or len(matches) != 1 or matches[0]['status'] != 'draft':
            raise RuntimeError('Start guarded publication and select exactly one current demo draft')
        row = matches[0]
        path = '/v1/listing-reviews/' + str(UUID(row['id']))
        # Identity creates this record only after Catalog attempts the bound publish.
        current = self.call('identity', 'GET', path, 'seller', expected=(200,))
        binding = {'id': row['id'], 'watch_id': row['physical_watch_id'], 'revision': row['revision'],
                   'seller': seller['account']['id']}
        proofs = self.state.setdefault('listing_proofs', {})
        proof = proofs.get(reference)
        if proof is None:
            if action != 'challenge' or current['state'] != 'required' or current['revision'] != 0:
                raise RuntimeError('A fresh bound listing challenge is required; existing approvals cannot count')
            proof = proofs[reference] = {'binding': binding, 'commands': {}}
            self.save()
        elif proof['binding'] != binding:
            raise RuntimeError('The private review no longer binds the exact draft and watch')
        commands = proof['commands']
        challenge = commands.get('challenge', {}).get('result', {})
        submission = commands.get('submit', {}).get('result', {})
        assignment = commands.get('assign', {}).get('result', {})
        if action == 'challenge':
            if current['state'] not in ('required', 'issued') or (current['state'] == 'issued' and 'challenge' not in commands):
                raise RuntimeError('This run cannot issue a challenge over another review')
            revision = commands.get('challenge', {}).get('revision', current['revision'])
            value = self.review_command(proof, action, path+'/challenges', {'revision': revision}, seller)
            if value['state'] != 'issued' or value['revision'] != revision + 1:
                raise RuntimeError('Identity did not confirm the expected challenge')
            self.write_review_file(file, json.dumps({'listing_id': binding['id'], 'listing_revision': binding['revision'],
                                                     'proof_revision': value['revision'], 'code': value['code']}).encode())
        elif action == 'submit':
            if 'code' not in challenge or (current['state'] != 'issued' and 'submit' not in commands):
                raise RuntimeError('Use the current single-use challenge before proceeding')
            photo = read_private_file(file, POSSESSION_PHOTO_MAX)
            if not photo.startswith(PNG_SIGNATURE):
                raise ValueError('Supply the actual private possession photograph as PNG')
            body = {'revision': challenge['revision'], 'challenge_id': challenge['challenge_id'],
                    'code': challenge['code'], 'photo_base64': base64.b64encode(photo).decode('ascii')}
            value = self.review_command(proof, action, path+'/submissions', body, seller)
            if value['state'] != 'pending' or value['revision'] != challenge['revision'] + 1:
                raise RuntimeError('Identity did not confirm the expected submission')
            proof['photo_digest'] = sha256(photo).hexdigest()
            challenge.pop('code')
            self.save()
        else:
            reviewer = self.listing_reviewer(credentials)
            reviewer_id = reviewer['account']['id']
            if reviewer_id == binding['seller']:
                raise RuntimeError('Seller cannot review their own evidence')
            if action == 'assign':
                if not submission or 'photo_digest' not in proof or current['state'] != 'pending':
                    raise RuntimeError('The actual seller submission must be pending')
                operator = self.login('operator')
                self.require_listing_permission(operator, 'identity.private-seller.assign')
                value = self.review_command(proof, action, path+'/assignment',
                                            {'revision': submission['revision'], 'reviewer_id': reviewer_id}, operator)
                if value['state'] != 'pending' or value['revision'] != submission['revision'] + 1:
                    raise RuntimeError('Identity did not confirm the independent assignment')
                proof['reviewer'] = reviewer_id
                self.save()
            else:
                expected = {field: assignment.get(field) for field in ('revision', 'assignment_revision')}
                if not assignment or proof.get('reviewer') != reviewer_id:
                    raise RuntimeError('Use the assigned independent reviewer')
                if 'decide' not in commands and (current['state'] != 'pending' or
                        any(current[field] != value for field, value in expected.items())):
                    raise RuntimeError('The active assignment changed')
                if action == 'inspect':
                    if 'decide' in commands:
                        raise RuntimeError('Do not use an earlier inspection after a verdict attempt')
                    photo = self.call('identity', 'GET', path+'/photo', expected=(200,), raw=True, headers={
                        'Authorization': 'Bearer ' + reviewer['access_token'],
                    })
                    data = photo.content
                    if (photo.headers.get('content-type') != 'image/png' or len(data) > POSSESSION_PHOTO_MAX or
                            sha256(data).hexdigest() != proof['photo_digest']):
                        raise RuntimeError('Reviewer did not receive the exact submitted private photo')
                    self.write_review_file(file, data)
                    proof['inspection'] = {**expected, 'reviewer': reviewer_id}
                    self.save()
                elif action == 'decide':
                    if proof.get('inspection') != {**expected, 'reviewer': reviewer_id}:
                        raise RuntimeError('The assigned reviewer must read the exact private photo before a verdict')
                    decision = json.loads(read_private_file(file, 8192))
                    if (not isinstance(decision, dict) or set(decision) != {'verdict', 'reason'} or
                            decision['verdict'] not in ('approved', 'correction', 'rejected') or
                            not isinstance(decision['reason'], str) or not 5 <= len(decision['reason'].strip()) <= 500):
                        raise ValueError('Supply an explicit reviewer verdict and a bounded audit reason')
                    value = self.review_command(proof, action, path+'/decision', {**decision, **expected}, reviewer)
                    if value['state'] != decision['verdict'] or value['revision'] != assignment['revision'] + 1:
                        raise RuntimeError('Identity did not confirm the selected reviewer verdict')
                    if value['state'] != 'approved':
                        raise RuntimeError('Listing possession has not been approved; publication proof is incomplete')
                else:
                    raise ValueError('Unknown listing review action')
        print('Listing review step acknowledged; private review materials remain in the proof directory.')

    def verify_reviewed_publication(self, listings):
        proofs = self.state.get('listing_proofs', {})
        for reference in self.private_demo_references():
            matches = [item for item in listings if item['facts']['reference'] == reference]
            proof = proofs.get(reference)
            if len(matches) != 1 or not proof:
                raise RuntimeError('A private listing lacks a connected possession review')
            row, binding = matches[0], proof['binding']
            verdict = proof['commands'].get('decide', {}).get('result', {})
            if (verdict.get('state') != 'approved' or row['id'] != binding['id'] or
                    row['physical_watch_id'] != binding['watch_id'] or row['revision'] != binding['revision'] + 1 or
                    row['seller_type'] != 'private'):
                raise RuntimeError('Publication does not match the reviewed draft, watch and revision')

    def publication(self):
        for name in ['seller','dealer']:
            self.login(name)
        # The owning Catalog importer uses the actual create/upload/fee/publish APIs.
        private = {
            'BT_ENVIRONMENT': 'demo', 'BT_DEMO_IMPORT_ACK': 'illustrative-stock-only',
            'BT_DEMO_PRIVATE_DIAGNOSTICS': '1',
            'BT_DEMO_PRIVATE_TOKEN': self.state['accounts']['seller']['access_token'],
            'BT_DEMO_DEALER_TOKEN': self.state['accounts']['dealer']['access_token'],
            'BT_DEMO_DEALER_ORGANIZATION_ID': self.state['businesses']['dealer']['id'],
        }
        if self.backend == 'native':
            demo = self.run_dir / 'demo'
            demo.mkdir(exist_ok=True)
            for filename in ('images-manifest.json', 'listings.json'):
                shutil.copyfile(ROOT / 'demo' / filename, demo / filename)
            shutil.copytree(ROOT / 'web/public/demo/watches', demo / 'watches', dirs_exist_ok=True)
            private['BT_DEMO_ROOT'] = str(demo)
            command, env = self.native_plan('catalog', ['bt_runtime.fixtures', 'L03.listings', 'demo'], private)
        else:
            command = ['docker', 'compose', '-f', str(self.run_dir / 'compose.local.json'), 'exec', '-T']
            for key in private:
                command.extend(['-e', key])
            command.extend(['catalog', 'python', '-m', 'bt_runtime.fixtures', 'L03.listings', 'demo'])
            env = {**os.environ, **private}
        if not self.reconciling:
            self.execute_publication(command, env)
        listings=[]
        for name in ['seller','dealer']:
            org='?organization_id='+self.state['businesses']['dealer']['id'] if name=='dealer' else ''
            listings.extend(item for item in self.call('catalog','GET','/v1/seller/listings'+org,name)['items'] if item['is_demo'])
        assert len(listings)==6 and all(item['status']=='published' for item in listings)
        self.verify_reviewed_publication(listings)
        self.state['listings']=listings
        discovery=self.call('catalog','GET','/v1/discovery/watches')
        assert discovery['items'] and all(item['demo'] for item in discovery['items'])
        self.save()
        print('Six labeled sample listings published; auctions enter browse after scheduling.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase', choices=['all','accounts','onboard','publication','listing-review','contacts','auctions','bids','purchases','directory','request'])
    parser.add_argument('--origin',default='http://127.0.0.1:3300')
    parser.add_argument('--backend', choices=['container', 'native'], default='container')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--listing-reference')
    parser.add_argument('--review-action', choices=['challenge', 'submit', 'assign', 'inspect', 'decide'])
    parser.add_argument('--review-file', type=Path, help='Private code/photo or verdict file for this action')
    parser.add_argument('--reviewer-credentials', type=Path, help='Optional mode-0600 credentials for an already qualified reviewer')
    args=parser.parse_args()
    if args.backend == 'native' and args.run_dir is None:
        parser.error('--backend native requires --run-dir')
    if args.phase == 'listing-review':
        if args.run_dir is None or not args.listing_reference or not args.review_action:
            parser.error('listing-review requires --run-dir, --listing-reference and --review-action')
        if (args.review_action != 'assign') != (args.review_file is not None):
            parser.error('--review-file is required for challenge, submit, inspect and decide only')
        if args.reviewer_credentials is not None and args.review_action in ('challenge', 'submit'):
            parser.error('Seller actions do not use reviewer credentials')
    elif any((args.listing_reference, args.review_action, args.review_file, args.reviewer_credentials)):
        parser.error('Listing review options require the listing-review phase')
    walk=Walkthrough(args.origin, args.backend, args.run_dir)
    try:
        if args.phase == 'all':
            walk.all()
        elif args.phase == 'listing-review':
            walk.listing_review(args.listing_reference, args.review_action, args.review_file, args.reviewer_credentials)
        else:
            walk.run_phase(args.phase)
    finally:
        try:
            (walk.run_dir/(args.phase+'-evidence.json')).write_text(json.dumps(walk.evidence,indent=2))
        finally:
            walk.client.close()


if __name__=='__main__':
    main()
