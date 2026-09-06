#!/usr/bin/env python3
"""O1a deterministic offline fault matrix and isolated native health/HTTP validation."""
import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import stat
import sys
import time
import urllib.error
import urllib.request

if not __debug__:raise RuntimeError('assertions required')
ROOT=Path(__file__).resolve().parents[3]
SCRIPTS=Path(__file__).parent
spec=importlib.util.spec_from_file_location('ops',SCRIPTS/'operations-health.py')
ops=importlib.util.module_from_spec(spec);spec.loader.exec_module(ops)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def corpus(seed):
    state=20260906;result=[]
    for i in range(256):
        state=(state*1664525+1013904223)&0xffffffff;p=state%len(seed)
        if i%4==0:x=seed[:p]
        elif i%4==1:x=seed[:p]+b'\0'+seed[p+1:]
        elif i%4==2:x=seed+b'\n{}'
        else:x=seed[:p]+bytes([state%128])+seed[p+1:]
        result.append(x)
    return result


async def validate(root,skip_suites=False):
    assert root.is_absolute() and root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev') and root.name.startswith('o1a-')
    assert not (root/'operations-summary.json').exists()
    (root/'tmp').mkdir(exist_ok=True,mode=0o700)
    env={**os.environ,'TMPDIR':str(root/'tmp'),'CARGO_TARGET_DIR':str(root/'target'),'PYTHONDONTWRITEBYTECODE':'1','TRITON_CACHE_DIR':str(root/'triton-cache'),'CUDA_CACHE_PATH':str(root/'cuda-cache')}
    controller=ROOT/'raspberry-pi/sdr-agent/controller';web=ROOT/'raspberry-pi/sdr-agent/web-console';node=ROOT/'raspberry-pi/sdr-agent/planner-worker'
    report={'schema_version':1,'status':'failed','rx_bytes':0,'locked_test_read':False,'recognizer_available':False,'suites':[],'cases':[]}
    processes=[];sockets=[]
    async def run(name,args,timeout=900,cwd=ROOT):
        log=root/f'{name}.log';start=time.monotonic()
        with log.open('w') as out:
            p=await asyncio.create_subprocess_exec(*map(str,args),cwd=cwd,env=env,stdout=out,stderr=asyncio.subprocess.STDOUT,start_new_session=True)
            try:await asyncio.wait_for(p.wait(),timeout)
            finally:
                if p.returncode is None:
                    os.killpg(p.pid,signal.SIGTERM)
                    try:await asyncio.wait_for(p.wait(),5)
                    except asyncio.TimeoutError:os.killpg(p.pid,signal.SIGKILL);await p.wait()
        item={'name':name,'argv':[str(a).replace(str(ROOT),'$REPO').replace(str(root),'$FEATURE') for a in args],'exit_code':p.returncode,'seconds':time.monotonic()-start,'sha256':sha(log)}
        report['suites'].append(item);print(json.dumps(item),flush=True)
        assert p.returncode==0,name
    async def launch(name,args,environment):
        with (root/f'{name}.log').open('w') as out:
            p=await asyncio.create_subprocess_exec(*map(str,args),env=environment,stdout=out,stderr=asyncio.subprocess.STDOUT)
        processes.append(p);return p
    try:
        if not skip_suites:
            for directory,name in ((controller,'controller'),(web,'web')):
                await run(name+'-fmt',['cargo','fmt','--manifest-path',directory/'Cargo.toml','--check'])
                await run(name+'-tests',['cargo','test','--manifest-path',directory/'Cargo.toml','--all-targets','--','--nocapture'])
                await run(name+'-clippy',['cargo','clippy','--manifest-path',directory/'Cargo.toml','--all-targets','--','-D','warnings'])
            await run('node-tests',['node','--test'],cwd=node)
            for pattern,name in [('test_operations*.py','operations-tests'),('test_gpu_lease.py','gpu-fault-tests'),('test_amc_worker_supervisor.py','supervisor-fault-tests'),('test_amc_mamba_worker.py','worker-contract-tests')]:
                interpreter = ROOT/'local-assets/amc-eval/runtime/venv/bin/python' if name=='worker-contract-tests' else Path(sys.executable)
                await run(name,[interpreter,'-m','unittest','discover','-s',SCRIPTS.parent/'tests','-p',pattern],timeout=120)
            await run('c-sanitized-tests',['make','-C',ROOT/'sdr-system/sdrd','test',f'BUILD_DIR={root}/sdrd-sanitized','CFLAGS=-std=c11 -O1 -g -Wall -Wextra -Wpedantic -Werror -fsanitize=address,undefined -fno-omit-frame-pointer','LDFLAGS=-fsanitize=address,undefined'])
        await run('web-build',['cargo','build','--manifest-path',web/'Cargo.toml'])
        controls=Path(f'/run/user/{os.getuid()}/sdrharness');controls.mkdir(exist_ok=True,mode=0o700)
        sockets=[controls/f'{root.name}-planner.sock',controls/f'{root.name}-session.sock']
        assert not any(p.exists() for p in sockets)
        address=port()
        nodeenv={**env,'SDR_PLANNER_BASE_URL':'http://127.0.0.1:9/v1','SDR_PLANNER_API_KEY':'o1a-unused-local-key','SDR_PLANNER_PROVIDER':'spark-local','SDR_PLANNER_MODEL':'spark-x2.5-4b','SDR_PLANNER_PROVIDER_CONFIG':str(root/'absent-provider.json'),'SDR_PLANNER_SOCKET':str(sockets[0]),'SDR_SESSION_SOCKET':str(sockets[1]),'SDR_PLANNER_TIMEOUT_MS':'1000','SDR_PLANNER_WEB_SEARCH_URL':''}
        await launch('native-node',['node',node/'src/main.mjs'],nodeenv)
        webenv={**env,'SDR_WEB_LISTEN_HOST':'127.0.0.1','SDR_WEB_LISTEN_PORT':str(address),'SDR_WEB_STATE_PATH':str(root/'state.json'),'SDR_WEB_AGENT_BINARY':'/bin/false','SDR_WEB_REQUEST_PATH':str(ROOT/'jetson-agx/sdrharness/config/request.json'),'SDR_WEB_PROVIDER_CONFIG_PATH':str(root/'absent-web-provider.json'),'SDR_WEB_RESULT_DB_PATH':str(root/'results.sqlite3'),'SDR_WEB_CAPTURE_ROOT':str(root/'captures'),'SDR_WEB_CORPUS_ROOT':str(root/'corpus'),'SDR_WEB_SDRD_ADDRESS':'127.0.0.1:9','SDR_WEB_SESSION_SOCKET':str(sockets[1])}
        webproc=await launch('native-web',[root/'target/debug/sdr-agent-web-console'],webenv)
        probes=[{'name':'web','kind':'http','endpoint':f'http://127.0.0.1:{address}/api/health'},{'name':'planner','kind':'unix','endpoint':str(sockets[0])}]
        config=ops.validate_config({'schema_version':1,'probes':probes,'disk_path':str(root),'minimum_free_bytes':4*1024**3})
        for _ in range(100):
            statuses=await asyncio.gather(*(asyncio.to_thread(ops.probe,p) for p in probes))
            if all(p['status']=='healthy' for p in statuses):break
            await asyncio.sleep(.05)
        else:raise RuntimeError('native health startup failed')
        report['cases'].append({'name':'native_readonly_health','statuses':statuses})
        frames=corpus(b'{"protocol_version":1,"operation":"unsupported"}')
        for raw in frames:
            reader,writer=await asyncio.open_unix_connection(str(sockets[0]),limit=32769)
            try:
                writer.write(raw+b'\n');await writer.drain();reply=await asyncio.wait_for(reader.readline(),4)
                result=json.loads(reply);assert result['status']=='error'
            finally:writer.close();await writer.wait_closed()
        assert (await asyncio.to_thread(ops.probe,probes[1]))['status']=='healthy'
        report['cases'].append({'name':'native_planner_fuzz','count':256,'seed':20260906,'sha256':hashlib.sha256(b'\0'.join(frames)).hexdigest()})
        def invalid_http(raw):
            request=urllib.request.Request(f'http://127.0.0.1:{address}/api/recognition-results',data=raw,method='POST',headers={'Content-Type':'application/json'})
            try:
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=2) as response:return response.status
            except urllib.error.HTTPError as e:return e.code
        frames=corpus(b'{"origin":"invalid","result":{}}')
        for raw in frames:assert 400<=await asyncio.to_thread(invalid_http,raw)<500
        report['cases'].append({'name':'native_web_archive_fuzz','count':256,'seed':20260906,'sha256':hashlib.sha256(b'\0'.join(frames)).hexdigest()})
        state=root/'health-state.json';healthy=await asyncio.to_thread(ops.snapshot,config,state)
        assert all(v=='healthy' for v in healthy['statuses'].values())
        assert not (await asyncio.to_thread(ops.snapshot,config,state))['events']
        webproc.terminate();await asyncio.wait_for(webproc.wait(),45)
        failed=await asyncio.to_thread(ops.snapshot,config,state);assert failed['statuses']['web']=='unavailable'
        assert not (await asyncio.to_thread(ops.snapshot,config,state))['events']
        webproc=await launch('native-web-restarted',[root/'target/debug/sdr-agent-web-console'],webenv)
        for _ in range(100):
            if (await asyncio.to_thread(ops.probe,probes[0]))['status']=='healthy':break
            await asyncio.sleep(.05)
        recovered=await asyncio.to_thread(ops.snapshot,config,state)
        assert {'service':'web','event':'recovered','status':'healthy'} in recovered['events']
        report['cases'].append({'name':'native_failure_dedupe_recovery','initial':healthy,'failed':failed,'recovered':recovered})
        report['status']='pass'
    except BaseException as error:
        report['failure']=f'{type(error).__name__}: {error}'
        raise
    finally:
        for p in reversed(processes):
            if p.returncode is None:
                p.terminate()
                try:await asyncio.wait_for(p.wait(),45)
                except asyncio.TimeoutError:p.kill();await p.wait()
        for p in sockets:
            if p.exists():
                assert stat.S_ISSOCK(p.lstat().st_mode);p.unlink()
        report['cleanup']={'process_exit_codes':[p.returncode for p in processes],'control_sockets_absent':all(not p.exists() for p in sockets),'control_sockets':[str(p) for p in sockets]}
        (root/'operations-summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('O1a offline faults and isolated native operations passed',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--feature-directory',type=Path,required=True);p.add_argument('--skip-suites',action='store_true',help='native smoke only; never claims omitted suites passed');a=p.parse_args()
    asyncio.run(validate(a.feature_directory,a.skip_suites))
