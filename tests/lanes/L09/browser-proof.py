"""Start/stop a clearly labeled, isolated browser contract proof without building images."""
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
STATE=ARTIFACTS/'browser-proof-state.json'
REGISTRATION=ROOT/'web/registrations/L09.ts'
PORTAL=ROOT/'web/features/moderation/__fixture_portal.tsx'
PAGE=ROOT/'web/app/(moderation)/operations/moderation/fixture-login/page.tsx'
ORIGIN='http://127.0.0.1:3109'
MARKER='L09_CONTRACT_FIXTURE_ONLY'


def settings(state):
    config=json.loads(subprocess.check_output(['./infra/foundation/compose.sh','config','--format','json'],cwd=ROOT))
    return {**os.environ,'BT_L09_TEST_IMAGE':state['image'],'BT_L09_WORKTREE':str(ROOT),
        'BT_L09_CONTRACTS':state['contracts'],'BT_L09_PROOF_ORIGIN':ORIGIN,
        'BT_L09_NETWORK':config['name']+'_default',
        'TEST_DATABASE_ADMIN_URL':'postgresql://postgres:'+config['services']['postgres']['environment']['POSTGRES_PASSWORD']+'@postgres:5432/postgres'}


def compose(state,*arguments,**kwargs):
    return subprocess.run(['docker','compose','-p',state['project'],'-f','tests/lanes/L09/browser-compose.yaml',*arguments],cwd=ROOT,env=settings(state),check=True,**kwargs)


def save(state):
    STATE.write_text(json.dumps(state,indent=2))


def stop():
    if not STATE.exists():
        print('No L09 browser proof is active')
        return
    state=json.loads(STATE.read_text())
    pid=state.get('web_pid')
    if pid:
        command=subprocess.run(['ps','-p',str(pid),'-o','command='],text=True,capture_output=True).stdout
        if 'beirut-time-web' in command and '3109' in command:
            try:
                os.killpg(pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
    compose(state,'stop','-t','30')
    REGISTRATION.write_text(Path(state['registration_backup']).read_text())
    for path in (PORTAL,PAGE):
        if path.exists():
            path.unlink()
    if PAGE.parent.exists():
        PAGE.parent.rmdir()
    # Next's ignored dev validator can retain the now-removed temporary route.
    # Remove only this worktree's generated type cache when it names our overlay;
    # the next dev/typegen invocation regenerates it from the restored app tree.
    dev_types=ROOT/'web/.next/dev/types'
    validator=dev_types/'validator.ts'
    if validator.exists() and 'operations/moderation/fixture-login' in validator.read_text():
        shutil.rmtree(dev_types)
    shutil.rmtree(state['contracts'],ignore_errors=True)
    STATE.unlink()
    print('L09 proof stopped; product registration restored; shared images/storage untouched')


def start(image):
    if STATE.exists() or PORTAL.exists() or PAGE.parent.exists():
        raise SystemExit('Stop the prior proof/overlay before starting another')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',3109))
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    run=uuid4().hex[:8]
    contracts=ARTIFACTS/('browser-contracts-'+run)
    contracts.mkdir(mode=0o755)
    subprocess.run(['python3','infra/foundation/package-contracts.py',str(contracts)],cwd=ROOT,check=True)
    backup=ARTIFACTS/('registration-'+run+'.ts')
    backup.write_text(REGISTRATION.read_text())
    state={'image':image,'project':'bt-l09-browser-'+run,'contracts':str(contracts),'registration_backup':str(backup)}
    save(state)
    try:
        text=REGISTRATION.read_text()
        if text.count('gateway:[')!=1:
            raise RuntimeError('Unexpected registration shape; no overlay applied')
        fixture="""gateway:[
    // L09_CONTRACT_FIXTURE_ONLY: temporary versioned authentication transport.
    ...['login','refresh','logout'].map(operation=>({service:'identity' as const,path:'/v1/accounts/'+operation,methods:['POST' as const],roles:['public' as const],forwardCookies:['bt_refresh']})),"""
        REGISTRATION.write_text(text.replace('gateway:[',fixture,1))
        PORTAL.write_text((ROOT/'tests/lanes/L09/web/fixture-portal.tsx').read_text())
        PAGE.parent.mkdir(parents=True)
        PAGE.write_text("import FixturePortal from '@/features/moderation/__fixture_portal';\nexport default function Page(){return <FixturePortal/>;}\n")
        compose(state,'up','-d','--no-build','--wait','--wait-timeout','120')
        urls={}
        for name,port in (('identity',18301),('trust',18307),('communications',18308),('service-operations',18309)):
            result=compose(state,'port','proof',str(port),capture_output=True,text=True)
            urls[name]='http://'+result.stdout.strip()
        state['urls']=urls
        web_env={**os.environ,'BT_PUBLIC_WEB_ORIGINS':ORIGIN,'BT_TRUST_FORWARDED_ORIGIN':'false',
            'IDENTITY_API_URL':urls['identity'],'TRUST_API_URL':urls['trust'],
            'COMMUNICATIONS_API_URL':urls['communications'],'SERVICE_OPERATIONS_API_URL':urls['service-operations']}
        with (ARTIFACTS/'browser-proof-web.log').open('w') as output:
            process=subprocess.Popen(['pnpm','--filter','beirut-time-web','exec','next','dev','--hostname','127.0.0.1','--port','3109'],cwd=ROOT,env=web_env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        state['web_pid']=process.pid
        save(state)
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError('Proof web failed to start')
            try:
                with urlopen(ORIGIN+'/en/operations/moderation/fixture-login',timeout=2) as response:
                    if response.status==200:
                        print('CONTRACT FIXTURE ONLY: '+ORIGIN+'/en/operations/moderation/fixture-login')
                        print('Domain modules write isolated databases; no receipt or technical pass is supplied')
                        return
            except (OSError,TimeoutError):
                time.sleep(.5)
        raise RuntimeError('Proof web startup deadline exceeded')
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
        parser.error('Pass an existing validated test image; this proof never builds')
    else:
        start(args.image)
