#!/usr/bin/env python3
"""Two1024-row one-pass TX/RX, shared immutable buffers, GPU DSP and disk.

Experimental finite campaign entry. Controller alone accesses P201. No model
load or full-SNR execution. A failed worker stops this pilot and retains IQ.
"""
import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import threading
import time
import uuid

import h5py
import numpy as np

import rml2018a_campaign as c
import rml2018a_campaign_gpu as g
import rml2018a_campaign_store as storage
import rml2018a_stream_dsp as dsp
from rml2018a_stream_frames import read_frame
from gpu_lease import GpuLease
from rml2018a_buffer_pool import BufferPool

ROOT = c.REPO
DATA = ROOT/'local-assets/amc-eval/datasets/rml2018a/RML2018a.hdf5'
DATA_SHA = 'e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38'
SCRIPTS = Path(__file__).resolve().parent
CHUNK = 1048576
RX_SAMPLES = 12*CHUNK


def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def spark_off():
    state=subprocess.check_output(['systemctl','show','spark-x25.service','-p','ActiveState','-p','MainPID'],text=True,timeout=5)
    c.require(set(state.splitlines())=={'ActiveState=inactive','MainPID=0'},'Spark must remain stopped')


def source():
    rows=g.snr_rows(30,0,2048)
    with h5py.File(DATA,'r') as f:
        x=f['X'][int(rows[0]):int(rows[-1])+1];y=f['Y'][int(rows[0]):int(rows[-1])+1];z=f['Z'][int(rows[0]):int(rows[-1])+1]
    c.require((z==30).all() and np.array_equal(y,np.eye(24)[rows//106496]),'source Y/Z row identity')
    return x[:,:,0]+1j*x[:,:,1]


def create(root, backend):
    c.require(root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev') and not root.exists(),'fresh pilot root')
    c.require(c.file_hash(DATA)==DATA_SHA,'source SHA')
    root.mkdir(mode=0o700); run_id=uuid.uuid4().hex
    values=source();waveform,scales=dsp.packet(values,run_id)
    with (root/'tx.fc32').open('xb') as f:f.write(waveform.tobytes());f.flush();os.fsync(f.fileno())
    software={str(SCRIPTS/n):c.file_hash(SCRIPTS/n) for n in (Path(__file__).name,'rml2018a_campaign.py',
        'rml2018a_campaign_gpu.py','rml2018a_campaign_store.py','rml2018a_stream_dsp.py','rml2018a_stream_frames.py',
        'rml2018a_guard_tone.py','rml2018a_lo_cancellation.py','rml2018a_buffer_pool.py')}
    p=dict(schema='rml2018a-continuous-pilot-v1',run_id=run_id,generation=time.time_ns()//1000000,
        controller=str(backend/'cargo/debug/sdr-agent'),tx_binary=str(backend/'tx-events'),
        controller_sha256=c.file_hash(backend/'cargo/debug/sdr-agent'),tx_binary_sha256=c.file_hash(backend/'tx-events'),
        daemon_sha256=c.file_hash(backend/'sdrd-armv7/sdrd'),software=software,
        source_sha256=DATA_SHA,source_rows=g.snr_rows(30,0,2048).tolist(),source_snr_db=30,
        source_iq_sha256=c.digest(values.tobytes()),scales_sha256=c.digest(scales.tobytes()),
        tx_samples=len(waveform),maximum_tx_seconds=len(waveform)/c.RATE,tx_bytes=waveform.nbytes,tx_sha256=c.file_hash(root/'tx.fc32'),
        rx_samples=RX_SAMPLES,maximum_rx_bytes=RX_SAMPLES*4,maximum_raw_after_background_bytes=CHUNK*4,
        maximum_pending_buffers=16,maximum_pool_bytes=16*CHUNK*4,gpu_input='RAM only; no disk reload',
        maximum_pending_processed_blocks=2,maximum_rows=2048,model_windows=0,
        gpu_warmup='one synthetic1048576-sample pilot search plus1024 source normalization/quality windows; no radio/model',
        deadline_seconds=180,reserve_bytes=512*1024**2,maximum_gpu_allocated_bytes=4*1024**3,free_bytes=shutil.disk_usage(root).free,
        rf=dict(center_hz=c.CENTER,rate_sps=c.RATE,bandwidth_hz=c.BW,tx_gain_db=60,rx_gain_db=50,
                tx_lo_offset_hz=250000,peak=.2*np.sqrt(10),settle_ms=500,rx_input='RX1/RX0/A_BALANCED'),
        connection='B210 RF A TX/RX ->20dB attenuator+15cm SMA ->P201 RX1',
        stop='STOP file or parent SIGINT/TERM/180s alarm -> identified TX stop and Controller generation cancel; verify full restoration',
        p201_staging='none: stream buffers only',semantics='Engineering pipeline pilot; source rows may overlap prior pilots; no accuracy/admission claim',
        background_before=str(backend/'rx-complete'),baseline=str(backend/'before-deploy.json'))
    c.require(p['free_bytes']>p['reserve_bytes'],'pilot disk reserve');c.save(root/'plan.json',p)
    return p


def background_record(directory):
    raw=np.fromfile(directory/'raw.sigmf-data',dtype='<i2').reshape(-1,2).astype(np.int64)
    audit=json.loads((directory/'audit.json').read_text())
    return dict(status='measured',tx_state='off',reference_plane='raw_adc',unit='adc_counts_squared',
        power_adc_squared=float(np.mean(np.sum(raw*raw,axis=1))),frequency_hz=c.CENTER,sample_rate_hz=c.RATE,
        bandwidth_hz=c.BW,rx_gain_db=50,sample_count=len(raw),capture_id=str(audit['generation']),
        timestamp_utc=__import__('datetime').datetime.fromtimestamp(audit['started_ns']/1e9,__import__('datetime').timezone.utc).isoformat(),
        timestamp_reference='host_command_start_not_ADC_time',raw_sha256=c.file_hash(directory/'raw.sigmf-data'),
        raw_path=str(directory/'raw.sigmf-data'))


def capture_background(root,p):
    dest=root/'background-after';dest.mkdir(mode=0o700);generation=p['generation']+1
    plan=dict(session_generation=generation,sample_count=CHUNK,max_bytes=CHUNK*4,timeout_ms=10000,
        storage_directory=str(dest),reserve_bytes=p['reserve_bytes'])
    c.save(dest/'plan.json',plan);audit=dict(generation=generation,started_ns=time.time_ns(),bytes_received=0)
    child=None
    try:
        with (dest/'controller.log').open('xb') as log, (dest/'raw.sigmf-data').open('xb') as raw:
            child=subprocess.Popen([p['controller'],'--mode','stream-rx','--sdrd','192.168.1.10:43110',
                '--request',str(dest/'plan.json')],stdout=subprocess.PIPE,stderr=log)
            while True:
                header,data=read_frame(child.stdout);c.require(header['generation']==generation,'background generation')
                if data:
                    c.require(header['sample_offset']*4==audit['bytes_received'],'background offsets')
                    raw.write(data);audit['bytes_received']+=len(data)
                    c.require(audit['bytes_received']<=CHUNK*4,'background byte bound')
                if header['event']=='rx_end':audit['end']=header;break
            raw.flush();os.fsync(raw.fileno())
            c.require(child.wait(timeout=10)==0 and audit['bytes_received']==CHUNK*4 and audit['end']['restored'],'background complete/restored')
        audit.update(status='completed',finished_ns=time.time_ns());c.save(dest/'audit.json',audit)
        c.save(dest/'raw.sigmf-meta',{'global':{'core:datatype':'ci16_le','core:version':'1.2.5','core:sample_rate':c.RATE,
            'core:description':'Post-transmission background; host command timestamp in audit.json'},
            'captures':[{'core:sample_start':0,'core:frequency':c.CENTER}],'annotations':[]})
        return background_record(dest)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        c.save(dest/'audit.json',audit)


def run(root):
    p=json.loads((root/'plan.json').read_text())
    c.require(not (root/'started.json').exists() and not (root/'STOP').exists(),'new pilot attempt/no STOP')
    c.require(p['schema']=='rml2018a-continuous-pilot-v1' and p['rx_samples']==RX_SAMPLES and
              p['maximum_rx_bytes']==RX_SAMPLES*4 and p['maximum_rows']==2048 and p['model_windows']==0,
              'finite stream pilot')
    for name,sha in p['software'].items():c.require(c.file_hash(name)==sha,'pilot software changed')
    c.require(c.file_hash(p['controller'])==p['controller_sha256'] and c.file_hash(p['tx_binary'])==p['tx_binary_sha256'] and
              c.file_hash(root/'tx.fc32')==p['tx_sha256'],'pilot executables/payload')
    values=source();c.require(c.digest(values.tobytes())==p['source_iq_sha256'],'source before TX')
    expected,scales=dsp.packet(values,p['run_id'])
    c.require(expected.nbytes==p['tx_bytes'] and len(expected)==p['tx_samples'] and c.digest(expected.tobytes())==p['tx_sha256'] and
              p['maximum_tx_seconds']==len(expected)/c.RATE,'exact finite TX payload')
    del expected
    bg=module('continuous_bg',SCRIPTS/'validate-p201-termination-background.py')
    transport=module('continuous_transport',ROOT/'devices/b210/transport.py').Transport('agx',bg)
    baseline=json.loads(Path(p['baseline']).read_text());bg.idle();bg.restoration(baseline['radio']);transport.preflight();spark_off()
    c.require(bg.ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]==p['daemon_sha256'],'deployed stream daemon')
    c.require(shutil.disk_usage(root).free>p['reserve_bytes'],'pilot free space')
    background=background_record(Path(p['background_before']))
    audit=dict(status='failed',started_ns=time.time_ns(),raw_receipts=[],gpu_blocks=[],processed_receipts=[],worker_errors=[])
    c.save(root/'started.json',audit)
    scratch=root/'scratch';scratch.mkdir(mode=0o700)
    os.environ.update(TMPDIR=str(scratch),CUDA_CACHE_PATH=str(scratch/'cuda'),XDG_CACHE_HOME=str(scratch))
    lease=GpuLease(scratch/'gpu-gate','mamba'); token=None
    tx=None;rx=None;workers=[];stop=threading.Event();raw_queue=queue.Queue(16);gpu_queue=queue.Queue(16);processed=queue.Queue(2)
    pool=BufferPool(16,RX_SAMPLES)
    failed_raw=[];buf=bytearray();received=0
    gpu_ready=threading.Event();gpu_done=threading.Event();disk_done=threading.Event();corpus=root/'snr-plus30';corpus.mkdir(mode=0o700)
    config=dict(session_id=p['run_id'],source_snr_db=30,max_raw_samples=RX_SAMPLES,source_sha256=DATA_SHA,
        preprocess_id='continuous16-pilot-track-guard-gpu-v1-experimental',
        profile_sha256=c.file_hash(ROOT/'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json'),
        label_map_sha256=c.file_hash(ROOT/'jetson-agx/sdrharness/config/amc/rml2018a-labels.server-v1.json'),
        sample_rate_hz=c.RATE,center_hz=c.CENTER,bandwidth_hz=c.BW,rx_gain_db=50,tx_gain_db=60,
        parent_plan_sha256=c.file_hash(root/'plan.json'),software=p['software'])
    store=storage.SnrStore(corpus,configuration=config)
    def abort(sig,frame):raise RuntimeError(f'pilot signal {sig}')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,abort)
    signal.alarm(180)
    def gpu_worker():
        gpu=None
        try:
            warmup_started=time.time_ns();gpu=g.PayloadBatch('cuda')
            gpu.normalize(values[:1024]);gpu.quality(values[:1024],values[:1024],np.full(1024,30.))
            warmup=dsp.Decoder(p['run_id'],values,gpu);warmup.samples=np.zeros(CHUNK,np.complex128)
            warmup.samples[256:1280]=c.marker(p['run_id'],0);warmup.find_first();del warmup
            audit['gpu_warmup_seconds']=(time.time_ns()-warmup_started)/1e9
            c.require(gpu.torch.cuda.max_memory_allocated()<=p['maximum_gpu_allocated_bytes'],'GPU warmup allocation budget')
            gpu.torch.cuda.reset_peak_memory_stats()
            decoder=dsp.Decoder(p['run_id'],values,gpu)
            gpu.torch.cuda.synchronize();audit['gpu_ready_ns']=time.time_ns();gpu_ready.set()
            while not stop.is_set():
                try:item=gpu_queue.get(timeout=.1)
                except queue.Empty:continue
                if item is None:break
                ticket=item
                audit.setdefault('first_gpu_input_ns',time.time_ns())
                audit.setdefault('gpu_buffer_sources',[]).append('ram')
                for result in decoder.feed(ticket.iq):
                    audit['gpu_blocks'].append(dict(block=result['block'],finished_ns=result['finished_ns']))
                    processed.put(result,timeout=5)
                gpu.torch.cuda.synchronize()
                pool.gpu_done(ticket)
            c.require(decoder.frame==128,'not all128 frame pilots decoded')
        except BaseException as error:
            audit['worker_errors'].append('GPU: '+repr(error));stop.set();gpu_ready.set()
        finally:
            if gpu is not None:
                audit['gpu_peak_allocated_bytes']=gpu.torch.cuda.max_memory_allocated()
                audit['gpu_peak_reserved_bytes']=gpu.torch.cuda.max_memory_reserved()
                if audit['gpu_peak_allocated_bytes']>p['maximum_gpu_allocated_bytes']:
                    audit['worker_errors'].append('GPU allocation budget exceeded');stop.set()
            audit['gpu_processing_done_ns']=time.time_ns();gpu_done.set()
            # Keep the initialized CUDA worker/context alive through disk drain.
            disk_done.wait()
            audit['gpu_worker_exit_ns']=time.time_ns()
    def writer_worker():
        ended=False;pending=None;inflight=None
        try:
            while not (ended and gpu_done.is_set() and processed.empty() and pending is None):
                if ended:time.sleep(.002)
                try:item=raw_queue.get(timeout=.02) if not ended else 'wait'
                except queue.Empty:item='wait'
                if item is None:ended=True
                elif not isinstance(item,str):
                    ticket=item;inflight=ticket;data=ticket.iq;received_ns=ticket.received_ns;offset=ticket.offset;start=time.time_ns()
                    c.require(sum(r['sample_count'] for r in store.index['raw'])==offset,'raw writer offset')
                    receipt=store.append_raw(data,dict(capture_id=str(p['generation']),timestamp_utc=__import__('datetime').datetime.fromtimestamp(received_ns/1e9,__import__('datetime').timezone.utc).isoformat(),
                        timestamp_reference='host_received_block',host_received_ns=received_ns,dropped_samples=0,overflow=False,
                        clipped_samples=int(np.any((data<=-2048)|(data>=2047),axis=1).sum()),background=background))
                    audit['raw_receipts'].append(dict(sequence=receipt['sequence'],started_ns=start,finished_ns=time.time_ns(),bytes=data.nbytes))
                    pool.raw_done(ticket,receipt['sha256'])
                    inflight=None
                # A GPU result may be ready before its referenced raw interval is durable.
                if pending is None:
                    try:pending=processed.get_nowait()
                    except queue.Empty:pass
                if pending is not None:
                    result=pending
                    end=int(np.max(result['sample_starts']+result['sample_counts']))
                    durable=sum(r['sample_count'] for r in store.index['raw'])
                    if end<=durable:
                        start=time.time_ns()
                        receipt=store.append_processed(*[result[k] for k in ('inputs','masks','sample_starts','sample_counts','quality')])
                        c.save(root/f"frames-{result['block']:03d}.json",result['frames'])
                        audit['processed_receipts'].append(dict(receipt,started_ns=start,finished_ns=time.time_ns()))
                        pool.processed_committed(RX_SAMPLES if result['release_before'] is None else int(result['release_before']))
                        pending=None
                    elif ended and gpu_done.is_set():raise ValueError('processed reference beyond received raw')
            c.require(len(store.index['processed'])==2,'two GPU blocks stored')
        except BaseException as error:
            if inflight is not None:failed_raw.append((inflight.iq,inflight.received_ns,inflight.offset,inflight))
            audit['worker_errors'].append('writer: '+repr(error));stop.set()
        finally:
            audit['disk_worker_done_ns']=time.time_ns();disk_done.set()
    try:
        token=asyncio.run(lease.acquire(time.monotonic()+10,request='continuous-pilot-gpu'))
        workers=[threading.Thread(target=gpu_worker),threading.Thread(target=writer_worker)]
        for worker in workers:worker.start()
        c.require(gpu_ready.wait(45) and not stop.is_set(),'GPU startup')
        with (root/'tx.log').open('xb') as txlog, (root/'controller.log').open('xb') as rxlog, (root/'rx-events.jsonl').open('x') as events:
            tx=subprocess.Popen([p['tx_binary'],str(root/'tx.fc32'),str(root/'tx-events.jsonl'),'--stream-pilot'],
                env=transport.env(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=txlog)
            c.require(json.loads(tx.stdout.readline())['event']=='ready','TX initialized')
            rxplan=dict(session_generation=p['generation'],sample_count=RX_SAMPLES,max_bytes=RX_SAMPLES*4,timeout_ms=15000,
                storage_directory=str(corpus),reserve_bytes=p['reserve_bytes'])
            c.save(root/'rx-plan.json',rxplan)
            rx=subprocess.Popen([p['controller'],'--mode','stream-rx','--sdrd','192.168.1.10:43110','--request',str(root/'rx-plan.json')],
                stdout=subprocess.PIPE,stderr=rxlog)
            audit.update(tx_pid=tx.pid,rx_pid=rx.pid);go=False
            while True:
                c.require(not stop.is_set() and not (root/'STOP').exists(),'pilot stopped/worker fault')
                header,data=read_frame(rx.stdout);now=time.time_ns();events.write(json.dumps(dict(header,host_received_ns=now))+'\n')
                c.require(header['generation']==p['generation'],'RX association')
                if data:
                    c.require(header['sample_offset']*4==received,'RX contiguous offsets');received+=len(data)
                    if not go:
                        audit['first_rx_chunk_ns']=now;tx.stdin.write(b'GO\n');tx.stdin.flush();audit['tx_go_ns']=time.time_ns()
                        c.require(json.loads(tx.stdout.readline())['event']=='tx_start','TX GO ack');go=True
                    buf.extend(data)
                    if len(buf)==CHUNK*4:
                        shared=np.frombuffer(bytes(buf),dtype='<i2').reshape(-1,2);c.require(not shared.flags.writeable,'immutable shared buffer')
                        offset=(received-len(buf))//4
                        try:
                            ticket=pool.admit(shared,now);c.require(ticket.offset==offset,'pool/RX offset')
                            raw_queue.put_nowait(ticket)
                        except queue.Full:
                            failed_raw.append((shared,now,offset,ticket));buf.clear();raise RuntimeError('raw writer queue full; stop without blocking RX')
                        buf.clear()
                        gpu_queue.put_nowait(ticket)
                if header['event']=='rx_end':
                    audit.update(rx_end=header,rx_finished_ns=now,rx_bytes=received)
                    c.require(header['status']=='ok' and header['restored'] and received==RX_SAMPLES*4 and not buf,'complete RX');break
            c.require(rx.wait(timeout=10)==0 and tx.wait(timeout=10)==0,'finite TX/RX exits')
        raw_queue.put(None,timeout=5);gpu_queue.put(None,timeout=5)
        for worker in workers:worker.join(timeout=90)
        c.require(all(not w.is_alive() for w in workers) and not audit['worker_errors'],'completed worker queues')
        tx_events=[json.loads(line) for line in (root/'tx-events.jsonl').read_text().splitlines()]
        audit['tx_async_events']=[v for v in tx_events if v['kind']=='async']
        c.require(tx_events[-1]['kind']=='summary' and tx_events[-1]['accepted_samples']==p['tx_samples'] and
                  all((v['event_code']&62)==0 for v in audit['tx_async_events']),'TX sample total/no reported continuity errors')
        store.verify();c.require(sum(r['sample_count'] for r in store.index['raw'])==RX_SAMPLES,'all raw bytes committed')
        audit['memory_pool']=pool.snapshot()
        c.require(audit['memory_pool']['held_buffers']==0 and len(audit['memory_pool']['released'])==12 and
                  audit['memory_pool']['peak_bytes']<=p['maximum_pool_bytes'],'all buffers released after processing/disk commits')
        bg.restoration(baseline['radio']);bg.idle();transport.preflight();spark_off()
        audit['background_after']=capture_background(root,p)
        bg.restoration(baseline['radio']);bg.idle()
        audit.update(status='completed',restored=True,finished_ns=time.time_ns(),source_rows=2048,model_windows=0,
            gpu_processing_started_during_rx=audit['first_gpu_input_ns']<audit['rx_finished_ns'],
            gpu_blocks_finished_during_rx=sum(v['finished_ns']<audit['rx_finished_ns'] for v in audit['gpu_blocks']))
    except BaseException as error:
        audit['error']=repr(error);raise
    finally:
        signal.alarm(0);stop.set()
        if rx is not None and rx.poll() is None:
            subprocess.run([p['controller'],'--mode','cancel','--sdrd','192.168.1.10:43110','--session-generation',str(p['generation'])],capture_output=True,timeout=5)
        for child in (tx,rx):
            if child is not None and child.poll() is None:
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        if buf:
            failed_raw.append((np.frombuffer(bytes(buf),dtype='<i2').reshape(-1,2),time.time_ns(),(received-len(buf))//4,None))
            buf.clear()
        for channel in (raw_queue,gpu_queue):
            try:channel.put(None,timeout=2)
            except queue.Full:pass
        for worker in workers:worker.join(timeout=30)
        if all(not worker.is_alive() for worker in workers):
            while not raw_queue.empty():
                item=raw_queue.get_nowait()
                if item is not None:failed_raw.append((item.iq,item.received_ns,item.offset,item))
            audit['pending_raw_buffers']=[]
            for i,(data,stamp,offset,_) in enumerate(failed_raw):
                if data is None:continue  # Already committed and released.
                path=root/f'pending-raw-{i:03d}.ci16'
                with path.open('xb') as pending_file:
                    pending_file.write(data.tobytes());pending_file.flush();os.fsync(pending_file.fileno())
                audit['pending_raw_buffers'].append(dict(path=str(path),sample_offset=offset,bytes=data.nbytes,host_received_ns=stamp,sha256=c.file_hash(path)))
            if audit['status']!='completed':
                try:
                    while len(store.index['processed'])<2:
                        block=len(store.index['processed']);inputs={tag:np.full((1024,2,1024),np.nan,dtype='<f4') for tag in storage.TAGS}
                        inputs['source']=g.PayloadBatch('cpu').normalize(values[block*1024:(block+1)*1024])
                        masks={tag:np.full(1024,tag=='source',dtype=bool) for tag in inputs}
                        quality=[dict(raw=c.receive_quality('sync_failed'),sync=dict(status='sync_failed',pipeline_error=audit.get('error','worker failed'))) for _ in range(1024)]
                        store.append_processed(inputs,masks,np.full(1024,-1,dtype='<i8'),np.zeros(1024,dtype='<i8'),quality)
                except BaseException as error:audit['failure_record_error']=repr(error)
            store.close()
            if token is not None:lease.release(token)
            lease.close()
        audit['worker_threads_stopped']=all(not w.is_alive() for w in workers)
        audit['memory_pool']=pool.snapshot()
        try:
            bg.restoration(baseline['radio']);bg.idle();transport.preflight();audit['restored']=True
        except BaseException as error:audit['restoration_error']=repr(error)
        c.save(root/'execution.json',audit)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['plan','run'])
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--backend',type=Path)
    args=parser.parse_args()
    if args.command=='plan':create(args.root,args.backend)
    else:run(args.root)
