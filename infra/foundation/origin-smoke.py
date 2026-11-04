"""Verify public gateway origins in a production image behind Docker and an explicit trusted edge."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
PATH = '/api/web/v1/identity/v1/foundation-origin-proof'
# This upstream only echoes transport metadata; it implements no Identity behavior.
WRAPPER = "require('http').createServer((q,s)=>{q.resume();s.setHeader('Content-Type','application/json');s.end(JSON.stringify({proof:'synthetic-origin-transport',origin:q.headers.origin||null}))}).listen(8000,'127.0.0.1');require('child_process').spawn(process.execPath,['web/server.js'],{stdio:'inherit'})"


def response(url, headers=None):
    request = Request(url, data=b'{}' if headers is not None else None, headers=headers or {})
    try:
        result = urlopen(request, timeout=10)
    except HTTPError as error:
        result = error
    with result:
        return result.status, json.loads(result.read())


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    tag = 'beirut-time/foundation-origin-proof:' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:8] + '-' + str(os.getpid())
    run('docker', 'build', '-f', 'web/Dockerfile', '--build-arg', 'FOUNDATION_GATEWAY_PROOF=1', '-t', tag, '.')
    evidence = []
    for trusted in [False, True]:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        public = f'http://localhost:{port}'
        allowed = '' if trusted else public
        container = subprocess.check_output(['docker', 'run', '--rm', '-d', '--read-only', '--tmpfs', '/tmp',
            '--memory', '512m', '--cpus', '1', '-p', f'127.0.0.1:{port}:3000', '-e', 'HOSTNAME=0.0.0.0',
            '-e', 'BT_PUBLIC_WEB_ORIGINS=' + allowed, '-e', 'BT_TRUST_FORWARDED_ORIGIN=' + str(trusted).lower(),
            '-e', 'IDENTITY_API_URL=http://127.0.0.1:8000', '--entrypoint', 'node', tag, '-e', WRAPPER], text=True).strip()
        try:
            for _ in range(60):
                try:
                    if response(public + '/api/health')[0] == 200:
                        break
                except (URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(1)
            else:
                raise AssertionError('Production gateway did not become ready')
            edge = {'X-Forwarded-Host': 'beirut.up.railway.app', 'X-Forwarded-Proto': 'https'}
            cases = [
                # Next advertises the incoming authority when no edge headers are supplied.
                ({'Origin': public}, 200),
                ({'Origin': public, **edge}, 403 if trusted else 200),
                ({'Origin': 'http://0.0.0.0:3000'}, 403),
                ({'Origin': 'https://foreign.test'}, 403),
                ({'Origin': 'null'}, 403),
                ({}, 403),
                ({'Origin': 'https://beirut.up.railway.app', **edge}, 200 if trusted else 403),
                ({'Origin': 'https://foreign.test', **edge}, 403),
                ({'Origin': 'https://beirut.up.railway.app', **edge, 'X-Forwarded-Host': 'beirut.up.railway.app,foreign.test'}, 403),
            ]
            for headers, expected in cases:
                status, body = response(public + PATH, {'Content-Type': 'application/json', **headers})
                assert status == expected, (trusted, headers, status, body)
                if status == 200:
                    assert body == {'proof': 'synthetic-origin-transport', 'origin': headers['Origin']}, body
                else:
                    assert body['error']['code'] == 'invalid_origin', body
                evidence.append({'trustedProxy': trusted, 'origin': headers.get('Origin'), 'status': status})
            if not trusted:
                environment = {**os.environ, 'CHROME_DEVTOOLS_AXI_SESSION': 'bt-foundation-origin-' + str(os.getpid())}
                try:
                    run('chrome-devtools-axi', 'open', public + '/en', env=environment, stdout=subprocess.DEVNULL)
                    source = f"const r=await page.eval(async()=>{{const r=await fetch('{PATH}',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}});return {{status:r.status,body:await r.json()}}}});if(r.status!==200||r.body.origin!=={json.dumps(public)})throw new Error(JSON.stringify(r));console.log(JSON.stringify(r));"
                    run('chrome-devtools-axi', 'run', input=source, text=True, env=environment)
                finally:
                    run('chrome-devtools-axi', 'stop', env=environment, stdout=subprocess.DEVNULL)
        finally:
            run('docker', 'stop', container, stdout=subprocess.DEVNULL)
    (ROOT / 'artifacts').mkdir(exist_ok=True)
    (ROOT / 'artifacts/origin-production.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('Production Docker-published and explicitly trusted proxy origins passed; forbidden origins stayed rejected.')


if __name__ == '__main__':
    main()
