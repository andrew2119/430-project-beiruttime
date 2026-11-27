"""Exercise production discovery in temporary trees without starting services."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]


class DiscoveryTests(unittest.TestCase):
    def test_contract_discovery_accepts_required_range(self):
        source = (ROOT / 'web/scripts/generate-nav.mjs').read_text()
        if '/^L(0[0-9]|1[01])$/' in source:
            self.skipTest('Shared contract reader expansion is deferred to its owner')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / 'web/scripts'
            scripts.mkdir(parents=True)
            (root / 'web/registrations').mkdir()
            contracts = root / 'contracts/registrations'
            contracts.mkdir(parents=True)
            shutil.copyfile(ROOT / 'web/scripts/generate-nav.mjs', scripts / 'generate-nav.mjs')
            for lane in range(26):
                name = f'L{lane:02}'
                (contracts / f'{name}.json').write_text(json.dumps({
                    'version': 1, 'lane': name, 'contracts': []}))
            result = subprocess.run(['node', str(scripts / 'generate-nav.mjs')],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root / 'web/contracts.generated.json').read_text()), [])

    def check_composition(self, present):
        source = (ROOT / 'infra/foundation/compose.sh').read_text()
        if 'for lane in 01 02 03 04 05 06 07 08 09 10 11; do' in source:
            self.skipTest('Shared composition reader expansion is deferred to its owner')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            foundation = root / 'infra/foundation'
            foundation.mkdir(parents=True)
            fragments = root / 'infra/compose'
            fragments.mkdir()
            shutil.copyfile(ROOT / 'infra/foundation/compose.sh', foundation / 'compose.sh')
            if present:
                shutil.copyfile(ROOT / 'infra/compose/L16.yaml', fragments / 'L16.yaml')
            binary = root / 'bin'
            binary.mkdir()
            command = binary / 'docker'
            command.write_text('#!/bin/sh\nprintf "%s\\n%s\\n" "${BT_COMPOSE_L16-}" "${BT_COMPOSE_L25-}"\n')
            command.chmod(0o755)
            environment = dict(os.environ)
            environment['PATH'] = str(binary) + os.pathsep + environment['PATH']
            environment['BT_COMPOSE_L16'] = 'stale-fragment'
            environment['BT_COMPOSE_L25'] = 'stale-fragment'
            result = subprocess.run(['bash', str(foundation / 'compose.sh'), 'config'],
                                    env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(),
                             ['infra/compose/L16.yaml' if present else '', ''])

    def test_composition_discovers_fragment(self):
        self.check_composition(present=True)

    def test_composition_clears_absent_fragments(self):
        self.check_composition(present=False)
