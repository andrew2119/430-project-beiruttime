"""Strict reading and private writing of the scripted review's files. Test only.

The scripted possession review (see ../walkthrough.py) passes its inputs through owner-only
files in the stage part's run folder. These checks refuse anything redirected, shared, changed
while read, oversized, or not strict JSON. Not physical inspection.
"""
from hashlib import sha256
import json
import math
import os
import re
import stat

PNG = b'\x89PNG\r\n\x1a\n'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def strict_json(raw):
    def unique(pairs):
        result = {}
        for k,v in pairs:
            require(k not in result, f'duplicate JSON key: {k}')
            result[k] = v
        return result
    def invalid(value):
        raise ValueError(f'nonfinite JSON number: {value}')
    def number(value):
        result=float(value)
        require(math.isfinite(result),f'nonfinite JSON number: {value[:32]}')
        require(result!=0 or not re.search('[1-9]',re.split('[eE]',value,1)[0]),'JSON number underflows its representation')
        return result
    def integer(value):
        require(len(value.lstrip('-'))<=20,'oversized JSON integer')
        return int(value)
    if isinstance(raw,(bytes,bytearray)): raw=raw.decode('utf-8')
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid,parse_float=number,parse_int=integer)


def evidence_bytes(path, limit, *, private=False, may_wait=False):
    require(path.parent.resolve()==path.parent,f'missing or redirected evidence: {path.name}')
    try:
        fd=os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:
        if may_wait: raise
        raise ValueError(f'missing or redirected evidence: {path.name}') from None
    except OSError as error:
        raise ValueError(f'missing or redirected evidence: {path.name}') from error
    with os.fdopen(fd,'rb') as stream:
        before=os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode),f'missing or redirected evidence: {path.name}')
        if private:
            require(stat.S_IMODE(before.st_mode)==0o600 and before.st_uid==os.geteuid() and before.st_nlink==1,
                    f'nonprivate evidence: {path.name}')
        require(0<before.st_size<=limit,f'empty or oversized evidence: {path.name}')
        raw=stream.read(limit+1); after=os.fstat(stream.fileno())
        require(len(raw)==before.st_size==after.st_size and (before.st_ctime_ns,before.st_mtime_ns)==(after.st_ctime_ns,after.st_mtime_ns),
                f'evidence changed while reading: {path.name}')
    return raw


def file_bytes(path, limit=32_000_000):
    return evidence_bytes(path,limit)


def private_write(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)


def private_bytes(path, limit, *, may_wait=False):
    return evidence_bytes(path,limit,private=True,may_wait=may_wait)


def digest(raw):
    return sha256(raw).hexdigest()
