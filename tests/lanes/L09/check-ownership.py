"""Check committed branch scope before publishing; copied dependencies are excluded."""
import argparse
from pathlib import PurePosixPath
import re
import subprocess

roots=(
 'services/trust/runtime','services/trust/modules/moderation',
 'services/communications/modules/operator-workspace','services/service-operations/modules/intake',
 'web/app/(moderation)/operations/moderation','web/app/(operator)/operations/dashboard',
 'web/app/(intake)/business-intake','web/features/moderation',
 'packages/contracts-trust/moderation','packages/contracts-service/intake','tests/lanes/L09'
)
files={'web/registrations/L09.ts','infra/compose/L09.yaml','contracts/registrations/L09.json'}
parser=argparse.ArgumentParser()
parser.add_argument('--pr-title',help='Optionally validate the real feature reference in the review title')
args=parser.parse_args()
branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip()
if branch!='bt/bt-l09':
    raise SystemExit('Refused branch name: '+branch)
if args.pr_title is not None and not re.match(r'^BT-[0-9]+\s+\S',args.pr_title):
    raise SystemExit('The review title must start with the real feature reference')
paths=subprocess.check_output(['git','diff','--name-only','origin/main...HEAD'],text=True).splitlines()
unknown=[path for path in paths if path not in files and not any(PurePosixPath(path).is_relative_to(root) for root in roots)]
if unknown:
    raise SystemExit('Unowned committed paths: '+', '.join(unknown))
if any('__fixture_portal' in path or '/fixture-login/' in path for path in paths if path.startswith('web/')):
    raise SystemExit('A temporary browser fixture was committed into the product tree')
if 'web/registrations/L09.ts' in paths:
    registration=subprocess.check_output(['git','show','HEAD:web/registrations/L09.ts'],text=True)
    if 'L09_CONTRACT_FIXTURE_ONLY' in registration:
        raise SystemExit('A temporary authentication fixture registration was committed')
if not paths:
    raise SystemExit('No committed lane changes to publish')
print(f'{branch}: all {len(paths)} committed paths belong to this lane')
