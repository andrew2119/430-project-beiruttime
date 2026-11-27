"""L12 image proof on an ephemeral hosted runner; no host source in app containers."""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import select
import socket
from socketserver import BaseRequestHandler, ThreadingTCPServer
import subprocess
import sys
from threading import Thread
import time
from uuid import uuid4

import httpx
from connected_scenarios import Scenarios

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / '.github/ci'))
import walkthrough as hosted  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FIXTURES = ROOT / 'packages/contracts-auction/policy/fixtures.json'
ORIGIN = 'http://127.0.0.1:3412'
SERVICES = ('identity', 'catalog', 'auction', 'pricing', 'orders')
APPS = (*SERVICES, 'web')
BASES = {
    'python:3.11.14-slim': 'docker.io/library/python@sha256:fa7a862d74b4decf68fb7d3a85147efc14dbcd3779c0abd56c071d27a1ffee04',
    'node:22.21.1-alpine': 'docker.io/library/node@sha256:eefb407f08684593068a61d76c3336fb418bdfd184357ccfe448aadfa1147b3e',
    'postgres:17.6-alpine': 'docker.io/library/postgres@sha256:747d5ed1fdeeb124b880fbe3d7c6557d2c4064ae41d6b6297d417882effce4be',
}
ROW_PHASES = {
    'five-services-and-web-ready': ('stack',),
    'real-identity-and-catalog-publication': ('publication',),
    'reserve-private': ('policy', 'close'),
    'fixed-end-120-90-and-before-zero': ('packaged', 'fixed'),
    'at-and-after-zero-refused': ('packaged', 'late'),
    'manual-and-two-proxy-rows': ('fixed',),
    'removed-controls-unavailable': ('browser-matrix', 'race'),
    'historical-order-read-actor-scoped': ('historical',),
    'browser-en-ar-dark-light-390': ('browser-matrix', 'browser-screens'),
}
PHASE_ORDER = ('build', 'packaged', 'stack', 'publication', 'policy-auction', 'policy', 'browser-matrix',
               'browser-screens', 'race', 'fixed', 'late', 'close', 'historical')
ID = re.compile(r'sha256:[0-9a-f]{64}')
PNG = b'\x89PNG\r\n\x1a\n'


class ProofError(RuntimeError):
    """A fixed, public-safe explanation."""


class HistoricalUnavailable(ProofError):
    """The reviewed historical Order proof prerequisites are absent."""


def command(label, *args, data=None, env=None, timeout=90, quiet=False):
    # No raw logs, argv, stderr, response bodies, or credentials reach public CI output.
    try:
        result = subprocess.run(args, cwd=ROOT, env=env, input=data, text=True, timeout=timeout,
                                stdout=subprocess.DEVNULL if quiet else subprocess.PIPE, stderr=subprocess.PIPE)
    except (OSError, subprocess.TimeoutExpired):
        raise ProofError(f'{label}: unavailable or timed out') from None
    if result.returncode:
        raise ProofError(f'{label}: command exited {result.returncode}')
    return result.stdout


def docker(*args, **kwargs):
    return command(kwargs.pop('label', f'docker {args[0]}'), 'docker', *args, **kwargs)


def env_flags(env):
    return [arg for key in env for arg in ('--env', key)]


def rsa_pair():
    key = command('generate disposable signing key', 'openssl', 'genpkey', '-algorithm', 'RSA',
                  '-pkeyopt', 'rsa_keygen_bits:2048')
    return key, command('derive disposable public key', 'openssl', 'pkey', '-pubout', data=key)


ATTEMPT_LABEL = 'bt.l12.attempt'
OBJECT_ID = re.compile(r'[0-9a-f]{64}')


class Owned:
    """Only acknowledged, read-back attempt identities may authorize a removal."""

    def __init__(self, stack, project):
        self.stack, self.project = stack, project
        self.incomplete = []

    @contextmanager
    def acquiring(self, label):
        try:
            yield
        except Exception:
            self.incomplete.append(f'{label}: creation or ownership was not confirmed')
            raise

    def register(self, label, readback, remove):
        def cleanup(identity):
            try:
                if readback() != identity:
                    raise ProofError('ownership changed')
                remove()
            except Exception:
                self.incomplete.append(f'{label}: exact cleanup was not confirmed')
        identity = readback()
        self.stack.callback(cleanup, identity)
        return identity

    def label(self, labels):
        return isinstance(labels, dict) and labels.get(ATTEMPT_LABEL) == self.project

    @property
    def flag(self):
        return f'{ATTEMPT_LABEL}={self.project}'


def read_image(owned, tag, sha):
    meta = json.loads(docker('image', 'inspect', tag))[0]
    labels = meta['Config']['Labels']
    if not (ID.fullmatch(meta['Id']) and tag in (meta['RepoTags'] or [])
            and meta['Os'] == 'linux' and meta['Architecture'] == 'amd64'
            and owned.label(labels) and labels.get('org.opencontainers.image.revision') == sha):
        raise ProofError('image identity check failed')
    return meta['Id']


def build(owned, sha, images):
    # Make the independent packaged check available even if a later app build fails.
    for name in ('auction', *(name for name in APPS if name != 'auction')):
        path = ROOT / ('web/Dockerfile' if name == 'web' else f'services/{name}/runtime/Dockerfile')
        tag = f'{owned.project}/{name}:local'
        recipe = path.read_text()
        base = 'node:22.21.1-alpine' if name == 'web' else 'python:3.11.14-slim'
        # Only pin the two reviewed external FROMs; keep all COPY/RUN/CMD and stages intact.
        recipe, matches = re.subn(rf'^FROM {re.escape(base)}(?= AS )', f'FROM {BASES[base]}', recipe, flags=re.M)
        if matches != 2:
            raise ProofError(f'{name}: Dockerfile base recipe drifted')
        options = [] if name == 'web' else ['--build-arg', f'SERVICE_PATH=services/{name}']
        print(f'Building {name} from {sha}', flush=True)
        if docker('image', 'ls', '--filter', f'reference={tag}', '--format', '{{.Repository}}:{{.Tag}}').strip():
            raise ProofError(f'{name}: attempt tag was already in use')
        with owned.acquiring(f'{name} image tag'):
            docker('build', '--pull', '--no-cache', '--platform', 'linux/amd64', '--target', 'runtime',
                   '--label', f'org.opencontainers.image.revision={sha}', '--label', owned.flag,
                   *options, '-t', tag, '-f', '-', '.',
                   data=recipe, label=f'build {name}', timeout=480, quiet=True)
            images[name] = owned.register(f'{name} image tag', lambda tag=tag: read_image(owned, tag, sha),
                                          lambda tag=tag: docker('image', 'rm', '--no-prune', tag))


def db_urls(service, passwords):
    runtime, owner = passwords[service]
    return (f'postgresql://bt_{service}:{runtime}@postgres:5432/bt_{service}',
            f'postgresql://bt_{service}_owner:{owner}@postgres:5432/bt_{service}')


def retry(label, action, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            return action()
        except ProofError:
            time.sleep(1)
    raise ProofError(f'{label}: not ready')


def provision(postgres):
    retry('PostgreSQL', lambda: docker('exec', postgres, 'pg_isready', '-q', '-h', '127.0.0.1', timeout=5))
    # Reuse the existing owner/runtime role init, without publishing a DB port.
    names = (*SERVICES, 'eligibility', 'trust', 'communications', 'service_ops')
    passwords = {name: (secrets.token_hex(16), secrets.token_hex(16)) for name in names}
    env = dict(os.environ, POSTGRES_USER='postgres', L12_POSTGRES=postgres)
    for name, (runtime, owner) in passwords.items():
        env[f'{name.upper()}_DB_PASSWORD'] = runtime
        env[f'{name.upper()}_OWNER_PASSWORD'] = owner
    script = 'psql() { docker exec -i "$L12_POSTGRES" psql "$@"; }; source "$1"'
    command('provision local database roles', 'bash', '-euc', script, 'l12', str(ROOT / 'infra/foundation/postgres-init.sh'),
            env=env)
    return passwords


def create_container(owned, network, name, alias, image, env, *options, argv=()):
    with owned.acquiring(name):
        alias_flags = ('--network-alias', alias) if alias else ()
        container = docker('create', '--pull', 'never', '--name', name, '--label', owned.flag,
                           '--network', network, *alias_flags, '--log-driver', 'none', '--security-opt',
                           'no-new-privileges', *env_flags(env), *options, image, *argv,
                           env={**os.environ, **env}).strip()
        if not OBJECT_ID.fullmatch(container):
            raise ProofError('cannot bind new container identity')

        def readback():
            meta = json.loads(docker('container', 'inspect', container))[0]
            if (meta['Id'] != container or meta['Name'] != '/' + name or not owned.label(meta['Config']['Labels'])
                    or meta['Image'] != image):
                raise ProofError('container identity check failed')
            return container

        return owned.register(name, readback, lambda: docker('container', 'rm', '--force', container))


def create_network(owned, name):
    with owned.acquiring('private network'):
        network = docker('network', 'create', '--internal', '--driver', 'bridge', '--label', owned.flag, name).strip()
        if not OBJECT_ID.fullmatch(network):
            raise ProofError('cannot bind new network identity')

        def readback():
            meta = json.loads(docker('network', 'inspect', network))[0]
            if not (meta['Id'] == network and meta['Name'] == name and meta['Internal'] and meta['Driver'] == 'bridge'
                    and owned.label(meta['Labels'])):
                raise ProofError('network identity check failed')
            return network

        return owned.register('private network', readback, lambda: docker('network', 'rm', network))


def create_volume(owned, name):
    # Volume names can be reused by Docker; refuse any existing object before create.
    if name in docker('volume', 'ls', '--format', '{{.Name}}').splitlines():
        raise ProofError('attempt volume name was already in use')
    with owned.acquiring('private PostgreSQL volume'):
        if docker('volume', 'create', '--driver', 'local', '--label', owned.flag, name).strip() != name:
            raise ProofError('cannot bind new volume name')

        def readback():
            meta = json.loads(docker('volume', 'inspect', name))[0]
            if not (meta['Name'] == name and meta['Driver'] == 'local' and meta['Scope'] == 'local'
                    and meta.get('CreatedAt') and meta.get('Mountpoint') and not meta.get('Options')
                    and owned.label(meta['Labels'])):
                raise ProofError('volume identity check failed')
            return meta['CreatedAt'], meta['Mountpoint']

        owned.register('private PostgreSQL volume', readback, lambda: docker('volume', 'rm', name))
        return name


def run_stack(owned, images):
    project = owned.project
    net_name = f'{project}-net'
    network = create_network(owned, net_name)
    volume = create_volume(owned, f'{project}-pg')
    postgres_image = BASES['postgres:17.6-alpine']
    docker('pull', '--platform', 'linux/amd64', postgres_image, timeout=120, quiet=True)
    postgres_meta = json.loads(docker('image', 'inspect', postgres_image))[0]
    postgres_id = postgres_meta['Id']
    if not (ID.fullmatch(postgres_id) and postgres_meta['Os'] == 'linux' and postgres_meta['Architecture'] == 'amd64'):
        raise ProofError('PostgreSQL digest did not resolve to a Linux/amd64 image')
    postgres = create_container(owned, network, project+'-postgres', 'postgres', postgres_id,
                                {'POSTGRES_PASSWORD': secrets.token_hex(16)}, '--mount',
                                f'type=volume,source={volume},target=/var/lib/postgresql/data')
    docker('start', postgres)
    passwords = provision(postgres)
    identity_private, identity_public = rsa_pair()
    service_private, service_public = rsa_pair()
    routes = {}
    for name in (*SERVICES, 'communications', 'eligibility', 'trust', 'service-operations'):
        url = f'http://{name}:8000' if name in SERVICES else 'http://127.0.0.1:3499'
        for prefix in ('', 'BT_'):
            for suffix in ('_URL', '_API_URL'):
                routes[prefix + name.replace('-', '_').upper() + suffix] = url
    web = {**routes, 'BT_ALLOWED_WEB_ORIGINS': ORIGIN, 'BT_PUBLIC_WEB_ORIGINS': ORIGIN,
           'BT_WEB_ORIGIN': ORIGIN, 'BT_TRUST_FORWARDED_ORIGIN': 'false', 'BT_LOCAL_HTTP': '1'}
    base = {**web, 'BT_ENVIRONMENT': 'demo', 'BT_AUTH_PUBLIC_KEY': identity_public,
            'BT_AUTH_ISSUER': 'beirut-time-identity', 'BT_AUTH_AUDIENCE': 'beirut-time',
            'BT_CONTACT_SIMULATOR': '1', 'BT_SERVICE_AUTH_PUBLIC_KEY': service_public,
            'BT_SERVICE_AUTH_PRIVATE_KEY': service_private, 'BT_EVENT_PRIVATE_KEY': service_private,
            'BT_DATABASE_POOL_SIZE': '3', 'BT_REQUEST_BODY_LIMIT': '8500000', 'BT_MODULES_PATH': '/app/modules'}
    for name in SERVICES:
        _, owner = db_urls(name, passwords)
        env = {'BT_SERVICE_NAME': name, 'BT_DATABASE_URL': owner, 'BT_MODULES_PATH': '/app/modules'}
        migration = create_container(owned, network, f'{project}-migrate-{name}', None, images[name], env,
                                     argv=('python', '-m', 'service_app.migrate'))
        # The exact container is owned before the attach/start can time out.
        docker('start', '--attach', migration, label=f'migrate {name}', timeout=120, quiet=True)
        state = json.loads(docker('container', 'inspect', migration))[0]['State']
        if state['Status'] != 'exited' or state['ExitCode'] != 0:
            raise ProofError(f'{name}: migration did not complete successfully')
    containers = {}
    for name in SERVICES:
        database, _ = db_urls(name, passwords)
        env = {**base, 'BT_SERVICE_NAME': name, 'BT_DATABASE_URL': database}
        if name == 'identity':
            env['BT_AUTH_PRIVATE_KEY'] = identity_private
        containers[name] = create_container(owned, network, f'{project}-{name}', name, images[name], env,
                                             '--memory', '256m', '--cpus', '0.5', '--read-only', '--tmpfs', '/tmp')
    containers['web'] = create_container(owned, network, project+'-web', 'web', images['web'], web,
                                         '--memory', '512m', '--cpus', '0.5')
    for container in containers.values():
        docker('start', container)
    endpoints = {}
    for name, container in containers.items():
        meta = json.loads(docker('inspect', container))[0]
        networks = meta['NetworkSettings']['Networks']
        if (meta['Image'] != images[name] or meta['Mounts'] or set(networks) != {net_name}
                or networks[net_name]['NetworkID'] != network):
            raise ProofError(f'{name}: runtime image or isolation mismatch')
        endpoints[name] = networks[net_name]['IPAddress']
        health = ('node', '-e', "fetch('http://127.0.0.1:3000/api/health').then(r=>{if(!r.ok)process.exit(1)})") if name == 'web' else (
            'python', '-c', "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)")
        retry(name, lambda: docker('exec', container, *health, timeout=6))
    return containers, endpoints


@contextmanager
def loopback_relay(port, address, destination_port):
    # The Linux host can reach its internal bridge directly. Expose only these
    # two targets to the browser/driver through runner loopback; never expose PostgreSQL.
    socket.inet_pton(socket.AF_INET, address)

    class Relay(BaseRequestHandler):
        def handle(self):
            try:
                with socket.create_connection((address, destination_port), timeout=5) as peer:
                    client = self.request
                    client.settimeout(5)
                    other = {client: peer, peer: client}
                    readers = set(other)
                    while readers:
                        ready, _, _ = select.select(readers, [], [], 45)
                        if not ready:
                            return
                        for source in ready:
                            chunk = source.recv(65536)
                            if chunk:
                                other[source].sendall(chunk)
                            else:
                                readers.remove(source)
                                other[source].shutdown(socket.SHUT_WR)
            except OSError:
                pass  # The calling HTTP client asserts response success.

    with ThreadingTCPServer(('127.0.0.1', port), Relay) as server:
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            thread.join()


class ImageScenarios(Scenarios):
    account_suffix = '.s1@example.test'

    def __init__(self, origin, out, project):
        super().__init__(origin, out, project)
        self.client.close()
        self.client = self.client_for_proof()

    def client_for_proof(self):
        # Requests are addressed only to runner loopback, irrespective of proxy settings.
        return httpx.Client(base_url=self.origin, headers={'Origin': self.origin}, timeout=30, trust_env=False)

    def prepare_images(self):
        # Use exactly the hosted coordinator and frozen review actor for private drafts.
        if hosted.proof.digest(hosted.ACTOR.read_bytes()) != hosted.ACTOR_SHA256:
            raise ProofError('hosted review actor differs from the pinned bytes')
        actor = hosted.load('n05_scripted_actor', hosted.ACTOR)
        source = hosted.load('connected_walkthrough', hosted.WALK)
        self.account_password = source.PASSWORD
        project = self.project

        class ImageWalkthrough(source.Walkthrough):
            def native_plan(self, service, arguments, extra=None):
                env = dict(extra or {})
                if service == 'catalog':
                    env['BT_DEMO_ROOT'] = '/app/demo'
                assert service in ('catalog', 'identity')
                return ['docker', 'exec', *env_flags(env), project+'-'+service, 'python', '-m', *arguments], {
                    **os.environ, **env}

        walk = ImageWalkthrough(self.origin, 'native', self.out)
        walk.client.close()
        walk.client = self.client_for_proof()
        try:
            for phase in ('accounts', 'bootstrap', 'onboard', 'contacts'):
                walk.run_phase(phase)
            review = dict(state='not reached', references=[], imports=0, review_calls=0)
            hosted.publication(walk, walk.run_phase, actor, review)
            self.accounts = walk.state['accounts']
            self.listings = {row['facts']['reference']: row for row in walk.state['listings']
                             if row['is_demo'] and row['seller_type'] == 'private'}
            assert set(self.listings) == set(actor.REFS) and all(row['status'] == 'published' for row in self.listings.values())
            self.evidence.append({'real_accounts': sorted(self.accounts), 'published_private': sorted(self.listings),
                                  'scripted_review': review, 'physical_inspection_verified': False})
        finally:
            walk.client.close()

    def refresh_sample_sessions(self):
        for role in ('seller', 'buyer-a', 'buyer-b'):
            self.accounts[role] = self.call('identity', 'POST', '/v1/accounts/login', body={
                'email': role + self.account_suffix, 'password': self.account_password})

    def drive_browser(self, context):
        command('real Chrome matrix', 'node', str(HERE/'image-browser.mjs'), 'matrix', str(self.out),
                data=json.dumps(context), timeout=240)
        self.refresh_sample_sessions()

    def capture_screenshots(self, listing, refresh):
        command('independent authenticated Chrome screenshots', 'node', str(HERE/'image-browser.mjs'), 'screens', str(self.out),
                data=json.dumps({'listing': listing, 'refresh': refresh}), timeout=180)

    def fixed_bid(self, actor, auction, kind, amount, end, remaining):
        lot, quote = self.quote(actor, auction, amount)
        key = {'Idempotency-Key': str(uuid4())}
        body = {'amount_minor': amount, 'fee_quote_id': quote['id'], 'expected_revision': lot['revision']}
        delay = (end - datetime.now(timezone.utc)).total_seconds() - remaining + 0.05
        if delay < 0:
            raise ProofError(f'reviewed bid missed the {remaining}s launch window')
        time.sleep(delay)
        path = f'/v1/auctions/{auction}/{kind}'
        receipt = self.call('auction', 'POST', path, actor, body, headers=key)
        assert receipt['status'] == 'succeeded'
        measured = (end - datetime.fromisoformat(receipt['server_time'])).total_seconds()
        assert remaining - 1 <= measured <= remaining
        assert self.call('auction', 'POST', path, actor, body, headers=key) == receipt
        return lot, receipt, measured

    def fixed_deadline(self):
        auction = self.create('DEMO-WATCH-05', seconds=132)
        path = f'/v2/seller/auctions/{auction}/policy'
        initial = self.call('auction', 'GET', path, 'seller')
        end = datetime.fromisoformat(initial['current_ends_at'])
        _, first, at_120 = self.fixed_bid('buyer-a', auction, 'maximum', 600000, end, 120)
        policy = self.call('auction', 'GET', path, 'seller')
        assert first['current_minor'] == 400000 and not policy['reserve_met'] and policy['end_version'] == initial['end_version']
        assert datetime.fromisoformat(policy['current_ends_at']) == end
        before, second, at_90 = self.fixed_bid('buyer-b', auction, 'bids', 410000, end, 90)
        policy = self.call('auction', 'GET', path, 'seller')
        assert second['accepted_sequence'] == before['accepted_sequence'] + 2 and second['current_minor'] == 420000
        assert policy['end_version'] == initial['end_version'] and datetime.fromisoformat(policy['current_ends_at']) == end
        assert not policy['reserve_met'] and policy['frozen'] and not policy['cancellation_eligible']
        denied = self.call('auction', 'PATCH', f'/v1/auctions/{auction}/policy', 'seller',
                           {'extension_policy': 'last-two-minutes.v1', 'buy_now_minor': 500000}, expected=(409,), direct_auction=True)
        assert denied['error']['code'] == 'fixed_end_policy'
        history_path = f'/v1/auctions/{auction}/history'
        history = self.call('auction', 'GET', history_path)
        assert [(row['sequence'], row['amount_minor'], row['automatic']) for row in history['items']] == [
            (1, 400000, True), (2, 410000, False), (3, 420000, True)]
        assert '600000' not in json.dumps(history) and 'maximum_minor' not in json.dumps(history)
        _, ceiling, at_45 = self.fixed_bid('buyer-a', auction, 'maximum', 610000, end, 45)
        assert ceiling['current_minor'] == 420000 and ceiling['accepted_sequence'] == second['accepted_sequence'] + 1
        assert ceiling['end_version'] == initial['end_version'] and datetime.fromisoformat(ceiling['ends_at']) == end
        assert self.call('auction', 'GET', history_path)['items'] == history['items']
        boundary = self.call('auction', 'GET', f'/v1/auctions/{auction}/deadline-boundary', 'seller', direct_auction=True)
        assert datetime.fromisoformat(boundary['ends_at']) == end
        assert boundary['evaluated_at'] == boundary['ends_at'] and boundary['code'] == 'auction_ended'
        assert boundary['revision'] == ceiling['revision'] and boundary['accepted_sequence'] == ceiling['accepted_sequence']
        self.evidence.append({'measured_seconds': [at_120, at_90, at_45], 'exact_boundary': boundary,
                              'late_bid_fixed_end': policy})
        return auction, end, policy['end_version'], history['items']

    def late_refusal(self, fixed):
        auction, end, end_version, history = fixed
        actor, amount = 'buyer-b', 430000
        lot, quote = self.quote(actor, auction, amount)
        expiry = datetime.fromisoformat(quote['expires_at'])
        reviewed = datetime.fromisoformat(quote['reviewed_at'])
        assert (quote['owner_id'] == self.accounts[actor]['account']['id'] and quote['subject_id'] == auction
                and quote['subject_revision'] == lot['revision'] and quote['price_minor'] == amount
                and quote['purpose'] == 'bid' and quote['currency'] == 'USD' and quote['schedule_id'] == 'usd-v2'
                and quote['sample'] is True and quote['source'] == 'sample' and quote['source_verified'] is False
                and reviewed < end < expiry)
        time.sleep(max(0, (end - datetime.now(timezone.utc)).total_seconds()) + 0.05)
        policy_path = f'/v2/auctions/{auction}/policy'
        before = self.call('auction', 'GET', policy_path, direct_auction=True)
        opened = datetime.fromisoformat(before['server_time'])
        assert end <= opened < expiry
        late = self.call('auction', 'POST', f'/v1/auctions/{auction}/bids', actor,
                         {'amount_minor': amount, 'expected_revision': lot['revision'], 'fee_quote_id': quote['id']},
                         expected=(200, 409), direct_auction=True)
        after = self.call('auction', 'GET', policy_path, direct_auction=True)
        checked = datetime.fromisoformat(after['server_time'])
        assert opened <= checked < expiry
        assert all(datetime.fromisoformat(row['current_ends_at']) == end and row['end_version'] == end_version
                   for row in (before, after))
        assert self.call('auction', 'GET', f'/v1/auctions/{auction}/history')['items'] == history
        if late.get('status') == 'denied' and late.get('code') == 'auction_ended':
            # Only the persisted mutation denial carries the lock's decision timestamp.
            assert opened <= datetime.fromisoformat(late['server_time']) <= checked
            assert late['auction_id'] == auction
            guard = 'deadline-specific'
        else:
            assert late.get('error', {}).get('code') in (
                'auction_window_or_fee_expired', 'auction_ended', 'auction_committed')
            # The close worker can win before the bid. An outer error alone does not
            # identify the authoritative mutation guard as the source of refusal.
            guard = 'refusal-only'
        self.evidence.append({'late_request_refusal': guard, 'server_before': opened.isoformat(),
                              'server_after': checked.isoformat(), 'quote_valid_until': expiry.isoformat()})
        return guard

    def close_result(self, fixed):
        auction, end, end_version, history = fixed
        print('Waiting for the unchanged reserve no-sale close.', flush=True)
        time.sleep(max(0, (end - datetime.now(timezone.utc)).total_seconds()))
        until = time.monotonic() + 15
        result = {}
        while time.monotonic() < until:
            result = self.call('auction', 'GET', f'/v1/auctions/{auction}/result', direct_auction=True)
            if result.get('status') == 'no_sale':
                break
            time.sleep(1)
        assert (result.get('status') == 'no_sale' and result.get('order_available') is False
                and result.get('winner') is None and result.get('reason') == 'reserve_not_met'
                and result.get('closing_minor') == 420000 and result.get('end_version') == end_version
                and datetime.now(timezone.utc) >= end)
        assert self.call('auction', 'GET', f'/v1/auctions/{auction}/history')['items'] == history
        self.evidence.append({'closed_below_reserve': result})


def expected_matrix(data):
    cases = json.loads(data)
    fixed, refused = cases['fixed_end'], cases['deadline_refusal']
    assert fixed['remaining_seconds'] == [120, 90, .001] and refused['remaining_seconds'] == [0, -.001]
    assert fixed['kinds'] == ['manual', 'proxy', 'ceiling_only']
    return [[remaining, kind, stored, None if remaining > 0 else refused['code']]
            for remaining in (*fixed['remaining_seconds'], *refused['remaining_seconds'])
            for stored in ('none.v1', 'last-two-minutes.v1') for kind in fixed['kinds']]


def packaged_matrix(owned, auction_image):
    data = FIXTURES.read_text()
    # No DB, Web, or published sample fixture is required for the packaged policy.
    probe = create_container(owned, 'none', owned.project+'-boundary', None, auction_image, {},
                             '--read-only', '--tmpfs', '/tmp',
                             argv=('python', '-c', (HERE/'image-boundary.py').read_text(), data))
    observed = json.loads(docker('start', '--attach', probe, label='exact packaged Auction deadline matrix'))
    state = json.loads(docker('container', 'inspect', probe))[0]['State']
    assert state['Status'] == 'exited' and state['ExitCode'] == 0 and observed == expected_matrix(data)
    return observed


def browser_files(out, mode=None):
    names = []
    for width in (1280, 390):
        if mode != 'screens':
            matrix = f'browser-{width}.json'
            assert len(json.loads((out/matrix).read_text())) == 8
            names.append(matrix)
        if mode != 'matrix':
            for locale in ('en', 'ar'):
                for theme in ('light', 'dark'):
                    name = f'fixed-policy-{locale}-{theme}-{width}.png'
                    with (out/name).open('rb') as image:
                        assert image.read(8) == PNG
                    assert (out/name).stat().st_size > 1024
                    names.append(name)
    return {name: hashlib.sha256((out/name).read_bytes()).hexdigest() for name in names}


def historical_orders(auction):
    # Do not turn a synthetic absent-operation response into a historical read pass.
    supports_lookup = docker('exec', auction, 'python', '-c',
        'from service_app.dependencies import Dependencies; print(hasattr(Dependencies, "lookup_historical_v1"))').strip()
    if supports_lookup == 'False':
        raise HistoricalUnavailable('historical orders: no historical Order lookup on the packaged Auction service and '
                                    'no approved retained pre-bid Order fixture on this base')
    raise HistoricalUnavailable('historical orders: no approved retained pre-bid Order fixture on this base')


def run(out, sha):
    assert re.fullmatch(r'[a-f0-9]{40}', sha) and command('checked-out SHA', 'git', 'rev-parse', 'HEAD').strip() == sha
    assert not command('check source purity', 'git', 'status', '--porcelain', '--ignored', '--untracked-files=all').strip()
    project = 'bt-l12-image-' + uuid4().hex
    out.mkdir(mode=0o700)
    report = {'sha': sha, 'complete': False, 'phases': dict.fromkeys(PHASE_ORDER, 'not-run'), 'errors': {},
              'images': {}, 'cleanup_incomplete': ['cleanup not finalized']}
    phases, results = report['phases'], {}

    def row_state(dependencies):
        statuses = {phases[name] for name in dependencies}
        if 'fail' in statuses:
            return 'fail'
        return 'pass' if statuses == {'pass'} else 'not-run'

    def checkpoint():
        report['rows'] = {row: row_state(deps) for row, deps in ROW_PHASES.items()}
        pending = out/'receipt.pending'
        pending.write_text(json.dumps(report, sort_keys=True) + '\n')
        pending.replace(out/'receipt.json')

    checkpoint()

    def phase(name, action, *dependencies):
        if any(phases.get(dep) != 'pass' for dep in dependencies):
            phases[name] = 'not-run'
            return
        print(f'L12: {name}', flush=True)
        try:
            results[name] = action()
        except Exception as error:
            phases[name] = 'fail'
            report['errors'][name] = str(error) if isinstance(error, ProofError) else 'assertion or runner operation failed'
        else:
            phases[name] = 'pass'
        checkpoint()

    with ExitStack() as stack:
        owned = Owned(stack, project)

        def app_stack():
            containers, endpoints = run_stack(owned, report['images'])
            stack.enter_context(loopback_relay(3412, endpoints['web'], 3000))
            stack.enter_context(loopback_relay(3413, endpoints['auction'], 8000))
            proof = ImageScenarios(ORIGIN, out, project)
            stack.callback(proof.client.close)
            return proof, containers

        def scenario(method, *args, refresh=False):
            proof, _ = results['stack']
            if refresh:
                proof.refresh_sample_sessions()
            result = getattr(proof, method)(*args)
            if method in ('browser_matrix', 'browser_screens'):
                report.setdefault('browser', {}).update(browser_files(out, method.split('_')[1]))
            # Keep private facts before granting credit to this phase.
            (out/'scenarios.json').write_text(json.dumps(proof.evidence))
            return result

        phase('build', lambda: build(owned, sha, report['images']))
        if 'auction' in report['images']:
            phase('packaged', lambda: report.update(matrix=packaged_matrix(owned, report['images']['auction'])))
        phase('stack', app_stack, 'build')
        phase('publication', lambda: scenario('prepare_images'), 'stack')
        # Both browser paths need auction 01 to exist, not a passed seller policy test.
        phase('policy-auction', lambda: scenario('create', 'DEMO-WATCH-01', refresh=True), 'publication')
        phase('policy', lambda: scenario('policy_cases', results['policy-auction']), 'policy-auction')
        phase('browser-matrix', lambda: scenario('browser_matrix'), 'policy-auction')
        phase('browser-screens', lambda: scenario('browser_screens'), 'policy-auction')
        # Auction 03 (race) and 05 (fixed/close) have separate listing state.
        phase('race', lambda: scenario('race', refresh=True), 'publication')
        phase('fixed', lambda: scenario('fixed_deadline', refresh=True), 'publication')
        phase('late', lambda: report.update(late_guard=scenario('late_refusal', results['fixed'])), 'fixed')
        # Close and its unchanged-history read remain useful even if the late request failed.
        phase('close', lambda: scenario('close_result', results['fixed']), 'fixed')
        phase('historical', lambda: historical_orders(results['stack'][1]['auction']), 'stack')

    report['cleanup_incomplete'] = owned.incomplete
    report['complete'] = (all(row_state(deps) == 'pass' for deps in ROW_PHASES.values()) and not owned.incomplete
                          and report.get('late_guard') == 'deadline-specific')
    checkpoint()
    if not report['complete']:
        raise ProofError('diagnostic is not a complete acceptance proof; see the per-row summary')


def verify(out, sha):
    check = 'read receipt.json'
    try:
        report = json.loads((out/'receipt.json').read_text())
        check = 'receipt SHA matches the checked-out SHA'
        assert report['sha'] == sha
        check = 'receipt marks the diagnostic complete'
        assert report['complete'] is True
        check = 'receipt marks every required row PASS'
        assert report['rows'] == dict.fromkeys(ROW_PHASES, 'pass')
        check = 'receipt confirms teardown completed'
        assert not report['cleanup_incomplete']
        check = 'receipt has deadline-specific live admission evidence'
        assert report['late_guard'] == 'deadline-specific'
        check = 'receipt binds exactly the six required image IDs'
        assert set(report['images']) == set(APPS) and all(ID.fullmatch(image) for image in report['images'].values())
        check = 'packaged boundary matrix matches the pinned cases'
        assert report['matrix'] == expected_matrix(FIXTURES.read_text())
        check = 'browser evidence files validate and match the receipt'
        assert browser_files(out) == report['browser']
        check = 'read scenarios.json'
        facts = json.loads((out/'scenarios.json').read_text())
        check = 'scenario evidence includes publication, recovery, race and reserve close'
        assert {'published_private', 'lost_response_recovered', 'race', 'closed_below_reserve'} <= set().union(*facts)
    # Report fixed check names and failure categories, never raw exceptions or evidence values.
    except AssertionError:
        raise ProofError(f'verify: {check}: requirement not met') from None
    except FileNotFoundError:
        raise ProofError(f'verify: {check}: required file missing') from None
    except OSError:
        raise ProofError(f'verify: {check}: required file unreadable') from None
    except ValueError:
        raise ProofError(f'verify: {check}: invalid JSON or file contents') from None
    except (KeyError, TypeError, AttributeError):
        raise ProofError(f'verify: {check}: invalid evidence structure') from None
    except Exception:
        raise ProofError(f'verify: {check}: evidence check could not be evaluated') from None
    print(f'L12 connected image proof passed for {sha}: {len(ROW_PHASES)} required rows.')


if __name__ == '__main__':
    mode, directory, revision = sys.argv[1:]
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Linux'
            or Path(directory).resolve().parent != Path(os.environ['RUNNER_TEMP']).resolve()):
        raise SystemExit('The L12 image proof requires the dedicated ephemeral GitHub Linux runner.')
    os.umask(0o077)
    try:
        {'run': run, 'verify': verify}[mode](Path(directory), revision)
    except ProofError as error:
        raise SystemExit(f'L12 image proof: {error}') from None
    except Exception:
        raise SystemExit('L12 image proof: missing or invalid runner evidence') from None
