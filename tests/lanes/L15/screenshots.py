#!/usr/bin/env python3
"""Headless Chrome screenshots using the AXI-owned profile after AXI is stopped.
Select the theme through the real shell control before stopping AXI; this script
never injects auth, UI results, response data, theme CSS, or DOM fixtures.
Run only inside the same bt-heavy.sh proof reservation.
"""
import argparse
import json
from pathlib import Path
import subprocess
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'tests/lanes/L15/.artifacts'
parser = argparse.ArgumentParser()
parser.add_argument('role', choices=['buyer', 'brand'])
parser.add_argument('theme', choices=['light', 'dark'])
args = parser.parse_args()
public = json.loads((OUT / 'proof-public.json').read_text())
paths = {'configuration': f'customize?configuration={public["configuration_id"]}',
         'request': f'custom-requests?draft={public["draft_id"]}'} if args.role == 'buyer' else {
         'brand': f'business/customizations?organization_id={public["brand_id"]}',
         'listing': f'seller/listings/{public["listing_id"]}?organization_id={public["brand_id"]}'}
chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
for width in [1280, 390]:
    for locale in ['en', 'ar']:
        for name, path in paths.items():
            if (OUT/'proof.stop').exists():
                raise SystemExit('Own visual proof stop requested')
            destination = OUT / f'{name}-{locale}-{width}-{args.theme}.png'
            capture = destination.with_name(destination.stem+'.capture.png')
            # A healthy loopback page before and after capture prevents a proof
            # deadline from turning a browser error page into visual evidence.
            with urlopen('http://127.0.0.1:3315/en/account',timeout=10) as health:
                if health.status != 200:
                    raise SystemExit('Own web proof is not ready')
            command = [chrome, '--headless=new', '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
                       '--disable-background-networking', '--disable-extensions',
                       '--use-mock-keychain', '--password-store=basic',
                       '--disable-gpu',
                       f'--user-data-dir={OUT / "profile-light"}',
                       f'--window-size={width},{2000 if width == 390 else 1000}', '--virtual-time-budget=4000',
                       '--timeout=12000', f'--screenshot={capture}',
                       f'http://127.0.0.1:3315/{locale}/{path}']
            if args.theme == 'dark':
                command.insert(1, '--force-dark-mode')
            with (OUT / 'screenshots.log').open('a') as log:
                subprocess.run(command, stdout=log, stderr=log, check=True, timeout=30)
            with urlopen('http://127.0.0.1:3315/en/account',timeout=10) as health:
                if health.status != 200:
                    raise SystemExit('Own web proof stopped during capture')
            if not capture.exists() or capture.stat().st_size < 10000:
                raise SystemExit(f'Screenshot missing: {capture}')
            capture.replace(destination)
            print(destination.name, flush=True)
