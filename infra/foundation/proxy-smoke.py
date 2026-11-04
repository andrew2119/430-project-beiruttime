"""Exercise locale handling on nested routes in a real production Next.js image."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import build_opener, HTTPRedirectHandler, Request

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def response(url, cookie=''):
    request = Request(url, headers={'Cookie': cookie})
    try:
        result = build_opener(NoRedirect).open(request, timeout=5)
    except HTTPError as error:
        result = error
    with result:
        return result.status, {key.lower(): value for key, value in result.headers.items()}, result.read().decode()


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', action='store_true', help='also check both locales/themes at desktop and phone widths')
    parser.add_argument('--loopback', action='store_true', help='bind Next to 127.0.0.1 behind a transparent local TCP forwarder')
    parser.add_argument('--overlay', type=Path, help='published lane web/packages trees, copied only inside this test build')
    args = parser.parse_args()
    tag = 'beirut-time/foundation-proxy-proof:' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:8] + '-' + str(os.getpid())
    if args.overlay:
        dockerfile = (ROOT / 'web/Dockerfile').read_text().replace('COPY . .', 'COPY . .\nCOPY --from=route-repro . .')
        run('docker', 'build', '-f', '-', '--build-context', 'route-repro=' + str(args.overlay.resolve()), '-t', tag, '.', input=dockerfile, text=True)
    else:
        run('docker', 'build', '-f', 'web/Dockerfile', '--build-arg', 'FOUNDATION_PROXY_PROOF=1', '-t', tag, '.')
    listening_port = '3001' if args.loopback else '3000'
    command = ['docker', 'run', '--rm', '-d', '--read-only', '--tmpfs', '/tmp',
        '--memory', '512m', '--cpus', '1', '-p', '127.0.0.1::' + listening_port]
    if args.loopback:
        # Real loopback binding exposes NextURL's 127.0.0.1 -> localhost normalization.
        # The transparent TCP forwarder only makes that private listener reachable by this host.
        forwarder = "require('child_process').spawn(process.execPath,['web/server.js'],{stdio:'inherit'});const net=require('net');net.createServer(c=>{const s=net.connect(3000,'127.0.0.1');c.pipe(s).pipe(c);s.on('error',()=>c.destroy());c.on('error',()=>s.destroy())}).listen(3001,'0.0.0.0')"
        command += ['-e', 'HOSTNAME=127.0.0.1', '--entrypoint', 'node', tag, '-e', forwarder]
    else:
        command += [tag]
    container = subprocess.check_output(command, text=True).strip()
    try:
        port = subprocess.check_output(['docker', 'port', container, listening_port + '/tcp'], text=True).strip().rsplit(':', 1)[1]
        origin = 'http://127.0.0.1:' + port
        for _ in range(60):
            try:
                if response(origin + '/api/health')[0] == 200:
                    break
            except (URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(1)
        else:
            raise AssertionError('Production web image did not become ready')
        checks = []
        routes = ['/operations/moderation', '/seller/auctions' if args.overlay else '/seller/dashboard']
        for public, internal, locale, cookie in [('/' + locale + route, route, locale, 'bt-locale=' + ('ar' if locale == 'en' else 'en'))
                for locale in ['en', 'ar'] for route in routes]:
            status, headers, body = response(origin + public + '?view=open', cookie)
            check = {'path': public, 'status': status, 'location': headers.get('location'),
                     'rewrite': headers.get('x-middleware-rewrite')}
            checks.append(check)
            assert status == 200, check
            assert 'location' not in headers, check
            for method in ['GET', 'HEAD']:
                curl = subprocess.check_output(['curl', '-sS', '--max-redirs', '0', '--max-time', '10',
                    '-D', '-', '-o', '/dev/null', *(['--head'] if method == 'HEAD' else []), origin + public], text=True)
                assert curl.splitlines()[0].split()[1] == '200' and '\nlocation:' not in curl.lower(), curl
            assert f'lang="{locale}"' in body, check
            if not args.overlay:
                assert f'data-locale="{locale}"' in body and f'data-path="{internal}"' in body and 'data-registered="true"' in body, check
            for method in ['GET', 'HEAD']:
                probe = subprocess.check_output(['docker', 'exec', container, 'node', '-e',
                    f"fetch('http://127.0.0.1:3000{public}',{{method:'{method}',redirect:'manual'}}).then(async r=>console.log(JSON.stringify({{status:r.status,location:r.headers.get('location')}})))"], text=True)
                assert json.loads(probe)['status'] == 200, probe
        for internal, locale in [(routes[0], 'en'), (routes[1], 'ar')]:
            status, headers, _ = response(origin + internal + '?view=open', 'bt-locale=' + locale)
            destination = headers.get('location', '')
            check = {'path': internal, 'status': status, 'location': destination}
            checks.append(check)
            assert status in {307, 308} and urlparse(destination).path == '/' + locale + internal, check
            assert urlparse(destination).query == 'view=open', check
            assert response(urljoin(origin, destination), 'bt-locale=' + locale)[0] == 200, check
        (ROOT / 'artifacts').mkdir(exist_ok=True)
        (ROOT / 'artifacts/proxy-production.json').write_text(json.dumps(checks, indent=2) + '\n')
        if args.browser:
            environment = {**os.environ, 'CHROME_DEVTOOLS_AXI_SESSION': 'bt-foundation-proxy-' + str(os.getpid())}
            source = (ROOT / 'tests/foundation/browser-nested-routes.js').read_text().replace('PROOF_ORIGIN', json.dumps(origin)).replace('PROOF_ROUTES', json.dumps(routes)).replace('PROOF_FIXTURE', 'false' if args.overlay else 'true')
            try:
                run('chrome-devtools-axi', 'open', origin + '/en', env=environment, stdout=subprocess.DEVNULL)
                for name, viewport in [('desktop', '1440x900x1'), ('phone', '390x844x3,mobile,touch')]:
                    run('chrome-devtools-axi', 'emulate', '--viewport', viewport, env=environment, stdout=subprocess.DEVNULL)
                    with (ROOT / f'artifacts/proxy-browser-{name}.json').open('w') as evidence:
                        run('chrome-devtools-axi', 'run', input=source.replace('PROOF_WIDTH', '1440' if name == 'desktop' else '390'), text=True, env=environment, stdout=evidence)
            finally:
                run('chrome-devtools-axi', 'stop', env=environment, stdout=subprocess.DEVNULL)
        print('Production nested-route locale rewrites and single-hop locale redirects passed.')
    finally:
        run('docker', 'stop', container, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
