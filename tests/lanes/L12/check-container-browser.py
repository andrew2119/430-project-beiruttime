"""Build only changed web image; reuse Auction with read-only current source mounts.

Invoke through bt-heavy.sh --build (or ordinary bt-heavy.sh when reusing web too).
"""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
root=Path(__file__).resolve().parents[3]
os.chdir(root)
suffix=hashlib.sha256(str(root).encode()).hexdigest()[:8]
auction='beirut-time/auction:l12-proof-'+suffix
web='beirut-time/web:l12-proof-'+suffix
if subprocess.run(['docker','image','inspect',auction],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
    raise SystemExit('A reusable Auction runtime image is required before this check')
if os.environ.get('BT_L12_REUSE_WEB_IMAGE')!='1':
    subprocess.run(['docker','build','--target','runtime','-f','web/Dockerfile','-t',web,'.'],check=True)
env={**os.environ,'BT_L12_CONTAINER_BROWSER':'1','BT_L12_AUCTION_IMAGE':auction,'BT_L12_WEB_IMAGE':web}
subprocess.run([sys.executable,'tests/lanes/L12/check-browser.py'],check=True,env=env)
