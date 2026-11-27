"""Run the native stack's own start, status, smoke and stop commands (N01) on this runner.

Usage: python .github/ci/n01.py <report.json>

The job needs the PostgreSQL 17 server binaries in /usr/lib/postgresql/17/bin, port 54329 free
(the stack starts its own private cluster, so this job has no database service), a production
web build in web/.next, and passwordless sudo, used once to install the root-owned admission
file that scripts/native-stack.py checks before every connected command.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_ci import MANIFEST, ROOT, common_environment, write_report  # noqa: E402
import checks_http  # noqa: E402

PYTHON = sys.executable
STACK = ROOT / 'scripts/native-stack.py'
ADMISSION = Path('/opt/domain-contracts/native-admission-v1.json')
POSTGRES_BIN = '/usr/lib/postgresql/17/bin'
PORTS = [54329, 3000, *(s['port'] for s in MANIFEST['services'] if s['name'] != 'web')]
SHARED_NAMES = ('NEXT_TELEMETRY_DISABLED', 'NODE_OPTIONS', 'UV_THREADPOOL_SIZE', 'OMP_NUM_THREADS',
                'OPENBLAS_NUM_THREADS', 'BT_AUTH_ISSUER', 'BT_AUTH_AUDIENCE', 'BT_WEB_ORIGIN',
                'BT_ALLOWED_WEB_ORIGINS', 'BT_PUBLIC_WEB_ORIGINS', 'BT_TRUST_FORWARDED_ORIGIN', 'BT_LOCAL_HTTP',
                'BT_CONTACT_SIMULATOR')
# Every domain verifies user and service tokens; only the actual signers get private keys.
SIGNERS = {
    'BT_AUTH_PRIVATE_KEY': ('identity',),
    'BT_EVENT_PRIVATE_KEY': ('identity', 'eligibility'),
    'BT_SERVICE_AUTH_PRIVATE_KEY': ('catalog', 'auction', 'pricing', 'orders', 'communications', 'service-operations'),
    'BT_PRICING_EVENT_PRIVATE_KEY': ('pricing',),
    'BT_TRUST_SERVICE_PRIVATE_KEY': ('trust',),
    'BT_INTAKE_SERVICE_PRIVATE_KEY': ('service-operations',),
}
HOLDER = r'''
import fcntl, os, pathlib, signal, stat, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
st = os.fstat(fd)
if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1:
    raise SystemExit('lock must be a plain single-name file owned by this user')
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
pathlib.Path(sys.argv[2]).write_text(str(os.getpid()))
while True:
    time.sleep(60)
'''


def ticks(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]


def stack_command(*args, timeout=60):
    return subprocess.run([PYTHON, '-I', str(STACK), *args], capture_output=True, text=True, timeout=timeout)


class Stage:
    def __init__(self):
        self.work = Path(tempfile.mkdtemp(prefix='n01-', dir=os.environ.get('RUNNER_TEMP')))
        self.run = self.work / 's'
        self.cap = self.work / 'capability.json'
        self.lock = self.work / 'native-batch.lock'
        self.batch = f"n01-{os.environ.get('GITHUB_RUN_ID', 'local')}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
        self.holder = self.start = None
        self.stopped = False
        self.passed, self.problems, self.timings = [], [], {}

    def step(self, name, action):
        print(f'::group::{name}', flush=True)
        began = time.monotonic()
        try:
            action()
            ok = True
        except Exception as error:  # every failure is reported by name
            ok = False
            self.problems.append(f'{name}: {error}')
        print('::endgroup::', flush=True)
        print(f"{'PASS' if ok else 'FAIL'} {name} ({time.monotonic() - began:.1f}s)", flush=True)
        if ok:
            self.passed.append(name)
        return ok

    def hold_lock(self):
        pid_file = self.work / 'holder.pid'
        self.holder = subprocess.Popen([PYTHON, '-I', '-c', HOLDER, str(self.lock), str(pid_file)])
        deadline = time.monotonic() + 5
        while not pid_file.is_file() and self.holder.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if not pid_file.is_file() or int(pid_file.read_text()) != self.holder.pid:
            raise RuntimeError('lock holder did not become ready')

    def admit(self):
        st = self.lock.stat()
        marker = dict(schema_version=1, state='closed', batch_id=self.batch, expires_at=time.time() + 1800,
                      pid=self.holder.pid, start_ticks=ticks(self.holder.pid), lock=str(self.lock),
                      lock_identity=f'{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}')
        draft = self.work / 'admission.json'
        draft.write_text(json.dumps(marker))
        subprocess.run(['sudo', '-n', 'install', '-D', '-m', '0644', '-o', 'root', '-g', 'root', str(draft),
                        str(ADMISSION)], check=True, timeout=15)

    def capability(self):
        keys = self.work / 'keys'
        keys.mkdir(mode=0o700)
        pem = {}
        for name in ('user', 'event'):
            subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                            '-out', str(keys / f'{name}.pem')], check=True, capture_output=True, timeout=30)
            subprocess.run(['openssl', 'pkey', '-in', str(keys / f'{name}.pem'), '-pubout', '-out',
                            str(keys / f'{name}.pub')], check=True, capture_output=True, timeout=10)
            pem[name] = ((keys / f'{name}.pem').read_text(), (keys / f'{name}.pub').read_text())
        demo = self.work / 'demo'
        demo.mkdir()
        for name in ('images-manifest.json', 'listings.json'):
            shutil.copy2(ROOT / 'demo' / name, demo / name)
        shutil.copytree(ROOT / 'web/public/demo/watches', demo / 'watches')
        values = common_environment()
        shared = {name: values[name] for name in SHARED_NAMES}
        shared.update(BT_ENVIRONMENT='demo', BT_REQUEST_BODY_LIMIT='8500000',
                      BT_DEMO_MANIFEST=str(ROOT / 'demo/images-manifest.json'), BT_DEMO_ROOT=str(demo),
                      AUCTION_HIGH_VALUE_USD_MINOR='1000000', AUCTION_HIGH_VALUE_LBP_MINOR='89500000000',
                      CATALOG_MEDIA_API_URL='http://127.0.0.1:8102')
        scoped = {}
        for service in MANIFEST['services']:
            name = service['name']
            if name == 'web':
                scoped[name] = {}
                continue
            key = name.upper().replace('-', '_')
            for alias in (key + '_URL', key + '_API_URL', 'BT_' + key + '_URL', 'BT_' + key + '_API_URL'):
                shared[alias] = f"http://127.0.0.1:{service['port']}"
            env = dict(BT_AUTH_PUBLIC_KEY=pem['user'][1], BT_SERVICE_AUTH_PUBLIC_KEY=pem['event'][1])
            for variable, signers in SIGNERS.items():
                if name in signers:
                    env[variable] = pem['user'][0] if variable == 'BT_AUTH_PRIVATE_KEY' else pem['event'][0]
            scoped[name] = env
        cap = dict(schema_version=1, batch_id=self.batch, python=PYTHON, postgres_bin=POSTGRES_BIN,
                   environment=shared, service_environment=scoped)
        fd = os.open(self.cap, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(cap, out)
        # The stack runs every process with PATH limited to the Python, PostgreSQL and system folders.
        node = Path(PYTHON).parent / 'node'
        if not node.exists():
            node.symlink_to(shutil.which('node'))

    def start_to_ready(self):
        began = time.monotonic()
        log = (self.work / 'start.log').open('w')
        self.start = subprocess.Popen([PYTHON, '-I', str(STACK), 'start', '--run-dir', str(self.run),
                                       '--capability', str(self.cap)], stdout=log, stderr=subprocess.STDOUT)
        while time.monotonic() < began + 240:
            # status refuses while start holds its exclusive control lock during startup.
            result = stack_command('status', '--run-dir', str(self.run), timeout=10)
            if result.returncode == 0:
                state = json.loads(result.stdout)['state']
                if state == 'ready':
                    self.timings['start_to_ready'] = round(time.monotonic() - began, 1)
                    return
                if state in ('failed', 'stopped', 'cleanup-incomplete'):
                    raise RuntimeError(f'status reported {state}')
            if self.start.poll() is not None:
                raise RuntimeError(f'start exited with {self.start.returncode} before ready')
            time.sleep(0.5)
        raise TimeoutError('not ready within 240 seconds')

    def smoke(self):
        # The supervisor holds a shared control lock for a moment between its checks, and smoke
        # takes that lock without waiting; retry only that refusal, for at most five seconds.
        began = time.monotonic()
        spec = importlib.util.spec_from_file_location('native_stack', STACK)
        stack = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stack)
        argv = sys.argv
        sys.argv = [str(STACK), 'smoke', '--run-dir', str(self.run), '--capability', str(self.cap)]
        try:
            while True:
                try:
                    stack.main()
                    break
                except BlockingIOError as error:
                    frame = error.__traceback__
                    while frame.tb_next is not None:
                        frame = frame.tb_next
                    if frame.tb_frame.f_code is not stack.main.__code__ or time.monotonic() > began + 5:
                        raise
                    time.sleep(0.1)
        finally:
            sys.argv = argv
        self.timings['smoke'] = round(time.monotonic() - began, 1)

    def shutdown(self):
        if self.start.poll() is None:
            self.start.send_signal(signal.SIGTERM)
        code = self.start.wait(timeout=60)
        # start turns SIGTERM into an interrupt, cleans up and exits by that interrupt.
        if code not in (0, -signal.SIGINT, -signal.SIGTERM, 130, 143):
            raise RuntimeError(f'start exited with {code} after SIGTERM')
        ledger = json.loads((self.run / 'ledger.json').read_text())
        if ledger.get('cleanup_complete') is not True or ledger['state'] not in ('stopped', 'failed'):
            raise RuntimeError(f"ledger after shutdown: state {ledger['state']}")

    def stop(self):
        result = stack_command('stop', '--run-dir', str(self.run), timeout=180)
        if result.returncode != 0:
            raise RuntimeError(f'stop exited {result.returncode}: {result.stderr.strip()[-300:]}')
        self.stopped = True

    def stopped_status(self):
        result = stack_command('status', '--run-dir', str(self.run), timeout=10)
        status = json.loads(result.stdout)
        ledger = json.loads((self.run / 'ledger.json').read_text())
        if not (ledger['state'] == status['state'] == 'stopped' and ledger['cleanup_complete'] is True):
            raise RuntimeError(f"status {status['state']}, ledger {ledger['state']}")
        if any(entry['owned'] for entry in status['processes']):
            raise RuntimeError('an owned session survived')

    def ports_free(self):
        busy = []
        for port in PORTS:
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(('127.0.0.1', port))
                except OSError:
                    busy.append(port)
        if busy:
            raise RuntimeError(f'ports still bound: {busy}')

    def release(self):
        self.holder.send_signal(signal.SIGTERM)
        self.holder.wait(timeout=10)
        self.holder = None
        with self.lock.open('r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def cleanup(self):
        """On any failure, let start finish its own cleanup, record the stop, and end the holder."""
        if self.start is not None and not self.stopped:
            if self.start.poll() is None:
                self.start.send_signal(signal.SIGTERM)
                try:
                    self.start.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    self.problems.append('cleanup: start did not finish its own cleanup')
            if (self.run / 'ledger.json').is_file() and self.start.poll() is not None:
                stack_command('stop', '--run-dir', str(self.run), timeout=180)
        if self.holder is not None:
            self.holder.send_signal(signal.SIGTERM)
            self.holder.wait(timeout=10)

    def diagnostics(self):
        # These are the stack's own redacted logs, never the capability or the keys.
        for log in [self.work / 'start.log', *sorted(self.run.glob('*.log'))]:
            if log.is_file():
                print(f'::group::{log.name} (last 30 lines)')
                print('\n'.join(log.read_text(errors='replace').splitlines()[-30:]))
                print('::endgroup::')


def main(report):
    stage = Stage()
    try:
        for name, action in (('lock holder', stage.hold_lock), ('root-owned admission', stage.admit),
                             ('disposable keys and capability', stage.capability),
                             ('start to ready', stage.start_to_ready), ('smoke', stage.smoke),
                             ('service identities', lambda: checks_http.ready(10)),
                             ('supervisor shutdown', stage.shutdown), ('stop', stage.stop),
                             ('stopped status', stage.stopped_status), ('ports free', stage.ports_free),
                             ('lock released', stage.release)):
            if not stage.step(name, action):
                break
    finally:
        stage.cleanup()
    if stage.problems:
        stage.diagnostics()
    return write_report(report, 'n01', not stage.problems, stage.problems, steps=stage.passed, seconds=stage.timings)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
