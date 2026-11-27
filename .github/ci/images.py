"""Build every Compose image with cached layers, then run the container smoke.

Usage:
  python3 .github/ci/images.py build
  python3 .github/ci/images.py smoke <report.json>

build reads the merged Compose configuration from infra/foundation/compose.sh, builds each
distinct image once with Buildx, in parallel, and loads it under every name Compose expects.
Layers are cached in the GitHub Actions cache, one scope per Dockerfile, so a warm run only
rebuilds what changed. It needs the Actions cache settings in its environment, which is why
the workflow starts it from a github-script step.

smoke runs the tracked container smoke (scripts/smoke.sh, the `make smoke` target) with
SKIP_BUILD=1 so it reuses the images just built, and with disposable signing keys.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get('RUNNER_TEMP') or '/tmp') / 'bt-images'
PROJECT = 'beirut-time'
KEYS = {'user': ('BT_AUTH_PRIVATE_KEY',),
        'event': ('BT_EVENT_PRIVATE_KEY', 'BT_SERVICE_AUTH_PRIVATE_KEY', 'BT_AUCTION_SERVICE_AUTH_PRIVATE_KEY',
                  'BT_PRICING_EVENT_PRIVATE_KEY', 'BT_TRUST_SERVICE_PRIVATE_KEY', 'BT_INTAKE_SERVICE_PRIVATE_KEY')}
PUBLIC = {'user': 'BT_AUTH_PUBLIC_KEY', 'event': 'BT_SERVICE_AUTH_PUBLIC_KEY'}


def compose_config():
    output = subprocess.run([str(ROOT / 'infra/foundation/compose.sh'), 'config', '--format', 'json'],
                            check=True, capture_output=True, text=True, cwd=ROOT).stdout
    return json.loads(output)


def targets(config):
    """One bake target per distinct build, tagged with every image name that uses it."""
    found = {}
    for name, service in sorted(config['services'].items()):
        build = service.get('build')
        if not build:
            continue
        context = Path(build.get('context', '.'))
        dockerfile = build.get('dockerfile', 'Dockerfile')
        args = {k: str(v) for k, v in sorted((build.get('args') or {}).items()) if v is not None}
        key = (str(context), dockerfile, json.dumps(args, sort_keys=True), build.get('target') or '')
        tag = service.get('image') or f'{PROJECT}-{name}'
        entry = found.setdefault(key, {'context': str(context), 'dockerfile': dockerfile, 'args': args,
                                       'tags': [], 'services': []})
        if build.get('target'):
            entry['target'] = build['target']
        if tag not in entry['tags']:
            entry['tags'].append(tag)
        entry['services'].append(name)
    bake = {}
    for entry in found.values():
        label = re.sub(r'[^a-z0-9]+', '-', f"{entry['dockerfile']}-{'-'.join(entry['args'].values())}".lower()).strip('-')
        scope = f'bt-{label}'
        target = {k: entry[k] for k in ('context', 'dockerfile', 'args', 'tags')}
        if 'target' in entry:
            target['target'] = entry['target']
        target.update({'cache-from': [f'type=gha,scope={scope}'], 'cache-to': [f'type=gha,mode=max,scope={scope}'],
                       'output': ['type=docker']})
        bake[label] = target
    return bake


def build():
    WORK.mkdir(parents=True, exist_ok=True)
    bake = targets(compose_config())
    plan = WORK / 'bake.json'
    plan.write_text(json.dumps({'group': {'default': {'targets': sorted(bake)}}, 'target': bake}, indent=2))
    print(f'Building {len(bake)} images: ' + ', '.join(sorted(bake)), flush=True)
    code = subprocess.run(['docker', 'buildx', 'bake', '--file', str(plan), '--progress', 'plain'], cwd=ROOT).returncode
    tags = sorted(t for target in bake.values() for t in target['tags'])
    missing = [t for t in tags if subprocess.run(['docker', 'image', 'inspect', t], capture_output=True).returncode]
    (WORK / 'build.json').write_text(json.dumps({'exit': code, 'images': len(bake), 'tags': tags, 'missing': missing}))
    return 1 if code or missing else 0


def keys():
    folder = WORK / 'keys'
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = {}
    for name in ('user', 'event'):
        private = folder / f'{name}.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out',
                        str(private)], check=True, capture_output=True)
        public = subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout'], check=True, capture_output=True,
                                text=True).stdout
        for variable in KEYS[name]:
            env[variable] = private.read_text()
        env[PUBLIC[name]] = public
    return env


def smoke(report):
    problems = []
    built = json.loads((WORK / 'build.json').read_text()) if (WORK / 'build.json').is_file() else None
    if built is None:
        problems.append('build: no build record')
    elif built['exit'] or built['missing']:
        problems.append(f"build: exit {built['exit']}, missing {built['missing']}")
    if problems:
        code = None
        problems.append('container smoke: not run, the images did not build')
    else:
        env = dict(os.environ, SKIP_BUILD='1', **keys())
        code = subprocess.run(['./scripts/smoke.sh'], cwd=ROOT, env=env, timeout=900).returncode
        if code:
            problems.append(f'container smoke: exit {code}')
            subprocess.run([str(ROOT / 'infra/foundation/compose.sh'), 'ps', '--all'], cwd=ROOT)
    steps = (['image build'] if built and not built['exit'] and not built['missing'] else []) + \
        (['container smoke'] if code == 0 else [])
    data = dict(suite='images', ok=not problems, problems=problems, steps=steps,
                images=built['images'] if built else 0)
    line = json.dumps(data, sort_keys=True, separators=(',', ':'))
    Path(report).write_text(line + '\n')
    print(line)
    return 0 if not problems else 1


if __name__ == '__main__':
    if sys.argv[1:2] == ['build']:
        sys.exit(build())
    if sys.argv[1:2] == ['smoke'] and len(sys.argv) == 3:
        sys.exit(smoke(sys.argv[2]))
    raise SystemExit(__doc__)
