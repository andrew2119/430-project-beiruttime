"""Prove nested local environment files never enter Docker build contexts or Git."""
import hashlib
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]


def main():
    tag = 'beirut-time/foundation-context-proof:' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:8] + '-' + str(os.getpid())
    with TemporaryDirectory(prefix='context-proof-', dir=ROOT / 'tests/foundation') as directory:
        probe = Path(directory) / 'nested'
        probe.mkdir()
        for name in ['.env', '.env.local', '.env.production', '.env.example']:
            (probe / name).write_text('SYNTHETIC_CONTEXT_PROOF=not-a-credential\n')
        relative = probe.relative_to(ROOT).as_posix()
        dockerfile = f'''FROM node:22.21.1-alpine
COPY . /context
RUN test ! -e /context/{relative}/.env \\
 && test ! -e /context/{relative}/.env.local \\
 && test ! -e /context/{relative}/.env.production \\
 && test -f /context/{relative}/.env.example
'''
        try:
            subprocess.run(['docker', 'build', '-f', '-', '-t', tag, '.'], cwd=ROOT, input=dockerfile, text=True, check=True)
            for name in ['.env', '.env.local', '.env.production']:
                result = subprocess.run(['git', 'check-ignore', '--no-index', '-q', relative + '/' + name], cwd=ROOT)
                assert result.returncode == 0, f'Git does not ignore nested {name}'
            example = subprocess.run(['git', 'check-ignore', '--no-index', '-q', relative + '/.env.example'], cwd=ROOT)
            assert example.returncode == 1, 'Safe environment examples must remain addable'
            print('Nested environment files excluded from Docker context and Git; examples remain available.')
        finally:
            subprocess.run(['docker', 'image', 'rm', tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == '__main__':
    main()
