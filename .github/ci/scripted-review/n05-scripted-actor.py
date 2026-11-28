"""Supply the authorized hosted test inputs, not service requests or human evidence."""
import base64
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from time import monotonic

sys.path.insert(0,str(Path(__file__).resolve().parent))
from http_evidence import photo_observation
from listing_coordinator import INPUTS,INPUT_LIMIT,REVIEW_SECONDS,absent,private_input,safe_folder
from listing_evidence import encode
from proof_types import digest,file_bytes,private_write,require,strict_json

REFS=('DEMO-WATCH-01','DEMO-WATCH-03','DEMO-WATCH-05')
PHOTO_PATH='web/public/icons/bt-192.png'
PHOTO_SHA='3b8992af9b0e010078fb0f0d44ab07e7414d9362b358e6bbdfa25da3a979c021'
VERDICT={'verdict':'approved','reason':'The assigned reviewer inspected the test image for this hosted check.'}


def supply(run,end):
    require(math.isfinite(end) and 0<end-monotonic()<=REVIEW_SECONDS,'invalid shared review deadline')
    safe_folder(run)
    folder=run/INPUTS; safe_folder(folder)
    raw=file_bytes(run/'source'/PHOTO_PATH,INPUT_LIMIT)
    require(digest(raw)==PHOTO_SHA,'wrong frozen test image')
    photo_observation(raw)
    require(len(encode(VERDICT))<=8192 and 5<=len(VERDICT['reason'])<=500,'invalid test verdict')
    seen=set()
    for ref in REFS:
        for kind,payload in (('photo',{'pngBase64':base64.b64encode(raw).decode()}),('verdict',VERDICT)):
            ready=folder/f'{ref}.{kind}.ready.json'
            target=folder/f'{ref}.{kind}.input.json'
            binding=strict_json(private_input(ready,4096,end))
            require(type(binding) is dict and set(binding)=={'token','afterReceipt'} and
                    all(type(v) is str and re.fullmatch('[0-9a-f]{64}',v) for v in binding.values()) and
                    binding['token'] not in seen, 'invalid or repeated listing readiness')
            seen.add(binding['token'])
            with tempfile.TemporaryDirectory(prefix='actor-',dir=folder) as temp:
                staged=Path(temp)/'input'
                private_write(staged,encode(dict(binding,payload=payload)))
                require(monotonic()<end and absent(target),'listing input is late or already exists')
                os.replace(staged,target)


if __name__=='__main__':
    try:
        supply(Path(sys.argv[1]),float(sys.argv[2]))
    except (OSError,ValueError,TypeError,KeyError,IndexError):
        sys.exit('N05 hosted actor refused or reached the shared deadline')
