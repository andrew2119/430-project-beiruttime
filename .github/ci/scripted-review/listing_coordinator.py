"""The file protocol between the walkthrough driver and the scripted review actor. Test only.

For each review step the driver releases a one-use ready file in an owner-only folder of the
run; the actor (n05-scripted-actor.py, started by hosted_actor) answers it with exactly one
input file, which the driver reads once and deletes. Both sides share one deadline.
The inputs are a frozen test icon and a fixed approved verdict: not physical inspection.
"""
from contextlib import contextmanager
from pathlib import Path
import os
from secrets import token_hex
import subprocess
import sys
import tempfile
from time import monotonic, sleep

import listing_evidence as le
from proof_types import digest, private_bytes, private_write, require, strict_json

INPUTS = 'n05-review-inputs'
PENDING = {'category':'publication_review_pending','http_status':503,'upstream':'identity'}
INPUT_LIMIT = 750*1024
PHOTO_ENVELOPE_LIMIT = 4*((INPUT_LIMIT+2)//3)+8192
VERDICT_ENVELOPE_LIMIT = 9216
REVIEW_SECONDS = 300


def absent(path):
    return not os.path.lexists(path)


def safe_folder(path):
    require(path.resolve()==path and path.is_dir() and path.stat().st_mode&0o077==0 and path.stat().st_uid==os.geteuid(),
            'listing coordination directory must be owner-only')


def private_input(path, limit, end):
    # Open and read the same descriptor. There is no existence check followed by a reopen.
    while monotonic()<end:
        try: return private_bytes(path,limit,may_wait=True)
        except FileNotFoundError: sleep(min(.25,max(0,end-monotonic())))
    raise ValueError('listing review input did not arrive before the shared deadline')


def await_input(folder,ref,kind,after,end,limit):
    """Release one scripted-actor input for ``after`` and consume it once (shared file protocol)."""
    require(monotonic()<end,'listing input readiness deadline elapsed')
    binding=dict(token=token_hex(32),afterReceipt=digest(le.encode(after)))
    ready=folder/f'{ref}.{kind}.ready.json'; target=folder/f'{ref}.{kind}.input.json'
    with tempfile.TemporaryDirectory(prefix='release-',dir=folder) as scratch:
        file=Path(scratch)/'ready'; private_write(file,le.encode(binding)); os.replace(file,ready)
    try:
        envelope=strict_json(private_input(target,limit,end))
        require(set(envelope)==set(binding)|{'payload'} and {k:envelope[k] for k in binding}==binding,
                'listing input lacks its current one-use action token and receipt')
        require(monotonic()<end,'listing review deadline elapsed before consuming input')
        return envelope['payload']
    finally:
        ready.unlink(missing_ok=True); target.unlink(missing_ok=True)


@contextmanager
def hosted_actor(run,end):
    script=Path(__file__).resolve().with_name('n05-scripted-actor.py')
    with subprocess.Popen([sys.executable,'-IB',str(script),str(run),repr(end)],stdin=subprocess.DEVNULL) as proc:
        try:
            yield
            require(proc.wait(timeout=max(0,end-monotonic()))==0,'N05 hosted actor did not complete')
        finally:
            if proc.poll() is None: proc.kill()
