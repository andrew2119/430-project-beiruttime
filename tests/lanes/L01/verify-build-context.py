"""Check an owned proof image for accidentally copied local signing/configuration files."""
import hashlib
from pathlib import Path
import re
import subprocess
import sys

checkout=hashlib.sha256(str(Path(__file__).resolve().parents[3]).encode()).hexdigest()[:8]
if len(sys.argv)!=2 or not re.fullmatch(r'beirut-time/(identity|eligibility):test-'+checkout+r'-[0-9]+',sys.argv[1]):
    raise SystemExit('Pass this checkout\'s Identity or Eligibility proof image tag')
probe='''from pathlib import Path
root=Path('/lane-tests/L01')
paths={str(path) for pattern in ['.env','.env.*','*.pem','*.key'] for path in root.rglob(pattern) if path.is_file()}
assert not paths, 'Local proof material copied into image: '+repr(sorted(paths))
print('No local configuration or signing material in proof image')
'''
subprocess.run(['docker','run','--rm','--read-only','--network','none','--entrypoint','python',sys.argv[1],'-c',probe],check=True)
