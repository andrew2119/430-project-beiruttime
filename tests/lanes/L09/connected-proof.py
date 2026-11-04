"""Run current provider code without touching shared runtimes or adding fixture login routes."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
from urllib.request import urlopen
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[3]
ARTIFACTS=ROOT/'artifacts/l09'
STATE=ARTIFACTS/'connected-proof-state.json'
ORIGIN='http://127.0.0.1:33101'


def compose(state,*arguments,**kwargs):
    config=json.loads(subprocess.check_output(['./infra/foundation/compose.sh','config','--format','json'],cwd=ROOT))
    env={**os.environ,'BT_L09_TEST_IMAGE':state['image'],'BT_L09_WORKTREE':str(ROOT),'BT_L09_CONTRACTS':state['contracts'],
        'BT_L09_PROOF_ORIGIN':ORIGIN,'BT_L09_NETWORK':config['name']+'_default',
        'TEST_DATABASE_ADMIN_URL':'postgresql://postgres:'+config['services']['postgres']['environment']['POSTGRES_PASSWORD']+'@postgres:5432/postgres'}
    return subprocess.run(['docker','compose','-p',state['project'],'-f','tests/lanes/L09/connected-compose.yaml',*arguments],cwd=ROOT,env=env,check=True,**kwargs)


def save(state):
    STATE.write_text(json.dumps(state,indent=2))


def stop():
    if not STATE.exists():
        print('No connected L09 proof is active')
        return
    state=json.loads(STATE.read_text())
    if pid:=state.get('web_pid'):
        command=subprocess.run(['ps','-p',str(pid),'-o','command='],text=True,capture_output=True).stdout
        if 'beirut-time-web' in command and '33101' in command:
            try:
                os.killpg(pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
    compose(state,'stop','-t','30')
    shutil.rmtree(state['contracts'],ignore_errors=True)
    STATE.unlink()
    print('Connected proof stopped; no shared runtimes, images or storage removed')


def start(image):
    if STATE.exists():
        raise SystemExit('Stop the prior connected proof first')
    for service in ('identity','eligibility'):
        if not (ROOT/f'services/{service}/runtime/service_app/main.py').exists():
            raise SystemExit('Merge the real Identity provider before this proof')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',33101))
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    run=uuid4().hex[:8]
    contracts=ARTIFACTS/('connected-contracts-'+run)
    contracts.mkdir(mode=0o755)
    subprocess.run(['python3','infra/foundation/package-contracts.py',str(contracts)],cwd=ROOT,check=True)
    state={'image':image,'project':'bt-l09-connected-'+run,'contracts':str(contracts)}
    save(state)
    try:
        compose(state,'up','-d','--no-build','--wait','--wait-timeout','120')
        urls={}
        for name,port in (('identity',18301),('eligibility',18306),('trust',18307)):
            result=compose(state,'port','proof',str(port),capture_output=True,text=True)
            urls[name]='http://'+result.stdout.strip()
        state['urls']=urls
        env={**os.environ,'BT_PUBLIC_WEB_ORIGINS':ORIGIN,'BT_TRUST_FORWARDED_ORIGIN':'false',
            **{name.upper().replace('-','_')+'_API_URL':url for name,url in urls.items()}}
        with (ARTIFACTS/'connected-proof-web.log').open('w') as out:
            process=subprocess.Popen(['pnpm','--filter','beirut-time-web','exec','next','dev','--hostname','127.0.0.1','--port','33101'],cwd=ROOT,env=env,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
        state['web_pid']=process.pid
        save(state)
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError('Connected web failed to start')
            try:
                with urlopen(ORIGIN+'/en/account?next=%2Foperations%2Fmoderation',timeout=2) as response:
                    if response.status==200:
                        print('Real Identity/Eligibility/Trust, disposable databases: '+ORIGIN+'/en/account?next=%2Foperations%2Fmoderation')
                        print('No fixture authority, seeded grants, consent, custody or technical outcomes')
                        return
            except (OSError,TimeoutError):
                time.sleep(.5)
        raise RuntimeError('Connected web startup deadline exceeded')
    except BaseException:
        stop()
        raise


if __name__=='__main__':
    os.chdir(ROOT)
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('start','stop'))
    parser.add_argument('--image',default=os.getenv('BT_L09_TEST_IMAGE'))
    args=parser.parse_args()
    if args.action=='stop':
        stop()
    elif not args.image:
        parser.error('Pass an existing dependency image; this proof never builds')
    else:
        start(args.image)
