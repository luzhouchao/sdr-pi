#!/usr/bin/env python3
"""S5 bounded real RX/Worker/Runner/Planner validation. No training or dataset access."""
if not __debug__:
    raise RuntimeError('optimized Python would disable validation; refusing to run')

import argparse
import asyncio
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[3]
SCRIPTS=Path(__file__).parent


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


sup=module('supervisor',SCRIPTS/'amc-worker-supervisor.py')
gw=module('gateway',SCRIPTS/'spark-gpu-gateway.py')
rf=module('rf_validation',SCRIPTS/'validate-rf-v1-runtime-live.py')


def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def planner_has_internal_fields(value):
    if isinstance(value, dict):
        return any(key in {'experimental_batch', 'logits', 'iq_path', 'tensor', 'window_outputs'}
                   or planner_has_internal_fields(child) for key, child in value.items())
    if isinstance(value, list):
        return any(planner_has_internal_fields(child) for child in value)
    return False


def require_idle_radio(snapshot, connections):
    """A quiet buffer alone does not prove a persistent IIOD client released RX."""
    lines = snapshot.splitlines()
    if not lines or len(lines) % 2:
        raise ValueError('incomplete radio snapshot')
    state = dict(zip(lines[::2], lines[1::2]))
    controls = {path: value for path, value in state.items()
                if path.endswith('/enable') or path.endswith('_en')}
    if not controls or any(value != '0' for value in controls.values()):
        raise ValueError('RX busy: refusing concurrent hardware validation')
    for line in connections.splitlines():
        fields = line.split()
        if len(fields) >= 6 and fields[0] == 'tcp':
            if fields[3].endswith(':30431') and fields[5] == 'ESTABLISHED':
                raise ValueError('IIOD client connected: exclusive validation window required')


async def validate(feature):
    assert feature.resolve()==feature and feature.parent==Path('/var/tmp/sdrharness-dev')
    binary=feature/'target/debug/sdr-agent-controller';console=feature/'target/debug/sdr-agent';web=feature/'target/debug/sdr-agent-web-console'
    generation=int(time.time()*1000);gate=feature/'gate';runtime=feature/'mamba'
    summary_path=feature/f'live-summary-{generation}.json'
    gateway_port,backend_port,archive_port=port(),port(),port();assert len({gateway_port,backend_port,archive_port})==3
    key=secrets.token_hex(32);keyfile=feature/'gateway-key.txt';keyfile.write_text(key);keyfile.chmod(0o600)
    provider=feature/'provider.json';provider.write_text(json.dumps(dict(schema_version=1,api='openai-completions',base_url=f'http://127.0.0.1:{gateway_port}/v1',provider='spark-local',model='spark-x2.5-4b',api_key=key,context_window=32768,compression_threshold_percent=90)));provider.chmod(0o600)
    env={**os.environ,'TMPDIR':str(feature/'tmp'),'PYTHONDONTWRITEBYTECODE':'1','TRITON_CACHE_DIR':str(feature/'triton'),'CUDA_CACHE_PATH':str(feature/'cuda-cache')}
    processes=[];worker_pids=set();cases=[];p201_dirs=set();used_generations=set();logs=[]
    async def launch(tag,args,environment=None,interactive=False):
        log=feature/f'{tag}.log';logs.append(log)
        if interactive:
            proc=await asyncio.create_subprocess_exec(*map(str,args),env=environment or env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
        else:
            with log.open('w') as out:proc=await asyncio.create_subprocess_exec(*map(str,args),env=environment or env,stdout=out,stderr=asyncio.subprocess.STDOUT)
        processes.append(proc);return proc
    async def ssh(command):
        proc=await asyncio.create_subprocess_exec(*rf.SSH,command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err=await asyncio.wait_for(proc.communicate(),8);assert proc.returncode==0,err.decode();return out.decode()
    async def health():return await sup.exchange(runtime/'control.sock',dict(schema_version=1,operation='health'),1,sup.FRAME)
    async def ready(kind):
        end=time.monotonic()+150
        while time.monotonic()<end:
            try:
                if kind=='mamba':
                    h=await health()
                    if h['fault']:raise RuntimeError(h['fault'])
                    if h['ready']:worker_pids.add(h['worker_pid']);return h
                else:
                    status,h=await asyncio.wait_for(gw.backend_http(gateway_port,key,'/health'),1)
                    if status==200 and h['ready']:worker_pids.add(h['worker_pid']);return h
            except (OSError,asyncio.TimeoutError):pass
            await asyncio.sleep(.05)
        raise RuntimeError(kind+' startup timeout')
    async def native(args,payload=None,expected=0,timeout=90):
        proc=await asyncio.create_subprocess_exec(str(binary),*map(str,args),env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            out,err=await asyncio.wait_for(proc.communicate(None if payload is None else json.dumps(payload).encode()),timeout)
        finally:
            if proc.returncode is None:proc.kill();await proc.wait()
        if proc.returncode!=expected:raise RuntimeError(err.decode()[-3000:])
        return (json.loads(out) if out else None),err.decode()
    def archive(route='',method='GET'):
        req=urllib.request.Request(f'http://127.0.0.1:{archive_port}/api/recognition-results'+route,method=method)
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=3) as response:return json.load(response)
    async def radio_check():
        current=await ssh(rf.STATE_COMMAND);assert rf.restored_state(before,current),'radio restoration mismatch';return current
    # This is a finite validation plan, including seed inspection and at most
    # five two-capture recognition executions; pending/automatic never capture.
    before=await ssh(rf.STATE_COMMAND);daemon=(await ssh('pidof sdrd')).split();assert len(daemon)==1
    connections=await ssh('netstat -nt 2>/dev/null; true')
    require_idle_radio(before, connections)
    free=shutil.disk_usage(feature).free;assert free>32768+4*1024*1024
    audit=dict(schema_version=1,generation=generation,delivery='S5',recognizer_available=False,locked_test_read=False,training=False,
               frequency_hz=433920000,sample_rate_hz=2100000,rf_bandwidth_hz=1500000,gain_db=50,settle_ms=100,
               initial_inspection_samples=4096,max_recognition_executions=5,maximum_total_rx_bytes=16384+5*32768,
               maximum_model_spool_bytes=32768,free_bytes_before=free,feature_directory=str(feature),sdrd_pid=daemon[0],radio_before=before)
    print(json.dumps({k:v for k,v in audit.items() if k!='radio_before'}),flush=True)
    async def fake_plan(reader,writer):
        try:
            q=json.loads(await reader.readline());assert not q['observation']['health']['recognizer_available']
            response=dict(protocol_version=1,request_id=q['request_id'],session_generation=q['session_generation'],status='ok',planner=dict(provider='synthetic-action-fixture',model='s5-runner'),action=dict(kind='run_local_recognition',candidate_id='s5-live-candidate'))
            writer.write(json.dumps(response).encode()+b'\n');await writer.drain()
        finally:writer.close()
    planner_socket=feature/'scripted-plan.sock';scripted=await asyncio.start_unix_server(fake_plan,path=str(planner_socket),limit=32769)
    # Planner's production socket allowlist stays intact. These two unique
    # control sockets contain no retained data; all payload/log storage stays
    # inside the feature directory.
    control_root=Path(f'/run/user/{os.getuid()}/sdrharness')
    control_created=not control_root.exists()
    control_root.mkdir(mode=0o700,exist_ok=True)
    assert control_root.resolve()==control_root and control_root.stat().st_uid==os.getuid()
    node_socket=control_root/f'{feature.name}-planner.sock';session_socket=control_root/f'{feature.name}-session.sock'
    assert not node_socket.exists() and not session_socket.exists()
    try:
        print('starting private shared-gate Worker, Spark, Node and archive',flush=True)
        await launch('mamba',[sys.executable,SCRIPTS/'amc-worker-supervisor.py','--runtime-root',runtime,'--gpu-lease-root',gate,'--lifetime-seconds','1200','--max-batches','16','--max-restarts','4'])
        await launch('spark',[sys.executable,SCRIPTS/'spark-gpu-gateway.py','--runtime-root',feature/'spark','--gpu-lease-root',gate,'--port',gateway_port,'--backend-port',backend_port,'--api-key-file',keyfile,'--lifetime-seconds','1200','--max-requests','32'])
        webenv={**env,'SDR_WEB_LISTEN_HOST':'127.0.0.1','SDR_WEB_LISTEN_PORT':str(archive_port),'SDR_WEB_STATE_PATH':str(feature/'web-state.json'),'SDR_WEB_AGENT_BINARY':'/bin/false','SDR_WEB_REQUEST_PATH':str(feature/'unused.json'),'SDR_WEB_SESSION_SOCKET':str(feature/'unused.sock'),'SDR_WEB_SDRD_ADDRESS':'127.0.0.1:9','SDR_WEB_PROVIDER_CONFIG_PATH':str(feature/'unused-provider.json'),'SDR_WEB_RESULT_DB_PATH':str(feature/'results.sqlite3'),'SDR_WEB_CAPTURE_ROOT':str(feature/'captures'),'SDR_WEB_CORPUS_ROOT':str(feature/'corpus')}
        await launch('web',[web],webenv)
        nodeenv={**env,'SDR_PLANNER_BASE_URL':f'http://127.0.0.1:{gateway_port}/v1','SDR_PLANNER_API_KEY_FILE':str(keyfile),'SDR_PLANNER_PROVIDER_CONFIG':str(provider),'SDR_PLANNER_PROVIDER':'spark-local','SDR_PLANNER_MODEL':'spark-x2.5-4b','SDR_PLANNER_SOCKET':str(node_socket),'SDR_SESSION_SOCKET':str(session_socket),'SDR_PLANNER_MAX_TOKENS':'256','SDR_PLANNER_TIMEOUT_MS':'60000','SDR_PLANNER_WEB_SEARCH_URL':''}
        await launch('node',['node',ROOT/'raspberry-pi/sdr-agent/planner-worker/src/main.mjs'],nodeenv)
        await asyncio.gather(ready('mamba'),ready('spark'));assert archive()==[]
        for _ in range(100):
            if session_socket.exists():break
            await asyncio.sleep(.05)
        assert session_socket.exists()
        print('performing one bounded seed inspection; data remains unknown',flush=True)
        seed=dict(sweep_id=f's5-seed-{generation}',session_generation=generation,frequencies=dict(kind='centers',centers_hz=[433920000]),sample_rate_hz=2100000,rf_bandwidth_hz=1500000,gain_db=50,settle_ms=100,frame_samples=4096,aggregate_frames=1,point_timeout_ms=1000,detection_threshold_db=6.0)
        print(json.dumps({'seed_plan':seed,'maximum_bytes':16384,'stop_generation':generation,'p201_directory':f'/tmp/sdr-agent-dev/agx-sweep-{generation}-0'}),flush=True)
        used_generations.add(generation);p201_dirs.add(f'/tmp/sdr-agent-dev/agx-sweep-{generation}-0')
        seed_report,_=await native(['--mode','sweep','--sdrd','192.168.1.10:43110'],seed)
        point=seed_report['points'][0]['spectral'];await radio_check()
        candidate=dict(id='s5-live-candidate',center_hz=point['estimated_center_hz'],bandwidth_hz=point['occupied_bandwidth_hz'],peak_dbfs=point['peak_power_dbfs'],snr_db=point['measured_snr_db'],age_ms=0)
        assert candidate['bandwidth_hz']<=1500000
        def request(gen,rid=10):
            return dict(protocol_version=1,request_id=rid,session_generation=gen,instruction='Explicit bounded engineering recognition proposal; operator approval remains required.',state='idle',observation=dict(age_ms=0,health=dict(sdr_online=True,can_retune=True,can_capture_iq=True,recognizer_available=False,dropped_observations=0),candidates=[candidate.copy()]),limits=dict(min_freq_hz=70000000,max_freq_hz=6000000000,max_span_hz=5930000000,max_bandwidth_hz=2100000,max_dwell_ms=1000,max_iq_samples=4096,max_iq_bytes=32768,auto_approve_iq_bytes=32768,max_observation_age_ms=60000))
        def args(gen,rid,approval='operator'):
            return ['--mode','run-once','--sdrd','192.168.1.10:43110','--socket',planner_socket,'--approval',approval,'--engineering-recognition-root',runtime,'--recognition-archive',f'127.0.0.1:{archive_port}','--audit-log',feature/f'audit-{gen}-{rid}.jsonl','--recognizer-socket',feature/'unavailable.sock','--recognizer-admission',sup.RECEIPT]
        def dirs(gen,rid):
            used_generations.add(gen);p201_dirs.add(f'/tmp/sdr-agent-dev/agx-sweep-{gen}-0');p201_dirs.add(f'/tmp/sdr-agent-dev/agx-model-batch-{gen}-{rid}')
        for approval in ('pending','automatic'):
            outcome,err=await native(args(generation+1,10,approval),request(generation+1),expected=0 if approval=='pending' else 1)
            if approval=='pending':assert outcome['status']=='awaiting_approval' and not outcome['next_observation']['health']['recognizer_available']
            else:assert 'approval_required' in err
            assert archive()==[]
            cases.append(dict(case='one_shot_'+approval,executed=False))
        print('executing authorized one-shot fresh RX -> Worker -> archive',flush=True)
        dirs(generation+2,10)
        outcome,err=await native(args(generation+2,10),request(generation+2));(feature/'one-shot.log').write_text(err)
        assert outcome['status']=='executed' and outcome['recognition']['archive_id'] is not None,outcome
        assert outcome['recognition']['result']['experimental_batch'] is not None,outcome
        assert outcome['next_observation']['recognition']['status']=='unavailable'
        cases.append(dict(case='one_shot_operator',observation=outcome['next_observation']['recognition'],archive_id=outcome['recognition']['archive_id']))
        await radio_check()
        print('cancelling a blocked real Worker from one-shot Runner',flush=True)
        h=await ready('mamba');os.kill(h['worker_pid'],signal.SIGSTOP);gen=generation+3;dirs(gen,10)
        proc=await asyncio.create_subprocess_exec(str(binary),*map(str,args(gen,10)),env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        processes.append(proc);proc.stdin.write(json.dumps(request(gen)).encode());await proc.stdin.drain();proc.stdin.close()
        for _ in range(2500):
            if (await health())['active'] is not None:break
            if proc.returncode is not None:raise RuntimeError('runner ended before Worker cancel')
            await asyncio.sleep(.01)
        assert (await health())['active'] is not None
        proc.send_signal(signal.SIGTERM);out,err=await asyncio.wait_for(proc.communicate(),10);assert proc.returncode!=0 and b'cancelled' in err,err
        (feature/'model-cancel.log').write_bytes(err);await ready('mamba');await radio_check()
        cases.append(dict(case='one_shot_worker_cancel',late_result_discarded=True))
        print('cancelling while a real RX profile is applied',flush=True)
        gen=generation+4;dirs(gen,10)
        proc=await asyncio.create_subprocess_exec(str(binary),*map(str,args(gen,10)),env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        processes.append(proc);proc.stdin.write(json.dumps(request(gen)).encode());await proc.stdin.drain();proc.stdin.close()
        sampler_command='s5_read_index=0; while test "$s5_read_index" -lt 1500; do s5_lo=$(cat /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO_frequency); if test "$s5_lo" -ge 430000000 -a "$s5_lo" -le 437000000; then echo "$s5_lo"; exit 0; fi; s5_read_index=$((s5_read_index+1)); usleep 10000; done; exit 1'
        sampler=await asyncio.create_subprocess_exec(*rf.SSH,sampler_command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        processes.append(sampler)
        sample,diagnostic=await asyncio.wait_for(sampler.communicate(),25)
        assert sampler.returncode==0, 'did not observe owned RX profile: '+diagnostic.decode()
        applied_lo=int(sample.strip())
        proc.send_signal(signal.SIGTERM);out,err=await asyncio.wait_for(proc.communicate(),15)
        (feature/'rx-cancel.log').write_bytes(err)
        assert proc.returncode!=0 and b'cancelled' in err,err
        await radio_check();assert len(archive())==1
        cases.append(dict(case='one_shot_rx_cancel',profile_observed_hz=applied_lo,radio_restored=True))

        # Interactive host command uses the real Node session lifecycle; only
        # /approve may start RX. Its next actual Spark turn receives compact S2.
        print('checking interactive approval, real execution and Spark feedback',flush=True)
        gen=generation+5;template=feature/'console-request.json';template.write_text(json.dumps(request(gen,1)));dirs(gen,1)
        proc=await launch('console',[console,'--socket',session_socket,'--request',template,'--sdrd','192.168.1.10:43110','--session-state','off','--engineering-recognition-root',runtime,'--recognition-archive',f'127.0.0.1:{archive_port}','--recognition-audit',feature/'console-audit.jsonl','--recognizer-socket',feature/'unavailable.sock','--recognizer-admission',sup.RECEIPT],interactive=True)
        transcript=bytearray()
        async def drain():
            while chunk:=await proc.stdout.read(4096):
                transcript.extend(chunk)
                if len(transcript)>256*1024:raise RuntimeError('console output bound')
        pump=asyncio.create_task(drain())
        async def wait_text(text,timeout=30,start=0):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                if text.encode() in transcript[start:]:return
                if proc.returncode is not None:raise RuntimeError(transcript.decode()[-3000:])
                await asyncio.sleep(.02)
            raise RuntimeError('console timeout: '+text+'\n'+transcript.decode()[-3000:])
        async def send(text):proc.stdin.write((text+'\n').encode());await proc.stdin.drain()
        await wait_text('SDR Agent 已连接');await send('/recognize s5-live-candidate');await wait_text('工程识别等待人工批准')
        assert len(archive())==1
        await send('/approve');await wait_text('RecognitionObservation>',timeout=30)
        assert len(archive())==2
        # The completed recognition must start this real Spark turn itself;
        # do not hide a missing feedback trigger with another operator prompt.
        await wait_text('模型输入>',timeout=10)
        await wait_text('已验证计划',timeout=65)
        feedback_lines=[line for line in transcript.decode().splitlines() if line.startswith('模型输入> ')]
        assert len(feedback_lines)==1
        feedback=json.loads(feedback_lines[0].split('> ',1)[1])
        assert feedback['instruction'].startswith('请依据最新紧凑识别摘要')
        assert feedback['observation']['recognition']['request_id']==1
        assert feedback['observation']['recognition']['session_generation']==gen
        assert not planner_has_internal_fields(feedback)
        await asyncio.sleep(.2);await radio_check()
        print('checking interactive priority stop with blocked Worker',flush=True)
        h=await ready('mamba');os.kill(h['worker_pid'],signal.SIGSTOP)
        offset=len(transcript);await send('/recognize s5-live-candidate');await wait_text('工程识别等待人工批准',start=offset)
        dirs(gen,3)
        await send('/approve')
        for _ in range(2500):
            if (await health())['active'] is not None:break
            await asyncio.sleep(.01)
        active=(await health())['active'];assert active is not None
        p201_dirs.add(f"/tmp/sdr-agent-dev/agx-model-batch-{gen}-{active['request_id']}")
        offset=len(transcript);await send('/stop');await wait_text('会话已停止；旧计划已失效',timeout=20,start=offset)
        await ready('mamba');await radio_check();assert len(archive())==2
        cases.append(dict(case='interactive_worker_stop',old_generation=gen,renewed_generation=gen+1,late_result_discarded=True))
        await send('/quit');await asyncio.wait_for(proc.wait(),10);await pump
        (feature/'console.log').write_bytes(transcript);assert proc.returncode==0
        cases.append(dict(case='interactive_approve_execute_feedback',archive_rows=2,recognizer_available=False,automatic_feedback=True,feedback_request_id=feedback['request_id']))
        print('running fixed read-only real Spark regression',flush=True)
        regression=[]
        instructions=[('hold','只返回 hold，解释当前识别未准入。'),('stop','只返回 stop_session。'),('inspect','只建议 inspect_candidate 复查 s5-live-candidate，采样率 2100000 Hz，带宽 1500000 Hz，驻留 100 ms。不要提出执行识别。'),('capture','只建议 capture_bounded_iq，候选 s5-live-candidate，采样率 2100000 Hz，带宽 1500000 Hz，4096 个复数样本。'),('survey','只建议 survey_band，范围 433000000–434000000 Hz，步进 1000000 Hz，采样率 2100000 Hz，带宽 1500000 Hz，驻留 5 ms。'),('recognition_unavailable','识别能力为 false。不要提出 run_local_recognition，返回 hold 说明未准入。'),('synthetic_classified','这是合成 classified 摘要回归，不是实测或生产准入。只返回 hold，说明合成演示不能当作事实。'),('synthetic_rejected','这是合成 rejected 摘要回归。只返回 hold，说明拒识演示不支持真实分类结论。')]
        for index,(name,instruction) in enumerate(instructions):
            req=request(generation+10,index+1);req['instruction']=instruction
            if name=='hold':
                # Newly created synthetic error, never re-date a real RF result.
                req['observation']['recognition']=dict(schema_version=1,candidate_id='s5-live-candidate',request_id=req['request_id'],session_generation=req['session_generation'],observed_at_unix_ms=int(time.time()*1000),status='error',reason='synthetic_regression',class_=None)
                o=req['observation']['recognition'];o['class']=o.pop('class_');o.update(calibrated_confidence=None,calibration_status='unavailable',decision_references=None,identity=None,source=None,quality=None,timing=None)
            if name.startswith('synthetic_'):
                profile=json.loads(sup.PROFILE.read_text())
                req['observation']['candidates']=[dict(id='synthetic-s5-candidate',center_hz=433920000,bandwidth_hz=200000,peak_dbfs=-30.0,snr_db=10.0,age_ms=0)]
                classified=name=='synthetic_classified'
                ref=dict(id='synthetic-only',sha256='0'*64)
                o=dict(schema_version=1,candidate_id='synthetic-s5-candidate',request_id=req['request_id'],session_generation=req['session_generation'],observed_at_unix_ms=int(time.time()*1000),status='classified' if classified else 'rejected',reason=None if classified else 'synthetic_rejection',calibrated_confidence=.75 if classified else None,calibration_status='frozen',decision_references={k:ref for k in ('calibration','rejection','admission')},identity=dict(model_id=profile['model']['model_id'],checkpoint_sha256=profile['model']['model_sha256'],profile_id=profile['profile_id'],profile_sha256=hashlib.sha256(sup.PROFILE.read_bytes()).hexdigest(),preprocess_id=profile['preprocess']['preprocess_id'],preprocess_sha256=profile['preprocess']['spec_sha256'],compute='cuda_fp16_autocast',aggregation='float64_arithmetic_mean_logits_then_softmax'),source=dict(sweep_id='synthetic-s5',request_id=1,session_generation=req['session_generation'],sequence=1,capture_request_id=2,capture_sequence=2),quality=dict(window_count=4,window_agreement=1.0,clipped_samples=0,dropped_samples=0,overflow=False,healthy=True),timing=dict(capture_us=1000,worker_total_us=1000,inference_us=900))
                o['class']=dict(numeric_id=1,name=None,name_status='provisional',name_evidence=None) if classified else None
                req['observation']['recognition']=o
            result,err=await native(['--mode','plan','--socket',node_socket,'--timeout-ms','60000','--recognizer-socket',feature/'unavailable.sock','--recognizer-admission',sup.RECEIPT],req,timeout=65)
            expected_kind={'hold':'hold','stop':'stop_session','inspect':'inspect_candidate','capture':'capture_bounded_iq','survey':'survey_band','recognition_unavailable':'hold','synthetic_classified':'hold','synthetic_rejected':'hold'}[name]
            assert result['action']['kind']==expected_kind,(name,result)
            if name in ('inspect','capture'):
                assert result['action']['candidate_id']=='s5-live-candidate' and result['action']['center_hz']==candidate['center_hz']
                assert result['action']['sample_rate_hz']==2100000 and result['action']['rf_bandwidth_hz']==1500000
                assert result['action']['samples' if name=='capture' else 'dwell_ms']==(4096 if name=='capture' else 100)
            if name=='survey':
                assert all(result['action'][k]==v for k,v in dict(start_hz=433000000,stop_hz=434000000,step_hz=1000000,sample_rate_hz=2100000,rf_bandwidth_hz=1500000,dwell_ms=5).items())
            if name.startswith('synthetic_'):assert any(word in result['action']['reason'] for word in ('合成','演示','synthetic'))
            regression.append(dict(case=name,synthetic_recognition_fixture=name.startswith('synthetic_') or name=='hold',action=result['action'],approval_required=result['approval_required']))
        cases.append(dict(case='fixed_spark_regression',results=regression))
        audit['cases']=cases;audit['radio_after']=await radio_check()
        audit['archive_summary']=[dict(id=r['id'],origin=r['origin'],status=r['observation']['status'],production_result=r['production_result'],iq_retained=r['iq_retained']) for r in archive()]
        for r in archive():assert r['origin']=='engineering_rx' and not r['production_result'] and not r['iq_retained'];archive('/'+str(r['id']),'DELETE')
        assert archive()==[]
        audit['status']='pass'
    except BaseException as error:
        audit['status']='failed'
        audit['failure']=f'{type(error).__name__}: {error}'
        raise
    finally:
        scripted.close();await scripted.wait_closed()
        audit['cases']=cases
        for proc in reversed(processes):
            if proc.returncode is None:
                proc.terminate()
                try:await asyncio.wait_for(proc.wait(),12)
                except asyncio.TimeoutError:proc.kill();await proc.wait()
        if 'pump' in locals():
            await asyncio.wait_for(pump, 2)
            (feature/'console.log').write_bytes(transcript)
        # Never repair another client's radio state. Preserve failure evidence
        # even when independent restoration readback or remote cleanup fails.
        cleanup_errors=[]
        try:
            audit['radio_final']=await ssh(rf.STATE_COMMAND)
            if not rf.restored_state(before,audit['radio_final']):
                cleanup_errors.append('radio restoration mismatch')
            audit['sdrd_pid_after']=(await ssh('pidof sdrd')).strip()
            if audit['sdrd_pid_after']!=daemon[0]:cleanup_errors.append('daemon changed')
            audit['p201_directories']=sorted(p201_dirs)
            for path in p201_dirs:
                if (await ssh(f'test ! -e {path} && echo absent')).strip()!='absent':
                    cleanup_errors.append('remote directory remains: '+path)
        except Exception as error:
            cleanup_errors.append(f'{type(error).__name__}: {error}')
        for path in (node_socket,session_socket):
            if path.exists():
                import stat
                assert stat.S_ISSOCK(path.lstat().st_mode)
                path.unlink()
        audit['control_sockets_removed']=[str(node_socket),str(session_socket)]
        if control_created and not list(control_root.iterdir()):control_root.rmdir()
        audit['process_exit_codes']=[p.returncode for p in processes]
        audit.setdefault('status','failed')
        audit['worker_pids']=sorted(worker_pids)
        audit['cleanup']={'feature_processes_stopped':True,'remote_checks_passed':not cleanup_errors,'errors':cleanup_errors}
        if cleanup_errors:audit['status']='failed'
        summary_path.write_text(json.dumps(audit,indent=2)+'\n')
        assert not cleanup_errors, cleanup_errors
    print('S5 bounded RX/Runner/Planner validation passed',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--feature-directory',type=Path,required=True);a=p.parse_args();asyncio.run(validate(a.feature_directory))
