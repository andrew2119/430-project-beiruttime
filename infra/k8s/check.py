"""Fail when the Kubernetes demo drifts from the Railway and Compose definitions it mirrors.

Usage: python3 infra/k8s/check.py <compose-config.json> <rendered-manifests.json> <kind-cluster.json>

The first file is the merged local stack, `infra/foundation/compose.sh config --format json`.
The second is `kubectl kustomize infra/k8s` as one JSON array (`yq ea -o=json '[.]'`).
The third is infra/k8s/kind.yaml as JSON (`yq -o=json`).
`infra/k8s/demo.sh check` produces all three and runs this script.
It also reads infra/railway/*.json, infra/foundation/postgres-init.sh and infra/k8s/kustomization.yaml
itself. This script needs only the Python standard library; producing its inputs needs Compose,
kubectl and yq, but no cluster.

What it holds the demo to, beyond matching Railway and Compose:
- the only way in from outside the cluster is kind's one mapping of the site's NodePort to
  127.0.0.1:3000; every other Service stays inside the cluster, and no Service sets externalIPs,
  a load balancer or any other way out;
- the stack is exactly the namespace, one Deployment, Job and Service per Railway service, and the
  site's and Postgres's Deployment and Service;
- no pod uses the node's network, process or IPC namespace, a node folder or a host port;
- every app variable is listed one by one (no envFrom), so each one is compared with Compose;
- the images are built with Compose's context, Dockerfile and build arguments and nothing else.

Deliberate differences from Compose, and nothing else:
- signing keys and database passwords come from the two Secrets demo.sh generates in each run;
- each database URL takes its password from DB_PASSWORD or OWNER_PASSWORD, read from that Secret;
- Identity's BT_ALLOWED_WEB_ORIGINS lists exactly the origins the site publishes (web's
  BT_PUBLIC_WEB_ORIGINS), as the Identity accounts contract requires;
- the migration runs Railway's preDeployCommand, so its owner URL is BT_MIGRATION_DATABASE_URL.
"""
import json
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / 'infra/k8s'
NAMESPACE = 'beirut-time'
PART_OF = 'app.kubernetes.io/part-of'
NAME, COMPONENT = 'app.kubernetes.io/name', 'app.kubernetes.io/component'
PASSWORDS, KEYS, INIT = 'database-passwords', 'signing-keys', 'postgres-init'
SERVICE_PORT, SITE_PORT, NODE_PORT = 8000, 3000, 30080
APP_USER = 10001
# Each signing variable reads one of the two demo key pairs demo.sh generates per run.
SIGNING = {
    'BT_AUTH_PRIVATE_KEY': 'user-private-key',
    'BT_AUTH_PUBLIC_KEY': 'user-public-key',
    'BT_SERVICE_AUTH_PUBLIC_KEY': 'service-public-key',
    'BT_EVENT_PRIVATE_KEY': 'service-private-key',
    'BT_SERVICE_AUTH_PRIVATE_KEY': 'service-private-key',
    'BT_PRICING_EVENT_PRIVATE_KEY': 'service-private-key',
    'BT_TRUST_SERVICE_PRIVATE_KEY': 'service-private-key',
    'BT_INTAKE_SERVICE_PRIVATE_KEY': 'service-private-key',
}
URL = re.compile(r'postgresql://(?P<user>[^:@/]+):(?P<password>[^@]*)@(?P<host>[^/@]+)/(?P<db>[^/?]+)')
COMPOSE_UNITS = {'': 1, 'b': 1, 'k': 1024, 'kb': 1024, 'm': 1024 ** 2, 'mb': 1024 ** 2, 'g': 1024 ** 3, 'gb': 1024 ** 3}
K8S_UNITS = {'': 1, 'Ki': 1024, 'Mi': 1024 ** 2, 'Gi': 1024 ** 3, 'k': 1000, 'M': 1000 ** 2, 'G': 1000 ** 3}

problems = []


def expect(condition, where, message):
    if not condition:
        problems.append(f'{where}: {message}')
    return bool(condition)


def deep(value, *keys):
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def compose_bytes(value):
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*([a-zA-Z]*)', str(value).strip())
    return int(float(match[1]) * COMPOSE_UNITS[match[2].lower()]) if match and match[2].lower() in COMPOSE_UNITS else None


def k8s_bytes(value):
    match = re.fullmatch(r'(\d+)([a-zA-Z]*)', str(value or ''))
    return int(match[1]) * K8S_UNITS[match[2]] if match and match[2] in K8S_UNITS else None


def k8s_cpu(value):
    text = str(value or '')
    try:
        return float(text[:-1]) / 1000 if text.endswith('m') else float(text)
    except ValueError:
        return None


def compose_memory(service):
    return compose_bytes(service.get('mem_limit') or deep(service, 'deploy', 'resources', 'limits', 'memory'))


def compose_cpus(service):
    value = service.get('cpus') or deep(service, 'deploy', 'resources', 'limits', 'cpus')
    return float(value) if value not in (None, '', 0) else None


def compose_env(service):
    env = service.get('environment') or {}
    if isinstance(env, list):
        env = dict(item.split('=', 1) if '=' in item else (item, None) for item in env)
    return {key: '' if value is None else str(value) for key, value in env.items()}


def database_url(value):
    match = URL.fullmatch(value or '')
    return match.groupdict() if match else None


def init_databases():
    text = (ROOT / 'infra/foundation/postgres-init.sh').read_text()
    match = re.search(r'^for service in ([a-z_ ]+); do$', text, re.M)
    return match[1].split() if match else []


def index(rendered):
    objects = {}
    for item in rendered:
        if not isinstance(item, dict):
            continue
        key = (item.get('kind'), deep(item, 'metadata', 'name'))
        expect(key not in objects, f'{key[0]}/{key[1]}', 'is defined twice')
        objects[key] = item
    return objects


def env_entries(where, container):
    entries = {}
    for entry in container.get('env') or []:
        expect(entry['name'] not in entries, where, f'sets {entry["name"]} twice')
        entries[entry['name']] = entry
    return entries


def literal(entry):
    return None if 'valueFrom' in entry else str(entry.get('value', ''))


def secret_ref(entry):
    ref = deep(entry, 'valueFrom', 'secretKeyRef') or {}
    return ref.get('name'), ref.get('key')


def defined_before(where, container, first, then):
    names = [entry['name'] for entry in container.get('env') or []]
    if first in names and then in names:
        expect(names.index(first) < names.index(then), where, f'{first} must come before {then}, which reads it')


def one_container(where, workload):
    containers = deep(workload, 'spec', 'template', 'spec', 'containers') or []
    expect(len(containers) == 1, where, f'has {len(containers)} containers, expected 1')
    expect(not deep(workload, 'spec', 'template', 'spec', 'initContainers'), where, 'has init containers')
    return containers[0] if containers else {}


def check_labels(where, workload, name, component):
    wanted = {NAME: name, COMPONENT: component}
    labels = deep(workload, 'metadata', 'labels') or {}
    template = deep(workload, 'spec', 'template', 'metadata', 'labels') or {}
    expect(all(labels.get(k) == v for k, v in wanted.items()), where, f'labels must include {wanted}')
    expect(all(template.get(k) == v for k, v in wanted.items()), where, f'pod labels must include {wanted}')
    selector = deep(workload, 'spec', 'selector', 'matchLabels')
    if workload.get('kind') == 'Deployment':
        expect(selector == wanted, where, f'selector must be exactly {wanted}')


def check_pod(where, workload, *, restricted=True, read_only=True):
    pod = deep(workload, 'spec', 'template', 'spec') or {}
    expect(pod.get('automountServiceAccountToken') is False, where, 'must not mount a service account token')
    expect(pod.get('enableServiceLinks') is False, where, 'must not inject service link variables')
    expect(not any(pod.get(key) for key in ('hostNetwork', 'hostPID', 'hostIPC')), where,
           "must not use the node's network, process or IPC namespace")
    expect(not any('hostPath' in volume for volume in pod.get('volumes') or []), where, 'must not mount a node folder')
    for container in pod.get('containers') or []:
        expect(container.get('imagePullPolicy') == 'Never', where, 'images are loaded into the cluster, never pulled')
        expect(not any('hostPort' in port or 'hostIP' in port for port in container.get('ports') or []), where,
               "must not publish a host port; the site's NodePort is the one way in")
    if not restricted:
        return
    context = pod.get('securityContext') or {}
    expect(context.get('runAsNonRoot') is True and context.get('runAsUser') == APP_USER
           and context.get('runAsGroup') == APP_USER, where, f'must run as the image user {APP_USER}, never root')
    expect(deep(context, 'seccompProfile', 'type') == 'RuntimeDefault', where, 'needs the RuntimeDefault seccomp profile')
    volumes = {v.get('name'): v for v in pod.get('volumes') or []}
    for container in pod.get('containers') or []:
        expect(not container.get('envFrom'), where,
               'must list each variable under env, never import them with envFrom, so each one is checked')
        own = container.get('securityContext') or {}
        expect(own.get('allowPrivilegeEscalation') is False, where, 'must forbid privilege escalation')
        expect(deep(own, 'capabilities', 'drop') == ['ALL'], where, 'must drop every capability')
        if read_only:
            expect(own.get('readOnlyRootFilesystem') is True, where, 'needs a read-only root filesystem, as in Compose')
            tmp = [m for m in container.get('volumeMounts') or [] if m.get('mountPath') == '/tmp']
            expect(len(tmp) == 1 and 'emptyDir' in volumes.get(tmp[0].get('name'), {}), where,
                   'needs a writable /tmp from an emptyDir, like the Compose tmpfs')


def check_limits(where, container, service, *, cpu_request=None):
    limits = deep(container, 'resources', 'limits') or {}
    requests = deep(container, 'resources', 'requests') or {}
    memory = compose_memory(service)
    expect(memory is not None and k8s_bytes(limits.get('memory')) == memory, where,
           f'memory limit {limits.get("memory")} differs from Compose ({memory} bytes)')
    cpus = compose_cpus(service)
    if cpus is None:
        expect('cpu' not in limits, where, 'Compose sets no CPU limit')
    else:
        expect(k8s_cpu(limits.get('cpu')) == cpus, where, f'CPU limit {limits.get("cpu")} differs from Compose ({cpus})')
    expect(k8s_bytes(requests.get('memory')) is not None and k8s_cpu(requests.get('cpu')) is not None, where,
           'needs CPU and memory requests so the node schedules it')


def check_probes(where, container, ready_path, timeout, port, live_path):
    def probe(kind):
        value = container.get(kind) or {}
        return value, value.get('httpGet') or {}
    startup, startup_get = probe('startupProbe')
    readiness, readiness_get = probe('readinessProbe')
    liveness, liveness_get = probe('livenessProbe')
    expect(startup_get.get('path') == ready_path and startup_get.get('port') == port, where,
           f'startup probe must be GET {ready_path} on {port} (the Railway health check)')
    budget = startup.get('periodSeconds', 10) * startup.get('failureThreshold', 3)
    expect(budget == timeout, where, f'startup probe allows {budget} s, Railway allows {timeout} s')
    expect(readiness_get.get('path') == ready_path and readiness_get.get('port') == port, where,
           f'readiness probe must be GET {ready_path} on {port}')
    expect(liveness_get.get('path') == live_path and liveness_get.get('port') == port, where,
           f'liveness probe must be GET {live_path} on {port}')


def check_service(where, objects, name, component, port, *, node_port=None):
    service = objects.get(('Service', name))
    if not expect(service, where, f'has no Service {name}'):
        return
    spec = service.get('spec') or {}
    extra = sorted(set(spec) - {'type', 'selector', 'ports'})
    expect(not extra, where, f'Service {name} sets {extra}; only type, selector and ports are allowed, so nothing '
           'publishes it another way (externalIPs, a load balancer or an external name)')
    expect(spec.get('selector') == {NAME: name, COMPONENT: component}, where,
           f'Service {name} must select exactly its own {component} pods')
    labels = deep(service, 'metadata', 'labels') or {}
    expect(labels.get(NAME) == name and labels.get(COMPONENT) == component, where,
           f'Service {name} must carry name {name} and component {component} so it deploys with its pods')
    ports = spec.get('ports') or []
    keys = {'name', 'port', 'targetPort', 'protocol'} | ({'nodePort'} if node_port else set())
    expect(len(ports) == 1 and ports[0].get('port') == port and ports[0].get('targetPort') == port
           and ports[0].get('protocol', 'TCP') == 'TCP' and set(ports[0]) <= keys, where,
           f'Service {name} must expose TCP port {port} and nothing else')
    if node_port is None:
        expect(spec.get('type', 'ClusterIP') == 'ClusterIP', where, f'Service {name} must stay inside the cluster')
    else:
        expect(spec.get('type') == 'NodePort' and ports and ports[0].get('nodePort') == node_port, where,
               f'Service {name} must be the NodePort {node_port} entry point')


def check_python_service(name, railway, compose, objects, databases, origins):
    where = name
    config = railway.get(name) or {}
    deploy = config.get('deploy') or {}
    build = config.get('build') or {}
    runtime = compose.get(name)
    migrate = compose.get(f'{name}-migrate')
    if not (expect(runtime, where, 'is missing from Compose') and expect(migrate, where, f'{name}-migrate is missing from Compose')):
        return None
    image = f'beirut-time/{name}:local'
    expect(runtime.get('image') == image and migrate.get('image') == image, where, f'Compose images must be {image}')
    expect(build.get('builder') == 'DOCKERFILE', where, 'Railway must build from a Dockerfile')
    check_build(where, runtime, build.get('dockerfilePath'))

    # The one-time migration: Railway's preDeployCommand with the owner URL.
    job = objects.get(('Job', f'{name}-migrate'))
    if expect(job, where, f'has no Job {name}-migrate'):
        job_where = f'Job/{name}-migrate'
        check_labels(job_where, job, name, 'migration')
        check_pod(job_where, job, read_only=False)
        spec = job.get('spec') or {}
        expect(spec.get('backoffLimit') == 0, job_where, 'must run once (backoffLimit 0), like a pre-deploy command')
        expect(deep(spec, 'template', 'spec', 'restartPolicy') == 'Never', job_where, 'must not restart')
        container = one_container(job_where, job)
        expect(container.get('image') == image, job_where, f'image must be {image}')
        commands = deploy.get('preDeployCommand') or []
        expect(len(commands) == 1, where, 'Railway must have exactly one preDeployCommand')
        if commands:
            expected = shlex.split(commands[0])
            expect(container.get('command') == expected and not container.get('args'), job_where,
                   f'command must be the Railway preDeployCommand {expected}')
            expect(' '.join(migrate.get('command') or []) in commands[0], where,
                   'Compose and Railway must run the same migration module')
        env = env_entries(job_where, container)
        wanted = compose_env(migrate)
        expect(set(env) == {'BT_SERVICE_NAME', 'OWNER_PASSWORD', 'BT_MIGRATION_DATABASE_URL'}
               and set(wanted) == {'BT_SERVICE_NAME', 'BT_DATABASE_URL'}, job_where,
               f'environment {sorted(env)} must be BT_SERVICE_NAME plus the owner URL, as in Compose {sorted(wanted)}')
        if 'BT_SERVICE_NAME' in env:
            expect(literal(env['BT_SERVICE_NAME']) == wanted.get('BT_SERVICE_NAME'), job_where, 'BT_SERVICE_NAME differs from Compose')
        owner = database_url(wanted.get('BT_DATABASE_URL'))
        ours = database_url(literal(env.get('BT_MIGRATION_DATABASE_URL', {'valueFrom': {}})))
        if expect(owner and ours, job_where, 'needs a postgresql:// owner URL'):
            expect({**ours, 'password': None} == {**owner, 'password': None}, job_where,
                   f'owner URL {ours} differs from Compose {owner} beyond the password')
            expect(ours['password'] == '$(OWNER_PASSWORD)', job_where, 'owner URL must read its password from OWNER_PASSWORD')
            database = owner['db'].removeprefix('bt_')
            expect(secret_ref(env.get('OWNER_PASSWORD', {})) == (PASSWORDS, f'{database.upper()}_OWNER_PASSWORD'),
                   job_where, f'OWNER_PASSWORD must come from {PASSWORDS}/{database.upper()}_OWNER_PASSWORD')
        defined_before(job_where, container, 'OWNER_PASSWORD', 'BT_MIGRATION_DATABASE_URL')

    # The service itself: Railway's startCommand and health check, Compose's environment and limits.
    database = None
    workload = objects.get(('Deployment', name))
    if expect(workload, where, f'has no Deployment {name}'):
        dep_where = f'Deployment/{name}'
        check_labels(dep_where, workload, name, 'service')
        check_pod(dep_where, workload)
        container = one_container(dep_where, workload)
        expect(container.get('image') == image, dep_where, f'image must be {image}')
        expected = shlex.split(deploy.get('startCommand') or '')
        expect(expected and container.get('command') == expected and not container.get('args'), dep_where,
               f'command must be the Railway startCommand {expected}')
        expect([p.get('containerPort') for p in container.get('ports') or []] == [SERVICE_PORT], dep_where,
               f'must listen on {SERVICE_PORT}')
        check_probes(dep_where, container, deploy.get('healthcheckPath'), deploy.get('healthcheckTimeout'),
                     SERVICE_PORT, '/health/live')
        check_limits(dep_where, container, runtime)
        env = env_entries(dep_where, container)
        wanted = compose_env(runtime)
        expect(set(env) == set(wanted) | {'DB_PASSWORD'}, dep_where,
               f'environment differs from Compose: missing {sorted(set(wanted) - set(env))}, '
               f'extra {sorted(set(env) - set(wanted) - {"DB_PASSWORD"})}')
        for key, value in sorted(wanted.items()):
            entry = env.get(key)
            if entry is None:
                continue
            if key == 'BT_DATABASE_URL':
                theirs, ours = database_url(value), database_url(literal(entry))
                if expect(theirs and ours, dep_where, 'needs a postgresql:// BT_DATABASE_URL'):
                    expect({**ours, 'password': None} == {**theirs, 'password': None}, dep_where,
                           f'BT_DATABASE_URL {ours} differs from Compose {theirs} beyond the password')
                    expect(ours['password'] == '$(DB_PASSWORD)', dep_where, 'BT_DATABASE_URL must read DB_PASSWORD')
                    database = theirs['db'].removeprefix('bt_')
                    expect(secret_ref(env.get('DB_PASSWORD', {})) == (PASSWORDS, f'{database.upper()}_DB_PASSWORD'),
                           dep_where, f'DB_PASSWORD must come from {PASSWORDS}/{database.upper()}_DB_PASSWORD')
            elif key in SIGNING:
                expect(value == '', dep_where, f'{key} is a literal in Compose; expected a supplied key')
                expect(secret_ref(entry) == (KEYS, SIGNING[key]), dep_where, f'{key} must come from {KEYS}/{SIGNING[key]}')
            elif key == 'BT_ALLOWED_WEB_ORIGINS':
                expect(origins is not None and literal(entry) == origins, dep_where,
                       f'BT_ALLOWED_WEB_ORIGINS must equal the site BT_PUBLIC_WEB_ORIGINS ({origins})')
            else:
                expect(literal(entry) == value, dep_where, f'{key} is {literal(entry)!r}, Compose has {value!r}')
        defined_before(dep_where, container, 'DB_PASSWORD', 'BT_DATABASE_URL')
        expect(database in databases, dep_where, f'database {database} is not created by postgres-init.sh')
    check_service(where, objects, name, 'service', SERVICE_PORT)
    return database


def check_build(where, service, dockerfile):
    build = service.get('build') or {}
    context = Path(build.get('context') or '.')
    context = context if context.is_absolute() else ROOT / context
    expect(context.resolve() == ROOT.resolve(), where, 'Compose must build from the repository root, as Railway does')
    file = Path(build.get('dockerfile') or 'Dockerfile')
    file = file.resolve().relative_to(ROOT.resolve()) if file.is_absolute() else file
    expect(dockerfile and file.as_posix() == dockerfile, where,
           f'Compose builds {file.as_posix()}, Railway builds {dockerfile}')
    expect(not build.get('target'), where, 'Compose must build the final Dockerfile stage, as Railway does')
    extra = sorted(set(build) - {'context', 'dockerfile', 'args', 'target'})
    expect(not extra, where, f'Compose build sets {extra}; demo.sh builds with only the context, Dockerfile and '
           'build arguments, so the demo image would differ from the Compose one')
    args = build.get('args') or {}
    expect(isinstance(args, dict) and all(isinstance(v, str) for v in args.values()), where,
           'Compose build arguments must be names with values, which demo.sh passes to the build unchanged')


def check_web(railway, compose, objects):
    where = 'web'
    config = railway.get('web') or {}
    deploy = config.get('deploy') or {}
    runtime = compose.get('web')
    if not expect(runtime, where, 'is missing from Compose'):
        return None
    expect(not deploy.get('startCommand') and not deploy.get('preDeployCommand'), where,
           'Railway runs the image command and no migration for the site')
    check_build(where, runtime, deep(config, 'build', 'dockerfilePath'))
    workload = objects.get(('Deployment', 'web'))
    origins = None
    if expect(workload, where, 'has no Deployment web'):
        dep_where = 'Deployment/web'
        check_labels(dep_where, workload, 'web', 'site')
        check_pod(dep_where, workload)
        container = one_container(dep_where, workload)
        expect(container.get('image') == 'beirut-time/web:local', dep_where, 'image must be beirut-time/web:local')
        expect(not container.get('command') and not container.get('args'), dep_where, 'must run the image command')
        expect([p.get('containerPort') for p in container.get('ports') or []] == [SITE_PORT], dep_where,
               f'must listen on {SITE_PORT}')
        check_probes(dep_where, container, deploy.get('healthcheckPath'), deploy.get('healthcheckTimeout'),
                     SITE_PORT, deploy.get('healthcheckPath'))
        check_limits(dep_where, container, runtime)
        env = env_entries(dep_where, container)
        wanted = compose_env(runtime)
        expect(set(env) == set(wanted), dep_where, f'environment differs from Compose: missing '
               f'{sorted(set(wanted) - set(env))}, extra {sorted(set(env) - set(wanted))}')
        for key, value in sorted(wanted.items()):
            if key in env:
                expect(literal(env[key]) == value, dep_where, f'{key} is {literal(env[key])!r}, Compose has {value!r}')
        origins = literal(env.get('BT_PUBLIC_WEB_ORIGINS', {'valueFrom': {}}))
        expect(origins and all(f'{host}:{SITE_PORT}' in origins.split(',') for host in
                               ('http://localhost', 'http://127.0.0.1')), dep_where,
               'BT_PUBLIC_WEB_ORIGINS must list the published local origins')
    check_service(where, objects, 'web', 'site', SITE_PORT, node_port=NODE_PORT)
    return origins


# The whole kind cluster: one node, and one port published on the machine, the site on loopback.
KIND_CLUSTER = {
    'kind': 'Cluster',
    'apiVersion': 'kind.x-k8s.io/v1alpha4',
    'nodes': [{'role': 'control-plane', 'extraPortMappings': [
        {'containerPort': NODE_PORT, 'hostPort': SITE_PORT, 'listenAddress': '127.0.0.1', 'protocol': 'TCP'}]}],
}


def check_kind(cluster):
    expect(cluster == KIND_CLUSTER, 'kind.yaml', f'must be exactly one node publishing NodePort {NODE_PORT} on '
           f'127.0.0.1:{SITE_PORT} and nothing else, {json.dumps(KIND_CLUSTER)}; found {json.dumps(cluster)}')


def check_postgres(compose, objects, databases):
    where = 'postgres'
    runtime = compose.get('postgres')
    workload = objects.get(('Deployment', 'postgres'))
    if not (expect(runtime, where, 'is missing from Compose') and expect(workload, where, 'has no Deployment postgres')):
        return
    dep_where = 'Deployment/postgres'
    check_labels(dep_where, workload, 'postgres', 'database')
    check_pod(dep_where, workload, restricted=False)
    expect(deep(workload, 'spec', 'strategy', 'type') == 'Recreate', dep_where, 'needs the Recreate strategy')
    container = one_container(dep_where, workload)
    expect(container.get('image') == runtime.get('image'), dep_where, f'image must be {runtime.get("image")}, as in Compose')
    env = env_entries(dep_where, container)
    wanted = compose_env(runtime)
    expect(set(env) == {'POSTGRES_USER'} and literal(env['POSTGRES_USER']) == wanted.get('POSTGRES_USER'), dep_where,
           'must set only POSTGRES_USER directly, as in Compose')
    expect(container.get('envFrom') == [{'secretRef': {'name': PASSWORDS}}], dep_where,
           f'must read every password from the {PASSWORDS} Secret')
    generated = {'POSTGRES_PASSWORD'} | {f'{d.upper()}_{kind}_PASSWORD' for d in databases for kind in ('DB', 'OWNER')}
    expect(set(wanted) - {'POSTGRES_USER'} == generated, where,
           f'Compose passwords {sorted(set(wanted) - {"POSTGRES_USER"})} differ from those demo.sh generates')
    test = deep(runtime, 'healthcheck', 'test') or []
    if expect(test[:1] == ['CMD-SHELL'] and len(test) == 2, where, 'Compose health check must be one CMD-SHELL line'):
        expect(deep(container, 'readinessProbe', 'exec', 'command') == shlex.split(test[1]), dep_where,
               f'readiness probe must be the Compose health check {test[1]!r}')
    check_limits(dep_where, container, runtime)
    mounts = {m.get('mountPath'): m.get('name') for m in container.get('volumeMounts') or []}
    volumes = {v.get('name'): v for v in deep(workload, 'spec', 'template', 'spec', 'volumes') or []}
    targets = [v.get('target') if isinstance(v, dict) else str(v).split(':')[1] for v in runtime.get('volumes') or []]
    data = [t for t in targets if t == '/var/lib/postgresql/data']
    expect(data and 'emptyDir' in volumes.get(mounts.get(data[0]), {}), dep_where,
           'data must live in an emptyDir at the Compose data path, gone with the cluster')
    scripts = [t for t in targets if t.startswith('/docker-entrypoint-initdb.d/')]
    init = volumes.get(mounts.get('/docker-entrypoint-initdb.d'), {}).get('configMap') or {}
    expect(len(scripts) == 1 and init.get('name') == INIT and init.get('defaultMode') == 0o555
           and init.get('items') == [{'key': Path(scripts[0]).name, 'path': Path(scripts[0]).name}] if scripts else False,
           dep_where, f'must run infra/foundation/postgres-init.sh from the {INIT} ConfigMap as {scripts}')
    check_service(where, objects, 'postgres', 'database', 5432)


def check_kustomization(objects):
    text = (K8S / 'kustomization.yaml').read_text()
    listed = set(re.findall(r'^\s*-\s+(\S+\.yaml)\s*$', text, re.M))
    present = {p.relative_to(K8S).as_posix() for p in K8S.rglob('*.yaml')} - {'kustomization.yaml', 'kind.yaml'}
    expect(listed == present, 'kustomization.yaml', f'resources must list every manifest: missing '
           f'{sorted(present - listed)}, unknown {sorted(listed - present)}')
    for (kind, name), item in sorted(objects.items()):
        where = f'{kind}/{name}'
        expect(deep(item, 'metadata', 'labels', PART_OF) == NAMESPACE, where, f'needs label {PART_OF}={NAMESPACE}')
        if kind == 'Namespace':
            expect(name == NAMESPACE, where, f'the only namespace is {NAMESPACE}')
        else:
            expect(deep(item, 'metadata', 'namespace') == NAMESPACE, where, f'must live in namespace {NAMESPACE}')


def main(compose_path, rendered_path, kind_path):
    compose = json.loads(Path(compose_path).read_text()).get('services') or {}
    objects = index(json.loads(Path(rendered_path).read_text()))
    check_kind(json.loads(Path(kind_path).read_text()))
    railway = {p.stem: json.loads(p.read_text()) for p in sorted((ROOT / 'infra/railway').glob('*.json'))}
    services = sorted(name for name in railway if name != 'web')
    databases = init_databases()
    expect(databases, 'postgres-init.sh', 'no `for service in ...; do` database list found')
    expect('web' in railway, 'infra/railway', 'has no web.json')
    check_kustomization(objects)
    origins = check_web(railway, compose, objects)
    check_postgres(compose, objects, databases)
    used = [check_python_service(name, railway, compose, objects, databases, origins) for name in services]
    expect(sorted(filter(None, used)) == sorted(databases), 'postgres-init.sh',
           f'databases {sorted(databases)} must be exactly the services\' databases {sorted(filter(None, used))}')
    def named(wanted):
        return {name for kind, name in objects if kind == wanted}
    expect(named('Namespace') == {NAMESPACE}, 'manifests',
           f'Namespaces {sorted(named("Namespace"))} must be {NAMESPACE} only')
    expect(named('Deployment') == set(services) | {'web', 'postgres'}, 'manifests',
           f'Deployments {sorted(named("Deployment"))} must be the Railway services, web and postgres')
    expect(named('Job') == {f'{name}-migrate' for name in services}, 'manifests',
           f'Jobs {sorted(named("Job"))} must be one migration per service')
    expect(named('Service') == set(services) | {'web', 'postgres'}, 'manifests',
           f'Services {sorted(named("Service"))} must be the Railway services, web and postgres, and no other')
    kinds = {kind for kind, _ in objects}
    expect(kinds <= {'Namespace', 'Deployment', 'Job', 'Service'}, 'manifests',
           f'unexpected kinds {sorted(kinds - {"Namespace", "Deployment", "Job", "Service"})}')
    if problems:
        print(f'{len(problems)} problem(s) between infra/k8s and Railway or Compose:')
        for problem in problems:
            print(f'  - {problem}')
        return 1
    print(f'infra/k8s agrees with Railway and Compose: {len(services)} services with their migrations, '
          f'web on 127.0.0.1:{SITE_PORT} only, postgres with {len(databases)} databases.')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:]))
