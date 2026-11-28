"""R0 discovery is additive: two new lanes coexist, absent fragments stay absent."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = next((p for p in Path(__file__).resolve().parents if (p/'compose.yaml').is_file()), Path('/repository-not-mounted'))
sys.path.insert(0, str(ROOT/'packages/runtime/src'))
from bt_runtime.modules import discover as modules
if ROOT.exists():
    spec = importlib.util.spec_from_file_location('contracts', ROOT/'infra/foundation/discover-contracts.py')
    contracts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contracts)


@unittest.skipUnless(ROOT.exists(), 'Source-tree discovery proof runs outside the service image')
class ExtensionTests(unittest.TestCase):
    def test_two_modules_and_lane_migrations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for lane in ('L12', 'L25'):
                module = root/lane
                module.mkdir()
                name = lane+'_0001_proof.sql'
                (module/name).write_text('SELECT 1;')
                (module/'module.json').write_text(json.dumps({'version':1,'id':lane+'.proof','migrations':[name]}))
            self.assertEqual([m.id for m in modules(root)], ['L12.proof','L25.proof'])
            (root/'L25/module.json').write_text(json.dumps({'version':1,'id':'L26.proof'}))
            with self.assertRaises(ValueError): modules(root)

    def test_contracts_and_escapes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'contracts/registrations').mkdir(parents=True)
            for lane in ('L12','L25'):
                path = 'packages/contracts-proof/'+lane
                (root/path).mkdir(parents=True)
                (root/f'contracts/registrations/{lane}.json').write_text(json.dumps({'version':1,'lane':lane,'contracts':[{'namespace':lane.lower()+'.proof.v1','path':path}]}))
            self.assertEqual([c['lane'] for c in contracts.discover(root)], ['L12','L25'])
            file = root/'contracts/registrations/L25.json'
            data = json.loads(file.read_text())
            data['contracts'][0]['path'] = '../escape'
            file.write_text(json.dumps(data))
            with self.assertRaises(ValueError): contracts.discover(root)
            data['lane'] = 'L26'
            file.unlink()
            (file.parent/'L26.json').write_text(json.dumps(data))
            with self.assertRaises(ValueError): contracts.discover(root)

    def test_compose_discovery_with_absent_fragments(self):
        # A local miniature tree keeps other lanes' real fragments read-only.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'infra/foundation').mkdir(parents=True)
            (root/'infra/compose').mkdir()
            script = root/'infra/foundation/compose.sh'
            script.write_text((ROOT/'infra/foundation/compose.sh').read_text())
            script.chmod(0o755)
            bin = root/'bin'
            bin.mkdir()
            docker = bin/'docker'
            docker.write_text('#!/bin/sh\nprintenv | sort\n')
            docker.chmod(0o755)
            for lane in ('L12','L25'): (root/f'infra/compose/{lane}.yaml').write_text('services: {}')
            output = subprocess.check_output([str(script),'config'], env={**os.environ,'PATH':str(bin)+':'+os.environ['PATH'],'BT_COMPOSE_L13':'untrusted'}, text=True)
            self.assertIn('BT_COMPOSE_L12=infra/compose/L12.yaml',output)
            self.assertIn('BT_COMPOSE_L25=infra/compose/L25.yaml',output)
            self.assertNotIn('BT_COMPOSE_L13=',output)
            compose = (ROOT/'compose.yaml').read_text()
            self.assertEqual(compose.count('\ninclude:'),1)
            for lane in ('L12','L25'): self.assertIn('BT_COMPOSE_'+lane,compose)


if __name__ == '__main__': unittest.main()
