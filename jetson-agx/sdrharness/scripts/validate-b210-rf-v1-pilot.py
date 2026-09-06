#!/usr/bin/env python3
"""One explicitly authorized finite 2440-MHz source burst, received replay and existing stores."""
import argparse
import asyncio
import base64
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sys
import time
import urllib.request
import numpy as np

if not __debug__:raise RuntimeError('validation requires assertions')
SCRIPTS=Path(__file__).parent

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
rf=module('rf','validate-rf-v1-runtime-live.py')
sup=module('sup','amc-worker-supervisor.py')
source=module('source','analyze-b210-source-match.py')
NX=['ssh','-F','/home/jetson/.ssh/config','-o','ConnectTimeout=20','-o','ServerAliveInterval=5','-o','ServerAliveCountMax=3','nx']
def sha(data):return hashlib.sha256(data).hexdigest()
def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def correlation(raw,reference,center):
    z=np.frombuffer(raw,dtype='<i2').reshape(-1,2).astype(float);iq=z[:,0]+1j*z[:,1]
    width=source.source_bandwidth(reference)
    # Source-derived filtering is diagnostic only; raw bytes go unchanged to RF-v1.
    correction=2440000000-center
    iq=iq*np.exp(-2j*np.pi*correction*np.arange(len(iq))/2100000)
    filtered=np.fft.ifft(np.fft.fft(iq)*(abs(np.fft.fftfreq(len(iq),1/2100000))<=width))
    ref=np.fft.ifft(np.fft.fft(reference)*(abs(np.fft.fftfreq(4096,1/2100000))<=width))
    target=abs(ref)-np.mean(abs(ref));rows=[]
    for start in range(0,len(filtered)-4095,4096):
        env=abs(filtered[start:start+4096]);env-=env.mean()
        norm=np.sqrt(np.sum(env**2)*np.sum(target**2))
        if not norm>0:raise ValueError('degenerate source diagnostic')
        cc=np.fft.ifft(np.fft.fft(env)*np.fft.fft(target).conj()).real/norm
        rows.append({'best_correlation':float(cc.max()),'lag':int(cc.argmax())})
    return {'source_half_width_hz':width,'windows':rows,'label':'unknown','calibration_eligible':False}

async def validate(root, replay_only=False):
    assert root.resolve()==root and root==Path('/var/tmp/sdrharness-dev/b210-pilot-906a')
    summary_path=root/('replay-summary.json' if replay_only else 'pilot-summary.json')
    assert not summary_path.exists()
    prior=json.loads((root/'pilot-summary.json').read_text()) if replay_only else None
    txplan=json.loads((root/'transmission-plan.json').read_text());tile=(root/'train-tile.fc32').read_bytes()
    assert sha(tile)==txplan['payload_sha256']=='c95ac58c1fd91ef4da992622dbdf70a9bc5884d0941419083451473a052f534e'
    assert txplan['tx_samples']==21000000 and txplan['tx_gain_db']==70
    available=shutil.disk_usage(root).free;assert available>8*1024*1024
    env={**os.environ,'TMPDIR':str(root/'tmp'),'PYTHONDONTWRITEBYTECODE':'1','TRITON_CACHE_DIR':str(root/'triton'),'CUDA_CACHE_PATH':str(root/'cuda-cache')}
    binary=root/'target/debug/sdr-agent-controller';example=root/'target/debug/examples/recognize-received-window'
    generation=time.time_ns()//1000000;paths=[];processes=[];tx=None;txpid=None;worker_pid=None
    report={'schema_version':1,'status':'failed','maximum_rx_bytes':802804,'maximum_tx_samples':21000000,'tx_nominal_seconds':10,'tx_plan':txplan,'source_group':'b210-rml-train-'+sha(tile),'capture_session_id':f'b210-pilot-{generation}','receive_domain_only':True,'reviewed_labels':0,'v1b_complete':False,'recognizer_available':False,'free_bytes':available,'cases':{}}
    if prior is not None:
        assert prior['cleanup']['errors']==[] and prior['nx_helper_child_fifo_absent']
        report=prior
        paths=list(prior['p201_directories'])
        report['rf_validation_status']=prior['status']
        report['rf_failure']=report.pop('failure',None)
        report['integration_status']='failed'
        report['offline_replay_only']=True
    async def command(args,timeout=15,data=None):
        p=await asyncio.create_subprocess_exec(*map(str,args),env=env,stdin=asyncio.subprocess.PIPE if data is not None else None,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            out,err=await asyncio.wait_for(p.communicate(data),timeout)
            if p.returncode:raise RuntimeError(err.decode(errors='replace')[-2000:])
            return out
        finally:
            if p.returncode is None:p.kill();await p.wait()
    async def radio():return (await command([*rf.SSH,rf.STATE_COMMAND])).decode()
    before=await radio();report['radio_before']=before
    state=dict(zip(before.splitlines()[::2],before.splitlines()[1::2]));assert all(v=='0' for p,v in state.items() if p.endswith('/enable') or p.endswith('_en'))
    connections=(await command([*rf.SSH,'netstat -nt 2>/dev/null; true'])).decode()
    assert not any(':30431 ' in l and 'ESTABLISHED' in l for l in connections.splitlines())
    daemon=(await command([*rf.SSH,'pidof sdrd'])).decode().strip();assert len(daemon.split())==1;report['sdrd_pid']=daemon
    async def launch(name,args,environment=env):
        with (root/f'{name}.log').open('w') as out:
            p=await asyncio.create_subprocess_exec(*map(str,args),env=environment,stdout=out,stderr=asyncio.subprocess.STDOUT)
        processes.append(p);return p
    async def capture(tag,index,samples=65535,center=2440000000):
        gen=generation+index;path=root/tag;path.mkdir(mode=0o700)
        plan={'sweep_id':f'pilot-{tag}-{gen}','session_generation':gen,'frequencies':{'kind':'centers','centers_hz':[center]},'sample_rate_hz':2100000,'rf_bandwidth_hz':1500000,'gain_db':50,'settle_ms':100 if samples==4096 else 500,'frame_samples':samples,'aggregate_frames':1,'point_timeout_ms':1000,'detection_threshold_db':6.}
        transient=f'/tmp/sdr-agent-dev/agx-sweep-{gen}-0';paths.append(transient)
        print(json.dumps({'event':'rx_plan','plan':plan,'max_bytes':samples*4,'estimated_duration_ms':plan['settle_ms']+plan['point_timeout_ms'],'free_bytes':shutil.disk_usage(root).free,'temporary_directory':str(path),'p201_directory':transient,'stop_generation':gen}),flush=True)
        assert shutil.disk_usage(root).free>samples*4+8*1024*1024
        started=time.time_ns()//1000000
        p=await asyncio.create_subprocess_exec(str(binary),'--mode','sweep','--sdrd','192.168.1.10:43110','--sigmf-directory',str(path),env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        processes.append(p)
        try:out,err=await asyncio.wait_for(p.communicate(json.dumps(plan).encode()),15)
        except BaseException:
            try:await command([binary,'--mode','cancel','--sdrd','192.168.1.10:43110','--session-generation',gen],timeout=6)
            except Exception as error:report.setdefault('cancel_errors',[]).append(str(error))
            raise
        done=time.time_ns()//1000000
        (root/f'{tag}-native-report.json').write_bytes(out);(root/f'{tag}-stderr.log').write_bytes(err)
        assert p.returncode==0,err.decode()[-2000:]
        value=json.loads(out);files=list(path.glob('*.sigmf-data'));assert len(files)==1 and files[0].stat().st_size==samples*4
        assert rf.restored_state(before,await radio())
        await command([*rf.SSH,f'test ! -e {transient}'])
        item={'plan':plan,'report':value,'started_at_unix_ms':started,'received_at_unix_ms':done,'raw_iq_sha256':sha(files[0].read_bytes()),'native_report_sha256':sha(out),'p201_directory':transient}
        report['cases'][tag]=item
        return item,files[0]
    async def stop_tx():
        if txpid is not None:
            # Never signal a reused/unrelated PID; verify this exact feature command.
            script=f'if test -r /proc/{txpid}/cmdline; then case "$(tr "\\000" " " < /proc/{txpid}/cmdline)" in *"{root}/b210-finite-train-tx.py"*) kill -TERM {txpid};; *) exit 1;; esac; fi'
            await command([*NX,script],timeout=25)
    runtime=root/'mamba';web_port=port();base=f'http://127.0.0.1:{web_port}'
    def http(route,method='GET',data=None):
        raw=None if data is None else json.dumps(data).encode();request=urllib.request.Request(base+route,data=raw,method=method,headers={'Content-Type':'application/json'})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=8) as response:
            out=response.read(384*1024+1);assert len(out)<=384*1024;return json.loads(out)
    print(json.dumps({k:v for k,v in report.items() if k not in ('radio_before','cases','tx_plan')}),flush=True)
    try:
        await launch('mamba',[sys.executable,SCRIPTS/'amc-worker-supervisor.py','--runtime-root',runtime,'--gpu-lease-root',root/'gate','--max-batches','2','--max-restarts','1','--lifetime-seconds','600'])
        for _ in range(1500):
            try:
                h=await sup.exchange(runtime/'control.sock',{'schema_version':1,'operation':'health'},1,sup.FRAME)
                if h['fault']:raise RuntimeError(h['fault'])
                if h['ready']:worker_pid=h['worker_pid'];report['worker_before']=h;break
            except (OSError,asyncio.TimeoutError):pass
            await asyncio.sleep(.1)
        else:raise RuntimeError('Worker startup timeout')
        webenv={**env,'SDR_WEB_LISTEN_HOST':'127.0.0.1','SDR_WEB_LISTEN_PORT':str(web_port),'SDR_WEB_STATE_PATH':str(root/'web-state.json'),'SDR_WEB_AGENT_BINARY':'/bin/false','SDR_WEB_PROVIDER_CONFIG_PATH':str(root/'absent-provider.json'),'SDR_WEB_RESULT_DB_PATH':str(root/'results.sqlite3'),'SDR_WEB_CAPTURE_ROOT':str(root/'app-captures'),'SDR_WEB_CORPUS_ROOT':str(root/'app-corpus')}
        await launch('web',[root/'target/debug/sdr-agent-web-console'],webenv)
        for _ in range(100):
            try:
                if http('/api/health')['ready']:break
            except OSError:pass
            await asyncio.sleep(.05)
        else:raise RuntimeError('private Web startup timeout')
        if not replay_only:
            baseline,_=await capture('baseline',0)
            tx=await asyncio.create_subprocess_exec(*NX,f'timeout --signal=TERM --kill-after=3s 65s python3 {root}/b210-finite-train-tx.py --directory {root}',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            processes.append(tx)
            ready=json.loads(await asyncio.wait_for(tx.stdout.readline(),45));assert ready['event']=='ready';txpid=ready['pid'];report['tx_ready']=ready
            tx.stdin.write(b'GO\n');await tx.stdin.drain()
            started=json.loads(await asyncio.wait_for(tx.stdout.readline(),2));assert started['event']=='tx_start';report['tx_started']=started;report['tx_ack_agx_ms']=time.time_ns()//1000000
            inspection,_=await capture('inspection',1)
            center=inspection['report']['points'][0]['spectral']['estimated_center_hz'];assert abs(center-2440000000)<=750000
            captured,raw_path=await capture('capture',2,4096,center)
            output,error=await asyncio.wait_for(tx.communicate(),15)
            (root/'tx-stdout.log').write_bytes(output);(root/'tx-stderr.log').write_bytes(error)
            assert tx.returncode==0,error.decode()[-2000:]
            report['tx_result']=json.loads(output);assert report['tx_result']['status']=='sent' and report['tx_result']['bytes_written']==21000000*8
            after,_=await capture('after',3)
        else:
            inspection=report['cases']['inspection'];captured=report['cases']['capture']
            raw_path=next((root/'capture').glob('*.sigmf-data'))
            assert sha(raw_path.read_bytes())==captured['raw_iq_sha256']
        await command(['scp','-F','/home/jetson/.ssh/config',f'nx:{root}/tx-summary.json',str(root/'tx-summary.json')],timeout=25)
        await command(['scp','-F','/home/jetson/.ssh/config',f'nx:{root}/tx-uhd.log',str(root/'tx-uhd.log')],timeout=25)
        values=np.frombuffer(tile,dtype='<f4').reshape(-1,2);reference=values[:,0]+1j*values[:,1]
        diagnoses={}
        for tag in report['cases']:
            raw=next((root/tag).glob('*.sigmf-data')).read_bytes()
            diagnoses[tag]=correlation(raw,reference,report['cases'][tag]['report']['points'][0]['actual_center_hz'])
        report['source_diagnostic_before_inference']=diagnoses
        report['missing_source_controls']=[tag for tag in ('baseline','after') if tag not in diagnoses]
        (root/'source-link.json').write_text(json.dumps({'schema_id':'b210_rf_v1_pilot_link_v1','source_group':report['source_group'],'source_split':'train','capture_iq_sha256':captured['raw_iq_sha256'],'diagnostic':diagnoses,'label':'unknown','review_pending':True,'evaluation_eligible':False},indent=2)+'\n')
        raw_path.rename(root/'received.ci16');raw_path=root/'received.ci16';raw_path.chmod(0o600)
        request={'schema_version':1,'candidate_id':'b210-pilot-source','request_id':10001,'inspection_plan':inspection['plan'],'inspection_report':inspection['report'],'inspection_received_at_unix_ms':inspection['received_at_unix_ms'],'capture_plan':captured['plan'],'capture_report':captured['report'],'capture_received_at_unix_ms':captured['received_at_unix_ms'],'raw_iq_file':raw_path.name,'raw_iq_sha256':captured['raw_iq_sha256']}
        input_path=root/'received-window.json';input_path.write_text(json.dumps(request))
        await command([example,input_path,root,'--validate-only'])
        result=json.loads(await command([example,input_path,root,runtime],timeout=15))
        assert result['synthetic_input'] is False and result['raw_iq_sha256']==captured['raw_iq_sha256'] and result['result']['observation']['status']=='unavailable'
        assert result['result']['observation']['observed_at_unix_ms']==captured['received_at_unix_ms']
        (root/'recognition-full.json').write_text(json.dumps(result,indent=2)+'\n')
        archive=http('/api/recognition-results','POST',{'schema_version':1,'session_id':report['capture_session_id'],'origin':'experimental_replay','result':result['result']})
        report['recognition_archive']=archive
        raw=raw_path.read_bytes();raw_path.unlink()
        # The store receives an explicit projection after removing deleted staging descriptors.
        projection=json.loads(json.dumps(captured['report']));projection['dataset']=None
        temp_dir=root/'capture';shutil.rmtree(temp_dir);assert not temp_dir.exists()
        captured['corpus_report_projection_sha256']=sha(json.dumps(projection,sort_keys=True,separators=(',',':')).encode())
        ingest={'schema_version':1,'capture_session_id':report['capture_session_id'],'captured_at_utc':datetime.datetime.fromtimestamp(captured['received_at_unix_ms']/1000,datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),'label_reason':'no_independent_label','plan':captured['plan'],'report':projection,'iq_base64':base64.b64encode(raw).decode(),'preflight':{'point_count':1,'samples_per_point':4096,'maximum_iq_bytes':16384,'estimated_duration_ms':projection['estimated_duration_ms'],'agx_available_bytes_before':available,'agx_temporary_directory':None,'p201_transient_directory':captured['p201_directory'],'direct_stop':f"SDRD/1 STOP_SESSION {captured['plan']['session_generation']}",'radio_restored':True,'p201_transient_removed':True,'agx_temporary_removed':True}}
        parent=http('/api/corpus','POST',ingest);parent_id=parent['summary']['result_id']
        package=root/'app-corpus'/parent_id
        derive={'schema_version':1,'result_id':parent_id+'-rf1','parent_manifest_sha256':sha((package/'manifest.json').read_bytes()),'parent_iq_sha256':captured['raw_iq_sha256'],'source_report':projection,'split':'receive_domain','label':{'provenance':'unknown','reason':'no_independent_label'}}
        child=http(f'/api/corpus/{parent_id}/derive-rf-v1','POST',derive)
        report['corpus_parent']=parent;report['corpus_rf_v1']=child
        assert child['summary']['iq_sha256']==captured['raw_iq_sha256']
        raw_files=[package/'raw.iq',root/'app-corpus'/derive['result_id']/'raw.iq']
        assert raw_files[0].stat().st_ino==raw_files[1].stat().st_ino
        report['corpus_shared_iq_inode_verified']=True
        report['coverage']=json.loads(await command([sys.executable,SCRIPTS/'summarize-rf-v1-evidence.py','--corpus-root',root/'app-corpus'],timeout=20))
        assert report['coverage']['v1b_complete'] is False
        report['manual_delete_results']=[http(f'/api/corpus/{parent_id}','DELETE'),http(f"/api/corpus/{derive['result_id']}",'DELETE'),http(f"/api/recognition-results/{archive['id']}",'DELETE')]
        assert http('/api/corpus')==[] and http('/api/recognition-results')==[]
        report['integration_status']='pass'
        report['status']='integration_pass_rf_control_failed' if replay_only and report['rf_validation_status']!='pass' else 'pass'
    except BaseException as e:
        report['failure']=f'{type(e).__name__}: {e}';raise
    finally:
        errors=[]
        if tx is not None and tx.returncode is None:
            try:await stop_tx()
            except Exception as e:errors.append('TX stop: '+str(e))
        for p in reversed(processes):
            if p.returncode is None:
                p.terminate()
                try:await asyncio.wait_for(p.wait(),15)
                except asyncio.TimeoutError:p.kill();await p.wait()
        try:
            report['radio_final']=await radio();assert rf.restored_state(before,report['radio_final'])
            assert (await command([*rf.SSH,'pidof sdrd'])).decode().strip()==daemon
            for path in paths:await command([*rf.SSH,f'test ! -e {path}'])
            if worker_pid:assert not Path(f'/proc/{worker_pid}').exists()
            if txpid is not None:
                child_pid=report['tx_ready']['child_pid']
                await command([*NX,f'test ! -d /proc/{txpid} && test ! -d /proc/{child_pid} && test ! -e {root}/tx.fc32.fifo'],timeout=25)
                report['nx_helper_child_fifo_absent']=True
        except Exception as e:errors.append(str(e))
        report['p201_directories']=paths;report['worker_pid']=worker_pid
        report['cleanup']={'errors':errors,'local_process_exit_codes':[p.returncode for p in processes],'worker_stopped':worker_pid is None or not Path(f'/proc/{worker_pid}').exists()}
        if errors:report['status']='failed'
        summary_path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    assert report.get('integration_status')=='pass' and not report['cleanup']['errors']
    print(json.dumps({'status':report['status'],'integration_status':report['integration_status'],'recognizer_available':False}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--replay-only',action='store_true',help='Use existing capture evidence; never transmit or capture');args=parser.parse_args()
    async def main():
        task=asyncio.current_task()
        for sig in (signal.SIGINT,signal.SIGTERM):asyncio.get_running_loop().add_signal_handler(sig,task.cancel)
        await validate(args.directory,args.replay_only)
    asyncio.run(main())
