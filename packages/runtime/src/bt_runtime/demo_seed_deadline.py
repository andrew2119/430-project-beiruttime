"""Hard deadline for the optional deploy demo seed: the seed runs in a separately supervised child process.

The pre-deploy step (`python -m service_app.migrate`) calls supervise() only after its migrations have
committed. Everything the seed does runs in the child: module discovery and import, the seed itself and every
one of its log lines. The parent only starts the child, copies its lines to the deploy log and waits at most
HARD_SECONDS; then it kills the child's whole process group, reaps it for at most REAP_SECONDS and copies its
last lines for at most RELAY_SECONDS more. It never raises and ignores the child's exit status, so no seed or
logging failure, and no stall, can change the migration step's result or keep the parent waiting more than
BOUND_SECONDS after the child has started. That bounds only this wait: not starting the child, not the migration
before it, and not when the server finishes rolling back a killed seed's open transaction. A step the child had
already committed stays, so a stopped seed may be partial, and the parent's last line says so.
A closed, broken or stalled deploy log only loses seed lines; the parent never writes to it on its own thread.
Standard library only, so importing this module cannot fail or stall on anything the seed itself uses.
"""
import contextlib
import os
import signal
import subprocess
import sys
import threading

SWITCH = 'BT_DEMO_SEED'
CHILD = 'bt_runtime.demo_seed_deadline'
HARD_SECONDS = 40
REAP_SECONDS = 2
RELAY_SECONDS = 1
BOUND_SECONDS = HARD_SECONDS + REAP_SECONDS + RELAY_SECONDS
STOPPED = b'DEMO SEED deadline: stopped at the hard limit; the seed may be partial; the deploy goes on\n'


def log_target() -> int | None:
    """The deploy log's descriptor, or None when it is closed, so the child's lines go nowhere."""
    try:
        os.fstat(2)
    except OSError:
        return None
    return 2


def write(target: int, data: bytes) -> None:
    while data:
        data = data[os.write(target, data):]


def relay(source: int, target: int | None, after: list[bytes]) -> None:
    """Copy the child's output to the deploy log until it ends, then any parent note; never raises."""
    try:
        while chunk := os.read(source, 65536):
            if target is not None:
                try:
                    write(target, chunk)
                except OSError:
                    target = None
        for line in after:
            if target is not None:
                write(target, line)
    except OSError:
        pass


def supervise(environ=None) -> None:
    """Run the seed in a child process under the hard deadline; returns at once while the switch is unset."""
    environ = os.environ if environ is None else environ
    if not environ.get(SWITCH):
        return
    try:
        target = log_target()
        child = subprocess.Popen(
            [sys.executable, '-m', CHILD], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL if target is None else subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True, env=None if environ is os.environ else dict(environ))
    except Exception:
        return
    after: list[bytes] = []
    reader = None
    try:
        if child.stdout is not None:
            reader = threading.Thread(target=relay, args=(child.stdout.fileno(), target, after),
                                      name='demo-seed-log', daemon=True)
            reader.start()
        try:
            child.wait(timeout=HARD_SECONDS)
        except subprocess.TimeoutExpired:
            after.append(STOPPED)
            with contextlib.suppress(OSError):
                os.killpg(child.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=REAP_SECONDS)
        if reader is not None:
            reader.join(RELAY_SECONDS)
    except Exception:
        with contextlib.suppress(Exception):
            os.killpg(child.pid, signal.SIGKILL)


def main() -> None:
    """The child's entry: the seed proper on its own loop, within its own cooperative budget."""
    try:
        from bt_runtime import demo_seed
        from bt_runtime.app.settings import Settings
        settings = Settings()
    except Exception as error:
        with contextlib.suppress(Exception):
            write(2, f'DEMO SEED seed: failed: {type(error).__name__}\n'.encode())
        return
    demo_seed.run(settings)


if __name__ == '__main__':
    main()
    with contextlib.suppress(Exception):
        sys.stdout.flush()
        sys.stderr.flush()
    # Threads the seed abandoned at its budget never hold the child open, and no exit hook runs.
    os._exit(0)
