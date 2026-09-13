"""Finite one/two original-Z groups: independent RX process, RAM DSP and storage.

The same Controller owns P201, one C++ child owns the external N210/B210.
No model load. All raw bytes survive a DSP failure; no live GPU disk fallback.
"""
import argparse
import ctypes
import fcntl
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
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
from rml2018a_buffer_pool import BufferPool
from gpu_lease import GpuLease

SCRIPTS=Path(__file__).resolve().parent
CHUNK=1048576
SNR_SAMPLES=dsp.FRAME_SAMPLES*64*96
DATA=c.REPO/'local-assets/amc-eval/datasets/rml2018a/RML2018a.hdf5'
DATA_SHA='e3dd0bef66a3426959ee66a1709a8c0a95d4f8395d18aaf6f1214bdbc763bd38'


def valid_snrs(snrs):
    return (isinstance(snrs,(list,tuple)) and len(snrs) in (1,2) and
            all(type(z) is int and z in range(-20,31,2) for z in snrs) and
            (len(snrs)==1 or snrs[1]==snrs[0]-2))


def snr_name(snr):
    return f'snr-plus{snr}' if snr>=0 else f'snr-minus{-snr}'


def source_identity():
    stat=DATA.stat()
    return dict(path=str(DATA),bytes=stat.st_size,mtime_ns=stat.st_mtime_ns,
                ctime_ns=stat.st_ctime_ns,device=stat.st_dev,inode=stat.st_ino,sha256=DATA_SHA)


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def available_ram():
    return int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024


class Source:
    def __init__(self,snrs,blocks=None):
        c.require(valid_snrs(snrs),'registered SNR groups')
        self.snrs=tuple(snrs);self.blocks=blocks;self.file=h5py.File(DATA,'r')
    def __call__(self,block):
        c.require(type(block) is int and 0<=block<96*len(self.snrs),'source block budget')
        snr=self.snrs[block//96];rows=g.snr_block_rows(snr,block%96);start=int(rows[0])
        x=self.file['X'][start:start+1024];y=self.file['Y'][start:start+1024];z=self.file['Z'][start:start+1024]
        c.require(x.shape==(1024,1024,2) and np.isfinite(x).all() and (z==snr).all() and
                  np.array_equal(y,np.eye(24)[rows//106496]),'original X/Y/Z identity')
        values=x[:,:,0]+1j*x[:,:,1]
        if self.blocks is not None:
            expected=self.blocks[block]
            c.require(expected['source_start']==start and expected['snr_db']==snr and
                      expected['source_iq_sha256']==c.digest(values.tobytes()),'source block changed after TX plan')
        return values,snr
    def close(self):self.file.close()


def packet_block(values,run_id,block):
    c.require(values.shape==(1024,1024) and np.isfinite(values).all(),'TX block input')
    peaks=np.max(abs(values),axis=1);c.require((peaks>0).all(),'TX nonzero rows')
    scaled=values*(.2*np.sqrt(10)/peaks[:,None]);parts=[]
    for k in range(64):
        parts.extend((np.zeros(256),c.marker(run_id,block*64+k)*np.sqrt(10),scaled[k*16:(k+1)*16].ravel(),np.zeros(256)))
    out=np.concatenate(parts).astype('<c8');c.require(len(out)==64*dsp.FRAME_SAMPLES and abs(out).max()<=.632456,'TX frame/peak')
    return out


def validate_stage_one(root):
    p=json.loads((root/'plan.json').read_text());a=json.loads((root/'execution.json').read_text())
    c.require(p['snrs']==[30] and a['status']=='passed' and a['source_rows']==98304 and a['all_frames_synchronized']
              and a['raw_verified'] and a['worker_threads_stopped'] and a['restored'],'stage one must pass before two groups')
    c.require(a['plan_sha256']==c.file_hash(root/'plan.json'),'stage one plan identity')
    c.require(set(a['sealed_artifacts'])=={'snr-plus30/'+name for name in
        ('configuration.json','index.json','raw.sigmf-meta','processed.h5','raw.sigmf-data')},'stage one complete seal set')
    # Check sealed artifacts, not merely a copied success flag.
    for name,sha in a['sealed_artifacts'].items():c.require(c.file_hash(root/name)==sha,'stage one seal')
    return dict(root=str(root),plan_sha256=c.file_hash(root/'plan.json'),execution_sha256=c.file_hash(root/'execution.json'))


def create(root,backend,snrs,after=None):
    c.require(root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev') and not root.exists(),'fresh SNR root')
    c.require(valid_snrs(snrs),'one or two consecutive original SNRs')
    prior=validate_stage_one(after) if len(snrs)==2 and after is not None else None
    c.require(snrs==[30] or prior is not None,'expanded SNR stage requires verified first stage')
    c.require(c.file_hash(DATA)==DATA_SHA,'original source SHA')
    tx_samples=SNR_SAMPLES*len(snrs);rx_chunks=(tx_samples+2*c.RATE+CHUNK-1)//CHUNK;rx_samples=rx_chunks*CHUNK
    reserve=len(snrs)*8*1024**3
    c.require(rx_samples*4<=1024**3 and shutil.disk_usage(root.parent).free>reserve and
              available_ram()>tx_samples*8+rx_samples*4+8*1024**3,'finite disk/host RAM budget')
    root.mkdir(mode=0o700);run_id=uuid.uuid4().hex;source=Source(snrs);blocks=[]
    try:
        with (root/'tx.fc32').open('xb') as out:
            for block in range(96*len(snrs)):
                values,snr=source(block);wave=packet_block(values,run_id,block);out.write(wave.tobytes())
                blocks.append(dict(block=block,snr_db=snr,source_start=int(g.snr_block_rows(snr,block%96)[0]),
                    source_rows=1024,source_iq_sha256=c.digest(values.tobytes()),wave_sha256=c.digest(wave.tobytes())))
            out.flush();os.fsync(out.fileno())
    finally:source.close()
    names=('rml2018a-snr-stream.py','rml2018a_snr_stream.py','rml2018a_campaign.py','rml2018a_campaign_gpu.py','rml2018a_campaign_store.py',
           'rml2018a_stream_dsp.py','rml2018a_stream_frames.py','rml2018a_buffer_pool.py','rml2018a_guard_gpu.py',
           'rml2018a_guard_tone.py','rml2018a_lo_cancellation.py','rml2018a-continuous-pilot.py','gpu_lease.py')
    runtime_identity=module('snr_plan_transport',c.REPO/'devices/b210/transport.py').identity('agx')
    p=dict(schema='rml2018a-full-snr-stream-v1',run_id=run_id,generation=time.time_ns()//1000000,snrs=list(snrs),
        prior_stage=prior,blocks=blocks,source_sha256=DATA_SHA,runtime_identity=runtime_identity,tx_samples=tx_samples,tx_bytes=tx_samples*8,
        tx_seconds=tx_samples/c.RATE,tx_sha256=c.file_hash(root/'tx.fc32'),rx_samples=rx_samples,rx_chunks=rx_chunks,
        maximum_rx_bytes=rx_samples*4,background_samples=CHUNK,maximum_background_bytes=2*CHUNK*4,
        total_blocks=len(blocks),source_rows=len(blocks)*1024,maximum_arena_bytes=rx_samples*4,
        maximum_gpu_allocated_bytes=4*1024**3,maximum_host_working_bytes=tx_samples*8+rx_samples*4+4*1024**3,
        reserve_bytes=reserve,free_bytes=shutil.disk_usage(root).free,available_ram_bytes=available_ram(),
        maximum_seconds=180+600*len(snrs),rx_timeout_ms=120000,model_windows=0,guard_backend='cuda-batch',
        controller=str(backend/'cargo/debug/sdr-agent'),tx_binary=str(backend/'tx-events'),
        controller_sha256=c.file_hash(backend/'cargo/debug/sdr-agent'),tx_binary_sha256=c.file_hash(backend/'tx-events'),
        daemon_sha256=c.file_hash(backend/'sdrd-armv7/sdrd'),baseline=str(backend/'before-deploy.json'),
        software={str(SCRIPTS/n):c.file_hash(SCRIPTS/n) for n in names},
        rf=dict(center_hz=c.CENTER,rate_sps=c.RATE,bandwidth_hz=c.BW,tx_gain_db=60,rx_gain_db=50,
                tx_lo_offset_hz=250000,peak=.2*np.sqrt(10),settle_ms=500,rx_input='RX1/RX0/A_BALANCED'),
        connection='AGX USB domestic N210/B210 RF A TX/RX ->20dB+15cm SMA ->P201 RX1',
        stop='root/STOP or SIGINT/TERM -> shared stop event, exact Controller generation cancel, identified TX stop, drain/preserve raw arena',
        p201_iq_staging='none; one continuous IIO stream',
        acceptance='all original rows/frames present, no reported TX/RX loss or clipping, all tensor inputs finite, exact raw/processed seals, no worker/pool fault and full restoration; SINR invalid/cancellation-skipped rows remain recorded, not silently dropped',
        storage='one continuous SigMF raw owner; per-SNR HDF5 and global sample offsets, no raw copy across SNRs')
    c.save(root/'plan.json',p);return p


def receive_process(p,root,arena,connection,stop):
    """Dedicated Python GIL: DSP/JSON/HDF5 in the parent cannot stall RX reads."""
    child=None;received=0;announced=0;first=False;result={'status':'failed','bytes_received':0}
    target=memoryview(arena).cast('B')
    try:
        with (root/'controller.log').open('xb') as log,(root/'rx-events.jsonl').open('x') as events:
            child=subprocess.Popen([p['controller'],'--mode','stream-rx','--sdrd','192.168.1.10:43110',
                '--request',str(root/'rx-plan.json')],stdout=subprocess.PIPE,stderr=log)
            connection.send(('pid',child.pid))
            while True:
                c.require(not stop.is_set(),'RX stopped')
                header,data=read_frame(child.stdout);stamp=time.time_ns()
                c.require(header['generation']==p['generation'],'RX generation')
                events.write(json.dumps(dict(header,host_received_ns=stamp))+'\n')
                if data:
                    c.require(header['sample_offset']*4==received and received+len(data)<=p['maximum_rx_bytes'],'RX exact offsets/budget')
                    target[received:received+len(data)]=data;received+=len(data)
                    if not first:connection.send(('first',stamp));first=True
                    if received//(CHUNK*4)>announced:
                        c.require(received%(CHUNK*4)==0,'RX chunk alignment')
                        connection.send(('buffer',announced*CHUNK,CHUNK,stamp));announced+=1
                if header['event']=='rx_end':
                    result.update(end=header,finished_ns=stamp)
                    c.require(header['status']=='ok' and header['restored'] and received==p['maximum_rx_bytes'],'complete/restored RX')
                    break
            c.require(child.wait(timeout=10)==0,'Controller exit');events.flush();os.fsync(events.fileno())
            result['status']='completed'
    except BaseException as error:result['error']=repr(error);stop.set()
    finally:
        if child is not None and child.poll() is None:
            try:subprocess.run([p['controller'],'--mode','cancel','--sdrd','192.168.1.10:43110','--session-generation',str(p['generation'])],capture_output=True,timeout=5)
            except BaseException:pass
            child.terminate()
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        result.update(bytes_received=received,announced_samples=announced*CHUNK)
        c.save(root/'rx-process.json',result)
        connection.send(('end',result));connection.close();target.release()


def run(root):
    p=json.loads((root/'plan.json').read_text());groups=len(p['snrs'])
    c.require(p['schema']=='rml2018a-full-snr-stream-v1' and valid_snrs(p['snrs']) and
              p['total_blocks']==groups*96 and p['tx_samples']==groups*SNR_SAMPLES and
              p['maximum_rx_bytes']==p['rx_samples']*4<=1024**3 and p['rx_samples']==p['rx_chunks']*CHUNK and
              p['rx_chunks']==(p['tx_samples']+2*c.RATE+CHUNK-1)//CHUNK and p['source_rows']==groups*98304 and
              p['maximum_seconds']==180+600*groups and p['reserve_bytes']==groups*8*1024**3 and
              p['model_windows']==0 and p['guard_backend']=='cuda-batch','finite SNR run')
    c.require(not (root/'started.json').exists() and not (root/'STOP').exists(),'new finite attempt/no STOP')
    if p['snrs']!=[30]:c.require(validate_stage_one(Path(p['prior_stage']['root']))==p['prior_stage'],'stage one remains sealed')
    for path,sha in p['software'].items():c.require(c.file_hash(path)==sha,'software changed after plan')
    for name,key in ((p['controller'],'controller_sha256'),(p['tx_binary'],'tx_binary_sha256'),(root/'tx.fc32','tx_sha256')):
        c.require(c.file_hash(name)==p[key],'executable/TX identity')
    c.require(shutil.disk_usage(root).free>p['reserve_bytes'] and available_ram()>p['maximum_host_working_bytes']+4*1024**3,'execution space/RAM')
    base=module('snr_pilot',SCRIPTS/'rml2018a-continuous-pilot.py')
    bg=module('snr_bg',SCRIPTS/'validate-p201-termination-background.py')
    transport=module('snr_tx',c.REPO/'devices/b210/transport.py').Transport('agx',bg)
    c.require(transport.identity==p['runtime_identity'],'N210 runtime changed after plan')
    baseline=json.loads(Path(p['baseline']).read_text());bg.idle();bg.restoration(baseline['radio']);transport.preflight();base.spark_off()
    c.require(bg.ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]==p['daemon_sha256'],'deployed daemon')
    audit=dict(status='failed',plan_sha256=c.file_hash(root/'plan.json'),started_ns=time.time_ns(),
        raw_receipts=[],processed_receipts=[],worker_errors=[],gpu_input_buffers=0)
    c.save(root/'started.json',audit)
    scratch=root/'scratch';scratch.mkdir(mode=0o700);os.environ.update(TMPDIR=str(scratch),CUDA_CACHE_PATH=str(scratch/'cuda'))
    context=mp.get_context('spawn');arena=context.RawArray(ctypes.c_int16,p['rx_samples']*2)
    shared=np.frombuffer(arena,dtype='<i2').reshape(-1,2);shared.setflags(write=False)
    stop=context.Event();parent_pipe,child_pipe=context.Pipe(duplex=False)
    raw_queue=queue.Queue(256);gpu_queue=queue.Queue(256);processed=queue.Queue(2)
    pool=BufferPool(256,p['rx_samples']);gpu_ready=threading.Event();gpu_done=threading.Event();disk_done=threading.Event()
    lease=GpuLease(scratch/'gpu-gate','mamba');token=None;tx=None;receiver=None;workers=[];stores=[];accepted=0
    background=None
    def interrupt(sig,frame):raise RuntimeError(f'SNR signal {sig}')
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM):signal.signal(sig,interrupt)
    signal.alarm(p['maximum_seconds'])
    for snr in p['snrs']:
        dest=root/snr_name(snr);dest.mkdir(mode=0o700)
        config=dict(session_id=p['run_id'],source_snr_db=snr,max_raw_samples=p['rx_samples'],source_sha256=DATA_SHA,
            preprocess_id='continuous16-rolling-cuda-guard-v2-experimental',profile_sha256=c.file_hash(c.REPO/'jetson-agx/sdrharness/config/amc/rml2018a-d8-rf-v1.runtime-profile.json'),
            label_map_sha256=c.file_hash(c.REPO/'jetson-agx/sdrharness/config/amc/rml2018a-labels.server-v1.json'),
            sample_rate_hz=c.RATE,center_hz=c.CENTER,bandwidth_hz=c.BW,rx_gain_db=50,tx_gain_db=60,
            parent_plan_sha256=audit['plan_sha256'],software=p['software'],campaign_snrs=p['snrs'])
        if stores:config['raw_parent']=dict(root=str(stores[0].root),configuration_sha256=c.file_hash(stores[0].root/'configuration.json'))
        stores.append(storage.SnrStore(dest,configuration=config,raw_parent=stores[0] if stores else None))
    owner=stores[0]
    def gpu_worker():
        source=None;gpu=None
        try:
            source=Source(p['snrs'],p['blocks']);gpu=g.PayloadBatch('cuda');values,snr=source(0)
            gpu.normalize(values);gpu.quality(values,values,np.full(1024,snr))
            warm=dsp.Decoder(p['run_id'],None,gpu,guard_backend='cuda-batch',source_loader=source,total_blocks=p['total_blocks'])
            warm.samples=np.zeros(CHUNK,complex);warm.samples[256:1280]=c.marker(p['run_id'],0);warm.find_first()
            tone=np.exp(2j*np.pi*250000*np.arange(65535)/c.RATE)
            warm.guard_batch.fit([tone]*64,[dict(payload_marker_offset=256,estimated_cfo_hz=0.)]*64);del warm
            gpu.torch.cuda.synchronize();gpu.torch.cuda.reset_peak_memory_stats()
            decoder=dsp.Decoder(p['run_id'],None,gpu,guard_backend='cuda-batch',source_loader=source,total_blocks=p['total_blocks'])
            audit['gpu_ready_ns']=time.time_ns();gpu_ready.set()
            while not stop.is_set():
                try:ticket=gpu_queue.get(timeout=.1)
                except queue.Empty:continue
                if ticket is None:break
                for result in decoder.feed(ticket.iq):processed.put(result,timeout=15)
                gpu.torch.cuda.synchronize();pool.gpu_done(ticket);audit['gpu_input_buffers']+=1
            audit.update(decoded_frames=decoder.frame,decoder_peak_samples=decoder.peak_samples)
            c.require(decoder.frame==p['total_blocks']*64,'all frame pilots decoded')
        except BaseException as error:audit['worker_errors'].append('GPU: '+repr(error));stop.set();gpu_ready.set()
        finally:
            if source:source.close()
            if gpu:
                audit['gpu_peak_allocated_bytes']=gpu.torch.cuda.max_memory_allocated()
                audit['gpu_peak_reserved_bytes']=gpu.torch.cuda.max_memory_reserved()
                if audit['gpu_peak_allocated_bytes']>p['maximum_gpu_allocated_bytes']:audit['worker_errors'].append('GPU budget exceeded');stop.set()
            audit['gpu_done_ns']=time.time_ns();gpu_done.set();disk_done.wait();audit['gpu_exit_ns']=time.time_ns()
    def writer_worker():
        ended=False;pending=None
        try:
            while not (ended and gpu_done.is_set() and pending is None and processed.empty()):
                try:item=raw_queue.get(timeout=.02) if not ended else 'wait'
                except queue.Empty:item='wait'
                if item is None:ended=True
                elif not isinstance(item,str):
                    ticket=item;data=ticket.iq
                    c.require(sum(v['sample_count'] for v in owner.index['raw'])==ticket.offset,'writer raw offset')
                    receipt=owner.append_raw(data,dict(capture_id=str(p['generation']),timestamp_utc=__import__('datetime').datetime.fromtimestamp(ticket.received_ns/1e9,__import__('datetime').timezone.utc).isoformat(),
                        host_received_ns=ticket.received_ns,timestamp_reference='host_received_block',dropped_samples=0,overflow=False,
                        clipped_samples=int(np.any((data<=-2048)|(data>=2047),axis=1).sum()),background=background))
                    audit['raw_receipts'].append(dict(sequence=receipt['sequence'],finished_ns=time.time_ns(),sample_count=ticket.samples,clipped=receipt['metadata']['clipped_samples']))
                    pool.raw_done(ticket,receipt['sha256'])
                if pending is None:
                    try:pending=processed.get_nowait()
                    except queue.Empty:pass
                if pending is not None:
                    end=int(np.max(pending['sample_starts']+pending['sample_counts']))
                    if end<=sum(v['sample_count'] for v in owner.index['raw']):
                        store=stores[pending['block']//96]
                        receipt=store.append_processed(*[pending[k] for k in ('inputs','masks','sample_starts','sample_counts','quality')])
                        storage.atomic_json(root/'frames'/f"{pending['block']:03d}.json",pending['frames'])
                        audit['processed_receipts'].append(dict(global_block=pending['block'],snr_db=store.config['source_snr_db'],finished_ns=time.time_ns(),**receipt))
                        pool.processed_committed(p['rx_samples'] if pending['release_before'] is None else int(pending['release_before']));pending=None
                    elif ended and gpu_done.is_set():raise ValueError('processed interval beyond durable RX')
                if ended:time.sleep(.002)
        except BaseException as error:audit['worker_errors'].append('writer: '+repr(error));stop.set()
        finally:audit['disk_done_ns']=time.time_ns();disk_done.set()
    try:
        background=base.capture_background(root,p,name='background-before',generation_offset=-1)
        c.require(not (root/'STOP').exists(),'STOP after background')
        bg.restoration(baseline['radio']);bg.idle()
        (root/'frames').mkdir(mode=0o700)
        token=__import__('asyncio').run(lease.acquire(time.monotonic()+10,request='full-snr-dsp'))
        workers=[threading.Thread(target=gpu_worker),threading.Thread(target=writer_worker)]
        for worker in workers:worker.start()
        c.require(gpu_ready.wait(60) and not stop.is_set(),'GPU warmup/ready')
        c.require(not (root/'STOP').exists(),'STOP before device initialization')
        rxplan=dict(session_generation=p['generation'],sample_count=p['rx_samples'],max_bytes=p['maximum_rx_bytes'],timeout_ms=p['rx_timeout_ms'],storage_directory=str(owner.root),reserve_bytes=p['reserve_bytes'])
        c.save(root/'rx-plan.json',rxplan)
        with (root/'tx.log').open('xb') as txlog:
            tx=subprocess.Popen([p['tx_binary'],str(root/'tx.fc32'),str(root/'tx-events.jsonl'),'--snr-stream'],env=transport.env(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=txlog)
            c.require(json.loads(tx.stdout.readline())['event']=='ready','TX ready');audit['tx_pid']=tx.pid
            receiver=context.Process(target=receive_process,args=(p,root,arena,child_pipe,stop));receiver.start();child_pipe.close()
            last_progress=time.monotonic()
            while True:
                c.require(not stop.is_set() and not (root/'STOP').exists(),'campaign stop/worker fault')
                if parent_pipe.poll(.2):
                    event=parent_pipe.recv()
                    if event[0]=='pid':audit['rx_pid']=event[1]
                    elif event[0]=='first':
                        c.require(not (root/'STOP').exists(),'STOP before TX GO')
                        audit['first_rx_ns']=event[1];tx.stdin.write(b'GO\n');tx.stdin.flush()
                        c.require(json.loads(tx.stdout.readline())['event']=='tx_start','TX GO')
                    elif event[0]=='buffer':
                        _,offset,count,stamp=event;ticket=pool.admit(shared[offset:offset+count],stamp)
                        c.require(ticket.offset==offset,'arena ticket offset');raw_queue.put_nowait(ticket);gpu_queue.put_nowait(ticket);accepted+=count
                    elif event[0]=='end':
                        audit['rx_process']=event[1];c.require(event[1]['status']=='completed','RX process complete');break
                elif not receiver.is_alive():raise RuntimeError('RX process exited before terminal record')
                if time.monotonic()-last_progress>5:
                    print(json.dumps(dict(event='progress',rx_samples=accepted,rx_total=p['rx_samples'],processed_blocks=len(audit['processed_receipts']),total_blocks=p['total_blocks'],held_buffers=pool.snapshot()['held_buffers'])),flush=True);last_progress=time.monotonic()
            receiver.join(10);c.require(not receiver.is_alive() and receiver.exitcode==0 and tx.wait(timeout=15)==0,'TX/RX children completed')
        raw_queue.put(None,timeout=5);gpu_queue.put(None,timeout=5)
        while any(w.is_alive() for w in workers):
            c.require(not stop.is_set() and not (root/'STOP').exists(),'processing stop')
            for w in workers:w.join(.2)
            if time.monotonic()-last_progress>5:
                print(json.dumps(dict(event='drain',processed_blocks=len(audit['processed_receipts']),total_blocks=p['total_blocks'],held_buffers=pool.snapshot()['held_buffers'])),flush=True);last_progress=time.monotonic()
        c.require(not audit['worker_errors'] and accepted==p['rx_samples'],'complete data flow')
        events=[json.loads(line) for line in (root/'tx-events.jsonl').read_text().splitlines()]
        c.require(events[-1]['status']=='sent_complete' and events[-1]['accepted_samples']==p['tx_samples'] and
                  all((v['event_code']&62)==0 for v in events if v['kind']=='async'),'TX events/no reported continuity errors')
        audit['tx_summary']=events[-1]
        c.require(len(audit['processed_receipts'])==p['total_blocks'] and not any(x['clipped'] for x in audit['raw_receipts']),'all blocks/no clipping')
        c.require(pool.snapshot()['held_buffers']==0 and len(pool.snapshot()['released'])==p['rx_chunks'],'all RAM tickets released after commits')
        bg.restoration(baseline['radio']);bg.idle();transport.preflight();base.spark_off()
        audit['background_after']=base.capture_background(root,p)
        for store in stores:store.finish()
        sealed={}
        for store in stores:
            for name in ('configuration.json','index.json','raw.sigmf-meta','processed.h5'):
                path=store.root/name;sealed[str(path.relative_to(root))]=c.file_hash(path)
        sealed[str(owner.raw_path().relative_to(root))]=c.file_hash(owner.raw_path())
        audit.update(status='passed',source_rows=p['source_rows'],all_frames_synchronized=True,raw_verified=True,sealed_artifacts=sealed,finished_ns=time.time_ns())
    except BaseException as error:audit['error']=repr(error)
    finally:
        signal.alarm(0);stop.set()
        if tx is not None and tx.poll() is None:
            tx.terminate()
            try:tx.wait(timeout=10)
            except subprocess.TimeoutExpired:tx.kill();tx.wait(timeout=5)
        if receiver is not None:
            if receiver.is_alive():
                try:subprocess.run([p['controller'],'--mode','cancel','--sdrd','192.168.1.10:43110',
                    '--session-generation',str(p['generation'])],capture_output=True,timeout=5)
                except BaseException as error:audit['cancel_error']=repr(error)
            # Keep draining notifications so the child can publish its terminal
            # record and stop. All received bytes are already in the RAM arena.
            until=time.monotonic()+20
            while receiver.is_alive() and time.monotonic()<until:
                if parent_pipe.poll(.1):
                    try:parent_pipe.recv()
                    except EOFError:break
                receiver.join(.1)
            if receiver.is_alive():receiver.terminate();receiver.join(10)
        for channel in (raw_queue,gpu_queue):
            try:channel.put(None,timeout=2)
            except queue.Full:pass
        for w in workers:w.join(timeout=60)
        audit['worker_threads_stopped']=all(not w.is_alive() for w in workers)
        if audit['worker_threads_stopped']:
            if audit['status']!='passed' and (root/'rx-process.json').exists():
                received=json.loads((root/'rx-process.json').read_text())['bytes_received']//4
                durable=sum(v['sample_count'] for v in owner.index['raw'])
                if received>durable:
                    path=root/'pending-raw.ci16'
                    with path.open('xb') as out:
                        for at in range(durable,received,CHUNK):out.write(shared[at:min(at+CHUNK,received)].tobytes())
                        out.flush();os.fsync(out.fileno())
                    audit['pending_raw']=dict(path=str(path),sample_offset=durable,samples=received-durable,sha256=c.file_hash(path))
                # Missing rows remain explicit in the ledger, without inventing
                # successful processing or discarding the stored partial corpus.
                audit['incomplete_blocks']=[dict(snr_db=s.config['source_snr_db'],first_missing=len(s.index['processed']),remaining=96-len(s.index['processed'])) for s in stores]
            for store in reversed(stores):store.close()
            if token is not None:lease.release(token)
            lease.close()
        audit['memory_pool']=pool.snapshot()
        try:bg.restoration(baseline['radio']);bg.idle();transport.preflight();base.spark_off();audit['restored']=True
        except BaseException as error:audit['restoration_error']=repr(error);audit['status']='failed'
        storage.atomic_json(root/'execution.json',audit);parent_pipe.close()
    c.require(audit['status']=='passed','SNR experiment failed; retained execution and IQ')


def tx_complete(root,p):
    events=[json.loads(line) for line in (root/'tx-events.jsonl').read_text().splitlines()]
    c.require(events[-1]['status']=='sent_complete' and events[-1]['accepted_samples']==p['tx_samples'] and
              all((v['event_code']&62)==0 for v in events if v['kind']=='async'),'complete TX without reported loss')
    return events[-1]


def sealed_artifacts(root,snrs):
    paths=[root/snr_name(z)/name for z in snrs for name in
           ('configuration.json','index.json','raw.sigmf-meta','processed.h5')]
    paths.append(root/snr_name(snrs[0])/'raw.sigmf-data')
    return {str(path.relative_to(root)):c.file_hash(path) for path in paths}


def completed(root,expected_snrs):
    """Read-only completion receipt; verify exact artifacts before skipping RF."""
    p=json.loads((root/'plan.json').read_text())
    receipt=root/'recovery.json' if (root/'recovery.json').exists() else root/'execution.json'
    a=json.loads(receipt.read_text())
    c.require(p['snrs']==list(expected_snrs) and valid_snrs(p['snrs']) and p['source_sha256']==DATA_SHA and
              a['status']=='passed' and a['source_rows']==len(expected_snrs)*98304 and
              a['all_frames_synchronized'] and a['raw_verified'] and a['worker_threads_stopped'] and a['restored'],
              'sealed complete SNR group required')
    c.require(a['plan_sha256']==c.file_hash(root/'plan.json'),'completed plan pin')
    c.require(a['sealed_artifacts']==sealed_artifacts(root,expected_snrs),'completed artifact seals')
    for snr in expected_snrs:
        directory=root/snr_name(snr);config=json.loads((directory/'configuration.json').read_text())
        index=json.loads((directory/'index.json').read_text())
        c.require(config['session_id']==p['run_id'] and config['source_snr_db']==snr and
                  config['source_sha256']==DATA_SHA and config['parent_plan_sha256']==a['plan_sha256'] and
                  index['complete'] and len(index['processed'])==96,'completed source/session coverage')
    return dict(root=str(root),snrs=list(expected_snrs),source_rows=a['source_rows'],
                plan_sha256=a['plan_sha256'],receipt=str(receipt),receipt_sha256=c.file_hash(receipt),
                sealed_artifacts=a['sealed_artifacts'])


def recovery_preflight(root):
    p=json.loads((root/'plan.json').read_text());a=json.loads((root/'execution.json').read_text())
    c.require(a['plan_sha256']==c.file_hash(root/'plan.json') and a['status']=='failed' and
              a['worker_threads_stopped'] and a.get('restored'),'stopped/restored failed attempt required')
    rx=json.loads((root/'rx-process.json').read_text())
    c.require(rx['status']=='completed' and rx['bytes_received']==p['maximum_rx_bytes'] and
              rx['end']['restored'],'recovery requires entire finite RX; partial capture retained')
    for path,sha in p['software'].items():c.require(c.file_hash(path)==sha,'recovery software pin')
    tx_complete(root,p)
    c.require(not any(v['clipped'] for v in a['raw_receipts']),'recovery no clipped IQ')
    c.require(not (root/'recovery.json').exists(),'recovery already published')
    return p,a


def compare_committed(store,result):
    """Replayed prefix validates positions/inputs/status; never overwrites it."""
    with h5py.File(store.root/'processed.h5','r') as f:
        b=f['blocks'][f"{result['block']%96:03d}"]
        c.require(np.array_equal(b['raw_sample_start'][:],result['sample_starts']) and
                  np.array_equal(b['raw_sample_count'][:],result['sample_counts']),'recovery prefix sample mapping')
        for tag in storage.TAGS:
            c.require(np.array_equal(b['valid/'+tag][:],result['masks'][tag]) and
                      np.allclose(b['inputs/'+tag][:],result['inputs'][tag],rtol=0,atol=1e-4,equal_nan=True),
                      'recovery prefix input equivalence')
        for old,new in zip(map(json.loads,b['quality_json'].asstr()[:]),result['quality']):
            for tag in ('raw','guard'):
                for key in ('rx_sinr_status','rx_sinr_reason'):
                    c.require(old[tag][key]==new[tag][key],'recovery prefix quality status')
                if old[tag]['rx_sinr_status']=='estimated':
                    c.require(abs(old[tag]['rx_sinr_db']-new[tag]['rx_sinr_db'])<=.001,'recovery prefix SINR equivalence')


def recover(root):
    """RF is stopped: load preserved IQ into RAM and append missing DSP only."""
    p,failed=recovery_preflight(root)
    c.require(available_ram()>p['maximum_rx_bytes']+8*1024**3 and
              shutil.disk_usage(root).free>p['reserve_bytes'],'recovery RAM/disk budget')
    lock=os.open(root/'recovery.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    journal=root/'recovery-started.json'
    if not journal.exists():storage.atomic_json(journal,dict(plan_sha256=c.file_hash(root/'plan.json'),
        failed_execution_sha256=c.file_hash(root/'execution.json'),new_tx_samples=0,new_rx_samples=0,
        started_ns=time.time_ns(),maximum_seconds=1800))
    c.require(json.loads(journal.read_text())['failed_execution_sha256']==c.file_hash(root/'execution.json'),
              'original failed execution retained')
    stores=[];source=None;lease=None;token=None
    audit=dict(status='failed',plan_sha256=c.file_hash(root/'plan.json'),started_ns=time.time_ns(),
               new_tx_samples=0,new_rx_samples=0,committed_prefix_blocks=0,appended_blocks=0)
    until=time.monotonic()+1800
    try:
        for snr in p['snrs']:
            stores.append(storage.SnrStore(root/snr_name(snr),raw_parent=stores[0] if stores else None))
        owner=stores[0];durable=sum(v['sample_count'] for v in owner.index['raw'])
        if durable<p['rx_samples']:
            pending=failed['pending_raw'];path=Path(pending['path'])
            c.require(path==root/'pending-raw.ci16' and pending['sample_offset']==durable and
                      pending['samples']==p['rx_samples']-durable and c.file_hash(path)==pending['sha256'],'preserved RX tail identity')
            metadata=owner.index['raw'][-1]['metadata']
            with path.open('rb') as f:
                while data:=f.read(CHUNK*4):
                    iq=np.frombuffer(data,dtype='<i2').reshape(-1,2)
                    c.require(not np.any((iq<=-2048)|(iq>=2047)),'recovered raw clipping')
                    owner.append_raw(iq,dict(metadata,recovery_parent_sha256=pending['sha256']))
        c.require(owner.raw_path().stat().st_size==p['maximum_rx_bytes'],'full durable RX')
        iq=np.fromfile(owner.raw_path(),dtype='<i2').reshape(-1,2);iq.setflags(write=False)
        source=Source(p['snrs'],p['blocks']);lease=GpuLease(root/'scratch/recovery-gpu','mamba')
        token=__import__('asyncio').run(lease.acquire(time.monotonic()+10,request='stopped-rf-cache-recovery'))
        gpu=g.PayloadBatch('cuda');decoder=dsp.Decoder(p['run_id'],None,gpu,guard_backend='cuda-batch',
            source_loader=source,total_blocks=p['total_blocks'])
        for at in range(0,len(iq),CHUNK):
            c.require(time.monotonic()<until and not (root/'RECOVERY_STOP').exists(),'recovery stop/deadline')
            for result in decoder.feed(iq[at:at+CHUNK]):
                store=stores[result['block']//96]
                if result['block']%96<len(store.index['processed']):
                    compare_committed(store,result);audit['committed_prefix_blocks']+=1
                else:
                    store.append_processed(*[result[k] for k in ('inputs','masks','sample_starts','sample_counts','quality')])
                    storage.atomic_json(root/'frames'/f"{result['block']:03d}.json",result['frames']);audit['appended_blocks']+=1
                if result['block']%8==7:print(json.dumps(dict(event='recovery',blocks=result['block']+1,total=p['total_blocks'])),flush=True)
        gpu.torch.cuda.synchronize()
        c.require(decoder.frame==p['total_blocks']*64,'recovery all pilots')
        for store in stores:
            if not store.index['complete']:store.finish()
        audit.update(status='passed',source_rows=p['source_rows'],all_frames_synchronized=True,raw_verified=True,
            sealed_artifacts=sealed_artifacts(root,p['snrs']),worker_threads_stopped=True,restored=True,
            restoration_basis='original finite RX and failed execution verified stopped/restored; recovery invokes no hardware',
            finished_ns=time.time_ns())
        storage.atomic_json(root/'recovery.json',audit)
    finally:
        for store in reversed(stores):store.close()
        if source:source.close()
        if token is not None:lease.release(token)
        if lease:lease.close()
        os.close(lock)
    return audit


ALL_SNRS=list(range(30,-21,-2))
PAIRS=[ALL_SNRS[i:i+2] for i in range(0,26,2)]


def full_plan(root,backend,first,two):
    """Campaign ledger for13 finite sessions; first sealed pair is imported."""
    c.require(root.is_absolute() and root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev') and
              not root.exists(),'fresh full campaign root')
    initial=validate_stage_one(first);imported=completed(two,[30,28])
    c.require(c.file_hash(DATA)==DATA_SHA,'full campaign original source hash')
    reserve=224*1024**3
    c.require(shutil.disk_usage(root.parent).free>reserve,'full campaign disk reserve')
    root.mkdir(mode=0o700);(root/'entries').mkdir(mode=0o700)
    identity=json.loads((two/'plan.json').read_text())
    groups=[dict(index=i,snrs=pair,attempts=[str(root.parent/(root.name+f'-g{i:02d}-a{a}'))
                for a in range(2 if i==1 else 1)]) for i,pair in enumerate(PAIRS)]
    # One additional bounded attempt is reserved solely for joint-stop validation.
    groups[0]['attempts']=[]
    p=dict(schema='rml2018a-snr-campaign-ledger-v1',source=source_identity(),snrs=ALL_SNRS,groups=groups,
        imported=imported,initial=initial,backend=str(backend),software_sha256=c.file_hash(Path(__file__)),
        cli_sha256=c.file_hash(SCRIPTS/'rml2018a-snr-stream.py'),rf=identity['rf'],connection=identity['connection'],
        maximum_new_attempts=13,maximum_new_tx_samples=13*2*SNR_SAMPLES,
        maximum_new_rx_bytes=13*(225443840+2*CHUNK)*4,maximum_new_tx_seconds=13*2*SNR_SAMPLES/c.RATE,
        reserve_bytes=reserve,maximum_wall_seconds=21600,maximum_pair_seconds=1380,
        maximum_retained_bytes=208*1024**3,source_rows=2555904,automatic_retry=False,
        model_windows=0,recognizer_available=False,created_ns=time.time_ns(),free_bytes=shutil.disk_usage(root).free,
        stop='campaign STOP or SIGINT/SIGTERM forwards STOP to current exact child; completed pairs remain sealed',
        recovery='completed pair skipped; full RX can resume DSP from preserved RAM-loaded IQ without TX; partial RX requires explicit retry and consumes its reserved attempt',
        model_gate='all26 unique source groups verified, raw/processed seals and restoration required before inference eligibility')
    storage.atomic_json(root/'ledger-plan.json',p)
    storage.atomic_json(root/'entries/00.complete.json',imported)
    return p


def full_load(root):
    p=json.loads((root/'ledger-plan.json').read_text())
    c.require(p['schema']=='rml2018a-snr-campaign-ledger-v1' and p['snrs']==ALL_SNRS and
              p['source']==source_identity() and p['source_rows']==2555904 and p['maximum_new_attempts']==13 and
              p['maximum_new_tx_samples']==13*2*SNR_SAMPLES and p['maximum_new_rx_bytes']==13*(225443840+2*CHUNK)*4 and
              p['maximum_wall_seconds']==21600 and p['reserve_bytes']==224*1024**3 and
              p['maximum_retained_bytes']==208*1024**3 and not p['automatic_retry'] and p['model_windows']==0 and
              p['software_sha256']==c.file_hash(Path(__file__)) and
              p['cli_sha256']==c.file_hash(SCRIPTS/'rml2018a-snr-stream.py'),'full campaign pinned scope')
    c.require(len(p['groups'])==13,'all13 groups')
    for i,group in enumerate(p['groups']):
        expected=[] if i==0 else [str(root.parent/(root.name+f'-g{i:02d}-a{a}')) for a in range(2 if i==1 else 1)]
        c.require(group==dict(index=i,snrs=PAIRS[i],attempts=expected),'exact nonoverlapping attempt roots')
    return p


def full_status(root,deep=True):
    p=full_load(root);rows=0;groups=[]
    for group in p['groups']:
        receipt=root/'entries'/f"{group['index']:02d}.complete.json"
        if receipt.exists():
            value=json.loads(receipt.read_text())
            c.require(value['snrs']==group['snrs'] and value['source_rows']==196608 and
                      value['root'] in ([p['imported']['root']] if group['index']==0 else group['attempts']),
                      'completion receipt registered source range')
            if deep:c.require(value==completed(Path(value['root']),group['snrs']),'completion receipt changed')
            rows+=value['source_rows'];groups.append(dict(index=group['index'],snrs=group['snrs'],status='complete',root=value['root']))
        else:groups.append(dict(index=group['index'],snrs=group['snrs'],status='pending'))
    return dict(complete=rows==2555904,source_rows=rows,total_source_rows=2555904,
                completed_snr_groups=rows//98304,groups=groups,model_loaded=False)


def full_run(root,retry=False,stop_after=None):
    """Serial pairs with one owner; receipts survive restarts, state is derived."""
    p=full_load(root)
    lock=os.open(root/'owner.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    active=None;child=None;stopping=False;previous={};started=time.monotonic()
    def stop(sig,frame):
        nonlocal stopping
        stopping=True
        if active is not None:(active/'STOP').touch()
    for sig in (signal.SIGINT,signal.SIGTERM):previous[sig]=signal.signal(sig,stop)
    try:
        c.require(not (root/'STOP').exists(),'campaign STOP exists')
        status=full_status(root)
        for group in p['groups']:
            i=group['index'];receipt=root/'entries'/f'{i:02d}.complete.json'
            if receipt.exists():
                if stop_after is not None and i>=stop_after:break
                continue
            c.require(not stopping and not (root/'STOP').exists() and time.monotonic()-started<p['maximum_wall_seconds'],'full campaign stop/deadline')
            paths=[Path(x) for x in group['attempts']];active=None
            # Reconcile a child completed before the controller wrote its receipt.
            for path in paths:
                if (path/'execution.json').exists():
                    try:value=completed(path,group['snrs'])
                    except (ValueError,KeyError,FileNotFoundError):continue
                    storage.atomic_json(receipt,value);break
            if receipt.exists():
                if stop_after is not None and i>=stop_after:break
                continue
            for path in paths:
                if not path.exists() or not (path/'started.json').exists():active=path;break
                if not retry:raise ValueError('interrupted/failed group retained; use recover for complete RX, or explicit --retry for partial RX')
            c.require(active is not None,'registered attempts exhausted; no implicit retransmit')
            if not (active/'plan.json').exists():
                c.require(not active.exists(),'incomplete plan retained; inspect before retry')
                create(active,Path(p['backend']),group['snrs'],Path(p['initial']['root']))
            plan=json.loads((active/'plan.json').read_text())
            c.require(plan['snrs']==group['snrs'] and plan['rf']==p['rf'] and plan['connection']==p['connection'],'child exact RF/source scope')
            used=sum(f.stat().st_size for path in [root,*[Path(v) for q in p['groups'] for v in q['attempts']]] if path.exists() for f in path.rglob('*') if f.is_file())
            c.require(used<p['maximum_retained_bytes'] and shutil.disk_usage(root).free>plan['reserve_bytes'],'global retained/disk budget')
            c.require(not stopping and not (root/'STOP').exists(),'STOP before child')
            storage.atomic_json(root/'state.json',dict(active=str(active),group=i,status='running',updated_ns=time.time_ns()))
            with (active/'campaign-run.log').open('ab') as log:
                child=subprocess.Popen([sys.executable,'-B',str(SCRIPTS/'rml2018a-snr-stream.py'),'run','--root',str(active)],stdout=log,stderr=subprocess.STDOUT)
                deadline=time.monotonic()+plan['maximum_seconds']+180;sent_stop=None
                while child.poll() is None:
                    if stopping or (root/'STOP').exists() or time.monotonic()>deadline:
                        (active/'STOP').touch()
                        if sent_stop is None:sent_stop=time.monotonic()
                        if time.monotonic()-sent_stop>180:
                            child.terminate();raise RuntimeError('child stop deadline exceeded; inspect exact hardware owner')
                    time.sleep(.2)
                c.require(child.returncode==0,'child failed/stopped; raw and processed data retained')
            value=completed(active,group['snrs']);storage.atomic_json(receipt,value)
            status=full_status(root,deep=False);storage.atomic_json(root/'state.json',status)
            print(json.dumps(dict(event='pair_sealed',snrs=group['snrs'],source_rows=status['source_rows'],total=2555904)),flush=True)
            # TX waveform is regenerable; IQ/HDF5 and failed evidence stay intact.
            wave=active/'tx.fc32'
            if wave.exists():
                c.require(c.file_hash(wave)==plan['tx_sha256'],'TX cleanup hash')
                storage.atomic_json(active/'tx-staging-cleanup.json',dict(path=str(wave),bytes=wave.stat().st_size,sha256=plan['tx_sha256']))
                wave.unlink();storage.sync_directory(active)
            active=None;child=None
            if stop_after is not None and i==stop_after:break
        status=full_status(root)
        storage.atomic_json(root/'state.json',status)
        if status['complete']:
            storage.atomic_json(root/'acquisition-complete.json',dict(**status,ledger_plan_sha256=c.file_hash(root/'ledger-plan.json'),
                completed_ns=time.time_ns(),inference_eligible=True,source_overlap_policy='one imported+30/+28 pair; exactly one sealed pair per remaining source group'))
        return status
    except BaseException as error:
        storage.atomic_json(root/'state.json',dict(status='stopped_or_failed',error=repr(error),
            active=str(active) if active else None,updated_ns=time.time_ns(),model_loaded=False))
        raise
    finally:
        if child is not None and child.poll() is None:
            if active is not None:(active/'STOP').touch()
            try:child.wait(timeout=180)
            except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=20)
        for sig,handler in previous.items():signal.signal(sig,handler)
        os.close(lock)
