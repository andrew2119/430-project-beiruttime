"""Check the staged and committed lane diff without treating authorized untracked handoffs as edits."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
DIRECTORIES = (
    'services/auction/runtime/',
    'services/auction/modules/rules/',
    'services/auction/modules/bid-admission/',
    'services/communications/modules/bid-notices/',
    'web/app/(auction-management)/seller/auctions/',
    'web/features/auction-management/',
    'packages/contracts-auction/core/',
    'packages/contracts-comms/bid-notices/',
    'tests/lanes/L05/',
)
FILES = {'web/registrations/L05.ts', 'infra/compose/L05.yaml', 'contracts/registrations/L05.json'}


def changed(*arguments):
    output = subprocess.check_output(['git', 'diff', '--name-only', '-z', *arguments], cwd=ROOT)
    return [item.decode() for item in output.split(b'\0') if item]


def owned(path):
    return path in FILES or any(path.startswith(directory) for directory in DIRECTORIES)


committed = changed('origin/main...HEAD')
# Compare the staged tree to main, so a pending normal main merge does not misclassify its inherited files.
staged = changed('--cached', 'origin/main')
foreign = sorted({path for path in committed + staged if not owned(path)})
if foreign:
    raise SystemExit('Foreign paths in lane diff: ' + ', '.join(foreign))
print(f'Owned-path check passed: {len(committed)} committed paths, {len(staged)} staged paths.')
if not committed:
    print('No owned commit exists yet; this is not a publication-completion check.')
