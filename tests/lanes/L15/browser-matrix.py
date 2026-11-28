#!/usr/bin/env python3
"""Interaction checks through our own chrome-devtools-axi session (never mocks)."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'tests/lanes/L15/.artifacts'
parser = argparse.ArgumentParser()
parser.add_argument('role', choices=['buyer', 'brand'])
args = parser.parse_args()
public = json.loads((OUT / 'proof-public.json').read_text())
env = dict(os.environ, CHROME_DEVTOOLS_AXI_SESSION='bt-s2-l15',
           CHROME_DEVTOOLS_AXI_AUTO_CONNECT='0',
           CHROME_DEVTOOLS_AXI_USER_DATA_DIR=str(OUT / 'profile-light'))
env.pop('CHROME_DEVTOOLS_AXI_BROWSER_URL', None)

def browser(*command):
    return subprocess.check_output(['chrome-devtools-axi', *command], env=env, text=True)

paths = [f'customize?configuration={public["configuration_id"]}',
         f'custom-requests?draft={public["draft_id"]}'] if args.role == 'buyer' else [
         f'business/customizations?organization_id={public["brand_id"]}',
         f'seller/listings/{public["listing_id"]}?organization_id={public["brand_id"]}']
records = []
for width in [1280, 390]:
    viewport=f'{width}x844x' + ('3,mobile,touch' if width == 390 else '1')
    for locale in ['en', 'ar']:
        for theme in ['light', 'dark']:
            for path in paths:
                browser('open', f'http://127.0.0.1:3315/{locale}/{path}')
                browser('emulate', '--viewport', viewport, '--color-scheme', theme)
                time.sleep(0.8)
                browser('eval', f'''() => {{ const desired={json.dumps(theme)};
                  if(document.documentElement.dataset.theme!==desired) {{
                    const button=[...document.querySelectorAll('button')].find(b=> /theme|الوضع|المظهر/.test(b.getAttribute('aria-label')||''));
                    if(button)button.click();
                  }} return document.documentElement.dataset.theme; }}''')
                time.sleep(0.2)
                result = browser('eval', f'''() => {{const root=document.documentElement, main=document.querySelector('main');
                  const v={{width:innerWidth,scroll:root.scrollWidth,locale:root.lang,dir:root.dir,theme:root.dataset.theme,
                    heading:main?.querySelector('h1')?.textContent,privateStorage:Object.keys(localStorage),
                    outside:[...main.querySelectorAll('*')].filter(e=>{{const r=e.getBoundingClientRect();return r.width>0&&!e.closest('.hx-tabs-rulerbox,[hidden]')&&(r.right>innerWidth+1||r.left< -1);}}).slice(0,8).map(e=>e.className),
                    errors:[...main.querySelectorAll('[role=alert]')].map(e=>e.textContent)}};
                  return (v.width==={width}&&v.scroll<=v.width&&!v.outside.length&&v.locale==={json.dumps(locale)}&&v.theme==={json.dumps(theme)}&&!!v.heading?'PASS|':'FAIL|')+JSON.stringify(v); }}''')
                records.append({'path': path, 'locale': locale, 'theme': theme, 'width': width, 'result': result})
                (OUT / f'{args.role}-matrix.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
                if 'PASS|' not in result:
                    raise SystemExit(result)
print(f'{len(records)} real dashboard viewport/language/theme checks passed')
