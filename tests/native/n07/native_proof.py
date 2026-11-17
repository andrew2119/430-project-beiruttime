"""Isolated native production proof contract, schema version 1."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[3]
ROUTES = ['/operations/moderation', '/seller/dashboard']
PROOF_PATH = '/api/web/v1/identity/v1/foundation-origin-proof'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def response(url, headers=None, method='GET'):
    request = Request(url, headers=headers or {}, method=method,
                      data=b'{}' if method == 'POST' else None)
    try:
        result = build_opener(ProxyHandler({}), NoRedirect).open(request, timeout=5)
    except HTTPError as error:
        result = error
    with result:
        return result.status, dict((k.lower(), v) for k, v in result.headers.items()), result.read().decode()


def origin_cases(public, trusted):
    edge = {'X-Forwarded-Host': 'edge.test', 'X-Forwarded-Proto': 'https'}
    return [
        ({'Origin': public}, 200),
        ({'Origin': public, **edge}, 403 if trusted else 200),
        ({'Origin': 'http://0.0.0.0:3000'}, 403),
        ({'Origin': 'https://foreign.test'}, 403),
        ({'Origin': 'null'}, 403), ({}, 403),
        ({'Origin': 'https://edge.test', **edge}, 200 if trusted else 403),
        ({'Origin': 'https://foreign.test', **edge}, 403),
        ({'Origin': 'https://edge.test', **edge,
          'X-Forwarded-Host': 'edge.test,foreign.test'}, 403),
    ]


def plan(kind):
    common = {'schema_version': 1, 'kind': kind,
              'container_publication': 'container-only',
              'browser': {'state': 'deferred', 'requires': 'N09',
                          'locales': ['en', 'ar'], 'themes': ['light', 'dark'],
                          'widths': [1440, 390],
                          'assertions': ['path', 'query', 'language', 'direction', 'theme',
                                         'registration', 'internal-path', 'forwarded-locale', 'width', 'no-overflow']},
              'connected_requires': ['N01', 'N08'],
              'build': ['pnpm', '--filter', 'beirut-time-web', 'build']}
    if kind == 'origin':
        common['cases'] = [{'trusted': trusted, 'headers': headers, 'status': status}
                           for trusted in [False, True]
                           for headers, status in origin_cases('http://localhost:3000', trusted)]
        common['assertions'] = ['exact-transport-body', 'invalid_origin', 'same-origin-browser-fetch-deferred']
    else:
        common['cases'] = [{'route': route, 'locale': locale, 'method': method,
                            'probe': probe, 'query': query,
                            'headers': {} if not query else {'Cookie': 'bt-locale=' + ('ar' if locale == 'en' else 'en')},
                            'status': 200}
                           for route in ROUTES for locale in ['en', 'ar']
                           for method in ['GET', 'HEAD'] for probe in ['public', 'loopback']
                           for query in ['', 'view=open']]
        common['redirects'] = [{'route': route, 'locale': locale, 'statuses': [307, 308],
                                'query': 'view=open', 'hops': 1}
                               for route, locale in zip(ROUTES, ['en', 'ar'])]
        common['assertions'] = ['no-location', 'language', 'registration', 'internal-path',
                                'forwarded-locale', 'loopback-normalization']
    return common


def prepare(root, run_dir, kind):
    run_dir = run_dir.resolve()
    if run_dir == root or root in run_dir.parents:
        raise ValueError('Run directory must be outside the source tree')
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / kind
    target.mkdir()  # Never reuse or remove a preserved run.
    source = target / 'source'
    if any(path.is_symlink() for path in root.rglob('*')
           if 'node_modules' not in path.parts and '.git' not in path.parts):
        raise ValueError('Source symlinks require an explicit copy contract')
    shutil.copytree(root, source, symlinks=True, ignore=shutil.ignore_patterns('.git', 'node_modules', '.next', '__pycache__'))
    for dependency in root.rglob('node_modules'):
        relative = dependency.relative_to(root)
        if 'node_modules' not in relative.parts[:-1]:
            destination = source / relative
            shutil.copytree(dependency, destination, symlinks=True)
            for link in destination.rglob('*'):
                if not link.is_symlink():
                    continue
                installed = dependency / link.relative_to(destination)
                resolved = installed.resolve(strict=True)
                if resolved.is_relative_to(root):
                    resolved = source / resolved.relative_to(root)
                link.unlink()
                link.symlink_to(resolved, target_is_directory=installed.is_dir())
    fingerprints = {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(source.rglob('*')) if path.is_file() and not path.is_symlink()
                    and 'node_modules' not in path.parts}
    (target / 'source-fingerprints.json').write_text(json.dumps(fingerprints, sort_keys=True))
    registration = source / 'web/registrations/L00.ts'
    shutil.copyfile(registration, registration.with_name('foundation-original.ts'))
    fixtures = source / 'tests/foundation/fixtures/web'
    shutil.copyfile(fixtures / ('gateway-registration.ts' if kind == 'origin' else 'nested-registration.ts'), registration)
    if kind == 'proxy':
        # The fixture owns these routes only inside this source copy.
        for entry in sorted(registration.parent.glob('L[0-9][0-9].ts')):
            if entry == registration:
                continue
            original = entry.with_name('foundation-original-' + entry.name)
            entry.rename(original)
            entry.write_text(
                f"import original from './{original.stem}';\n"
                "export default { ...original, routes: original.routes.filter(\n"
                f"  route => !{json.dumps(ROUTES)}.includes(route.path)\n"
                ") };\n")
        app = source / 'web/app'
        for page in app.rglob('page.*'):
            if page.suffix not in {'.js', '.jsx', '.ts', '.tsx'}:
                continue
            segments = page.parent.relative_to(app).parts
            route = '/' + '/'.join(part for part in segments
                                   if not (part.startswith('(') and part.endswith(')')))
            if route in ROUTES:
                # Remove conflicting pages only in the fingerprinted run copy.
                page.unlink()
        for route in ROUTES:
            destination = source / 'web/app/(foundation-proxy-proof)' / route.lstrip('/') / 'page.tsx'
            destination.parent.mkdir(parents=True)
            shutil.copyfile(fixtures / 'nested-page.tsx', destination)
    return source


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def start(stack, command, cwd, environment, **options):
    process = subprocess.Popen(command, cwd=cwd, env=environment, **options)
    stack.callback(stop, process)
    return process


def build(command, cwd, timeout=900):
    """Bound the build and reap its isolated process group on every exit."""
    process = subprocess.Popen(command, cwd=cwd, start_new_session=True)
    try:
        status = process.wait(timeout=timeout)
        if status:
            raise subprocess.CalledProcessError(status, command)
    finally:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # The leader may have exited while descendants still occupy the group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def ready(process, origin):
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError('Production process exited before readiness')
        try:
            if response(origin + '/api/health')[0] == 200:
                return
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise RuntimeError('Production process readiness timed out')


def verify_origin(public, trusted):
    for headers, expected in origin_cases(public, trusted):
        status, _, text = response(public + PROOF_PATH, {'Content-Type': 'application/json', **headers}, 'POST')
        body = json.loads(text)
        assert status == expected, (headers, status, expected)
        if expected == 200:
            assert body == {'proof': 'synthetic-origin-transport', 'origin': headers['Origin']}, body
        else:
            assert body['error']['code'] == 'invalid_origin', body


def verify_proxy(public, loopback):
    for route in ROUTES:
        for locale in ['en', 'ar']:
            path = '/' + locale + route
            cookie = {'Cookie': 'bt-locale=' + ('ar' if locale == 'en' else 'en')}
            status, headers, body = response(public + path + '?view=open', cookie)
            assert status == 200 and 'location' not in headers
            for marker in [f'lang="{locale}"', f'data-locale="{locale}"',
                           f'data-path="{route}"', 'data-registered="true"']:
                assert marker in body, marker
            for origin in [public, loopback]:
                for method in ['GET', 'HEAD']:
                    for query, fields in [('', None), ('?view=open', cookie)]:
                        status, headers, _ = response(origin + path + query, fields, method)
                        assert status == 200 and 'location' not in headers
    for route, locale in zip(ROUTES, ['en', 'ar']):
        cookie = {'Cookie': 'bt-locale=' + locale}
        status, headers, _ = response(public + route + '?view=open', cookie)
        destination = headers.get('location', '')
        parsed = urlsplit(destination)
        assert status in {307, 308} and parsed.path == '/' + locale + route
        assert parsed.query == 'view=open'
        assert not parsed.netloc or (parsed.scheme, parsed.netloc) == (urlsplit(public).scheme, urlsplit(public).netloc)
        status, headers, _ = response(urljoin(public, destination), cookie)
        assert status == 200 and 'location' not in headers


def main(kind):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--origin', default='http://localhost:3000')
    parser.add_argument('--loopback', action='store_true')
    parser.add_argument('--browser', action='store_true')
    args = parser.parse_args()
    if args.plan:
        print(json.dumps(plan(kind), indent=2))
        return
    if args.browser:
        parser.error('Browser interface N09 is unavailable; connected proof remains deferred')
    if not args.run_dir:
        parser.error('--run-dir is required for execution')
    origin = urlsplit(args.origin)
    if (origin.scheme != 'http' or origin.hostname not in {'localhost', '127.0.0.1'}
            or not origin.port or origin.path or origin.query or origin.fragment or origin.username):
        parser.error('--origin requires a plain explicit-port loopback HTTP origin')
    source = prepare(ROOT, args.run_dir, kind)
    build(plan(kind)['build'], source)
    runtime = source / 'web/.next/standalone'
    shutil.copytree(source / 'web/.next/static', runtime / 'web/.next/static', dirs_exist_ok=True)
    shutil.copytree(source / 'web/public', runtime / 'web/public', dirs_exist_ok=True)
    for trusted in ([False, True] if kind == 'origin' else [False]):
        with ExitStack() as stack:
            processes = []
            environment = {**os.environ, 'NODE_ENV': 'production', 'HOSTNAME': '127.0.0.1',
                           'PORT': str(origin.port), 'BT_PUBLIC_WEB_ORIGINS': '' if trusted else args.origin,
                           'BT_TRUST_FORWARDED_ORIGIN': str(trusted).lower()}
            internal_port = origin.port
            if args.loopback and kind == 'proxy':
                with socket.socket() as reservation:
                    reservation.bind(('127.0.0.1', 0))
                    internal_port = reservation.getsockname()[1]
                environment['PORT'] = str(internal_port)
            if kind == 'origin':
                listener = stack.enter_context(socket.socket())
                listener.bind(('127.0.0.1', 0))
                listener.listen()
                environment['IDENTITY_API_URL'] = f'http://127.0.0.1:{listener.getsockname()[1]}'
                environment['BT_PROOF_FD'] = str(listener.fileno())
                # Transport metadata only; no business operation is implemented.
                upstream = start(stack, ['node', '-e', "require('http').createServer((q,s)=>{q.resume();s.setHeader('Content-Type','application/json');s.end(JSON.stringify({proof:'synthetic-origin-transport',origin:q.headers.origin||null}))}).listen({fd:Number(process.env.BT_PROOF_FD)})"], runtime, environment, pass_fds=(listener.fileno(),))
                processes.append(upstream)
            process = start(stack, ['node', 'web/server.js'], runtime, environment)
            processes.append(process)
            ready(process, f'http://127.0.0.1:{internal_port}')
            if args.loopback and kind == 'proxy':
                forwarder = start(stack, ['node', '-e',
                    "const net=require('net');net.createServer(c=>{const s=net.connect(Number(process.env.PORT),'127.0.0.1');c.pipe(s).pipe(c);s.on('error',()=>c.destroy());c.on('error',()=>s.destroy())}).listen(Number(process.env.BT_PROOF_PUBLIC_PORT),'127.0.0.1')"],
                    runtime, {**environment, 'BT_PROOF_PUBLIC_PORT': str(origin.port)})
                processes.append(forwarder)
                ready(forwarder, args.origin)
            if kind == 'origin':
                verify_origin(args.origin, trusted)
            else:
                verify_proxy(args.origin, f'http://127.0.0.1:{internal_port}')
            if any(child.poll() is not None for child in processes):
                raise RuntimeError('An owned transport process exited during proof')
    print('Native transport assertions passed; browser and container publication remain deferred.')
