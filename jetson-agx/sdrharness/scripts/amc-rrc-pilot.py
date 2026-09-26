#!/usr/bin/env python3
"""Finite four-dataset RRC pilot via the existing Controller and B210 helper.

CPU consumes immutable RAM blocks while RX runs. No model import or inference.
Each dataset is a separate bounded session with original ADC stored once.
"""
import argparse
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
import numpy as np
import amc_rrc_transport as r
import amc_dataset_contract as native
import rml2018a_campaign_store as storage
from rml2018a_stream_frames import read_frame

c=r.c
REPO=c.REPO
SCRIPTS=Path(__file__).resolve().parent
CHUNK=1048576
BACKEND=Path('/var/tmp/sdrharness-dev/rml2018a-full-snr-20260913')
CONTROLLER_SHA='104d6d38f790c4c9f7afc293547dc2e69dcc933ffae2fcdd67f2722addecb765'
TX_SHA='b609f5cf741fc2780f275364151ae504dccc583cfe5f97961d37551549d8cae3'
DAEMON_SHA='dae7c32fd63fc4542fd5eadce37c272160eba92193accdb983919ad1a4fce74e'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def helpers():
    old=module('rrc_old_pilot',SCRIPTS/'rml2018a-continuous-pilot.py')
    bg=module('rrc_background',SCRIPTS/'validate-p201-termination-background.py')
    device=module('rrc_device',REPO/'devices/b210/transport.py').Transport('agx',bg)
    return old,bg,device


def load(entry):
    x,identity=native.read_selected(entry['source_path'],entry['contract']['dataset_id'],
        np.array(entry['contract']['source_rows']),entry['contract']['class_names'],entry['contract']['source_sha256'])
    c.require(identity==entry['contract'],'selected source metadata')
    return x


def prepare(root, selection, dataset):
    c.require(root.is_absolute() and root.resolve()==root and not root.exists() and
              root.is_relative_to(REPO/'local-assets/amc-eval/rf'),'fresh application-owned RF root')
    old,bg,device=helpers();old.spark_off();bg.idle();device.preflight()
    c.require(c.file_hash(BACKEND/'cargo/debug/sdr-agent')==CONTROLLER_SHA and
              c.file_hash(BACKEND/'tx-events')==TX_SHA,'existing verified executables')
    c.require(bg.ssh('sha256sum /sd/sdr-agent/current/sdrd').split()[0]==DAEMON_SHA,'verified deployed daemon')
    c.require(len(bg.ssh('pidof sdrd').split())==1,'one daemon')
    entry=json.loads(selection.read_text())['source_selection'][dataset]
    c.require(set(entry['contract']['source_snr_db'])=={18.},'uniform sourceZ18')
    c.require(c.file_hash(Path(entry['source_path']))==entry['contract']['source_sha256'],'full original source SHA')
    x=load(entry);run_id=root.name+'-'+dataset
    tx,info=r.transmit(x,run_id,frame_payload_samples=2048)
    c.require(info['tx_samples']+CHUNK<12*CHUNK,'finite TX fits RX with startup margin')
    free=shutil.disk_usage(root.parent).free;c.require(free>1024**3,'one GiB reserve')
    daemon_config_sha=bg.ssh('sha256sum /sd/sdr-agent/current/sdrd.conf').split()[0]
    baseline=bg.ssh(bg.STATE)
    root.mkdir(mode=0o700);(root/'tx.fc32').write_bytes(tx.tobytes())
    software={str(p):c.file_hash(p) for p in [Path(__file__),SCRIPTS/'amc_rrc_transport.py',SCRIPTS/'amc_dataset_contract.py',
       SCRIPTS/'rml2018a_campaign_store.py',SCRIPTS/'rml2018a_stream_dsp.py',SCRIPTS/'rml2018a_stream_frames.py']}
    p=dict(schema='amc-uniform-rrc-finite-pilot-v1',run_id=run_id,dataset=dataset,generation=time.time_ns()//1000000,
      source=entry,selected_iq_sha256=c.digest(x.tobytes()),transport=info,
      controller=str(BACKEND/'cargo/debug/sdr-agent'),tx_binary=str(BACKEND/'tx-events'),
      controller_sha256=CONTROLLER_SHA,tx_binary_sha256=TX_SHA,daemon_sha256=DAEMON_SHA,daemon_config_sha256=daemon_config_sha,software=software,
      rx_samples=12*CHUNK,maximum_rx_bytes=12*CHUNK*4,background_each_samples=CHUNK,
      total_adc_bytes=14*CHUNK*4,raw_guard_payload_bytes=len(x)*x.shape[1]*16,
      reserve_bytes=1024**3,free_bytes=free,deadline_seconds=180,cpu_pending_blocks=16,
      maximum_cpu_adc_buffer_bytes=12*CHUNK*16,model_windows_during_capture=0,
      rf=dict(center_hz=2455000000,rate_sps=2100000,bandwidth_hz=1500000,lo_offset_hz=250000,
              tx_gain_db=60,rx_gain_db=50,rx_port='RX1/RX0/A_BALANCED',settle_ms=500),
      connection='B210 A TX/RX ->20dB attenuator +15cm coax ->P201 RX1',
      p201_temporary_path=None,stop='STOP file, SIGINT/TERM or180s deadline: stop exact TX, cancel exact RX generation, verify restoration',
      baseline_radio=baseline,selection_path=str(selection),selection_sha256=c.file_hash(selection))
    c.save(root/'plan.json',p)
    print(json.dumps(dict(plan=str(root/'plan.json'),dataset=dataset,rows=len(x),tx_seconds=len(tx)/c.RATE,
                         max_adc_bytes=p['total_adc_bytes'],free_bytes=free)),flush=True)


def run(root):
    p=json.loads((root/'plan.json').read_text());old,bg,device=helpers()
    c.require(p['schema']=='amc-uniform-rrc-finite-pilot-v1' and p['rx_samples']==12*CHUNK and
              p['transport']['contract']==r.contract(2048) and not (root/'execution.json').exists() and
              not (root/'STOP').exists(),'one finite attempt')
    for path,sha in p['software'].items():c.require(c.file_hash(path)==sha,'frozen pilot software')
    c.require(c.file_hash(p['controller'])==CONTROLLER_SHA and c.file_hash(p['tx_binary'])==TX_SHA and
              c.file_hash(root/'tx.fc32')==p['transport']['tx_sha256'],'frozen executables/TX')
    old.spark_off();bg.idle();device.preflight();bg.restoration(p['baseline_radio'])
    c.require(bg.ssh('sha256sum /sd/sdr-agent/current/sdrd.conf').split()[0]==p['daemon_config_sha256'],'frozen daemon configuration')
    c.require(shutil.disk_usage(root).free>p['reserve_bytes'],'RF reserve')
    corpus=root/'corpus';corpus.mkdir(mode=0o700)
    cfg=dict(native_source=p['source']['contract'],sample_transport=r.contract(2048),session_id=p['run_id'],
      max_raw_samples=p['rx_samples'],source_sha256=p['source']['contract']['source_sha256'],
      preprocess_id=r.contract(2048)['method'],profile_sha256=c.digest(json.dumps(p['rf'],sort_keys=True).encode()),
      label_map_sha256=native.label_hash(p['source']['contract']['class_names']),sample_rate_hz=c.RATE,
      center_hz=c.CENTER,bandwidth_hz=c.BW,rx_gain_db=50,tx_gain_db=60,parent_plan_sha256=c.file_hash(root/'plan.json'),software=p['software'])
    store=storage.SnrStore(corpus,configuration=cfg)
    decoder=r.Decoder(p['run_id'],cfg['native_source']['window_samples'],len(cfg['native_source']['source_rows']),frame_payload_samples=2048)
    work=queue.Queue(16);faults=[];stop=threading.Event();worker=None;tx=rx=None;received=0;buf=bytearray()
    audit=dict(status='failed',started_ns=time.time_ns(),model_windows=0,restored=False)
    def cpu():
        try:
            while True:
                item=work.get()
                if item is None:break
                decoder.feed(item)
            decoder.feed(np.empty(0,complex),final=True)
        except BaseException as e:faults.append(repr(e));stop.set()
    def abort(sig,frame):raise RuntimeError('finite pilot interrupted '+str(sig))
    previous={s:signal.signal(s,abort) for s in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM)}
    signal.alarm(180)
    def stop_watch():
        while not stop.wait(.1):
            if (root/'STOP').exists():os.kill(os.getpid(),signal.SIGINT);return
    watcher=threading.Thread(target=stop_watch,daemon=True);watcher.start()
    def persist(data,stamp):
        iq=np.frombuffer(data,dtype='<i2').reshape(-1,2)
        store.append_raw(iq,dict(capture_id=str(p['generation']),timestamp_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
            timestamp_reference='host_received_block',host_received_ns=stamp,dropped_samples=0,overflow=False,
            clipped_samples=int(np.any((iq<=-2048)|(iq>=2047),axis=1).sum()),background=audit['background_before']))
        work.put_nowait(iq)
    try:
        audit['background_before']=old.capture_background(root,p,name='background-before',generation_offset=-1)
        bg.restoration(p['baseline_radio']);device.preflight()
        worker=threading.Thread(target=cpu);worker.start()
        with (root/'tx.log').open('xb') as txlog,(root/'controller.log').open('xb') as rxlog,(root/'rx-events.jsonl').open('x') as events:
            tx=subprocess.Popen([p['tx_binary'],str(root/'tx.fc32'),str(root/'tx-events.jsonl'),'--stream-pilot'],
                env=device.env(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=txlog)
            c.require(json.loads(tx.stdout.readline())['event']=='ready','TX ready without GO')
            rxplan=dict(session_generation=p['generation'],sample_count=p['rx_samples'],max_bytes=p['maximum_rx_bytes'],timeout_ms=15000,
                        storage_directory=str(corpus),reserve_bytes=p['reserve_bytes'])
            c.save(root/'rx-plan.json',rxplan)
            rx=subprocess.Popen([p['controller'],'--mode','stream-rx','--sdrd','192.168.1.10:43110','--request',str(root/'rx-plan.json')],
                                stdout=subprocess.PIPE,stderr=rxlog)
            audit.update(tx_pid=tx.pid,rx_pid=rx.pid);go=False
            while True:
                c.require(not stop.is_set() and not faults,'CPU/STOP failure')
                header,data=read_frame(rx.stdout);stamp=time.time_ns();events.write(json.dumps(dict(header,host_received_ns=stamp))+'\n')
                c.require(header['generation']==p['generation'],'RX generation')
                if data:
                    c.require(header['sample_offset']*4==received and received+len(data)<=p['maximum_rx_bytes'],'bounded continuous RX offsets')
                    received+=len(data)
                    if not go:
                        remaining=p['rx_samples']-received//4
                        c.require(remaining>p['transport']['tx_samples']+CHUNK,'TX fits remaining actual RX')
                        audit['first_rx_ns']=stamp;tx.stdin.write(b'GO\n');tx.stdin.flush();audit['go_ns']=time.time_ns()
                        c.require(json.loads(tx.stdout.readline())['event']=='tx_start','GO acknowledgment');go=True
                    buf.extend(data)
                    if len(buf)==CHUNK*4:persist(bytes(buf),stamp);buf.clear()
                if header['event']=='rx_end':
                    audit['rx_end']=header;c.require(header['status']=='ok' and header['restored'] and
                      received==p['maximum_rx_bytes'] and not buf,'complete restored RX');break
            c.require(rx.wait(timeout=10)==0 and tx.wait(timeout=10)==0,'finite children exit')
        work.put(None,timeout=2);worker.join(timeout=70)
        c.require(not worker.is_alive() and not faults,'CPU completed')
        result=decoder.result()
        for begin in range(0,decoder.rows,1024):
            end=min(begin+1024,decoder.rows)
            store.append_processed({k:v[begin:end] for k,v in result['inputs'].items()},
                {k:v[begin:end] for k,v in result['masks'].items()},result['sample_starts'][begin:end],
                result['sample_counts'][begin:end],result['quality'][begin:end])
        store.finish();c.save(root/'frames.json',result['frames'])
        txevents=[json.loads(s) for s in (root/'tx-events.jsonl').read_text().splitlines()]
        c.require(txevents[-1]['kind']=='summary' and txevents[-1]['accepted_samples']==p['transport']['tx_samples'] and
           all((e['event_code']&62)==0 for e in txevents if e['kind']=='async'),'TX accepted count/async gate')
        bg.restoration(p['baseline_radio']);bg.idle();device.preflight()
        audit['background_after']=old.capture_background(root,p)
        audit.update(status='completed',synchronized_rows=int(result['masks']['raw'].sum()),expected_rows=decoder.rows,
            guard_applied_frames=sum(f.get('guard',{}).get('status')=='applied' for f in result['frames']),expected_frames=decoder.total_frames,
            missing_frames=result['missing_frames'],tx_async_events=[e for e in txevents if e['kind']=='async'])
    except BaseException as e:audit['error']=repr(e);raise
    finally:
        signal.alarm(0);stop.set()
        if tx is not None and tx.poll() is None:
            tx.terminate()
            try:tx.wait(timeout=5)
            except subprocess.TimeoutExpired:tx.kill();tx.wait(timeout=5)
        if rx is not None and rx.poll() is None:
            subprocess.run([p['controller'],'--mode','cancel','--sdrd','192.168.1.10:43110','--session-generation',str(p['generation'])],capture_output=True,timeout=5)
            try:rx.wait(timeout=10)
            except subprocess.TimeoutExpired:rx.terminate();rx.wait(timeout=5)
        if worker is not None and worker.is_alive():
            try:work.put(None,timeout=2)
            except queue.Full:pass
            worker.join(timeout=70)
        if buf:
            (root/'uncommitted-tail.ci16').write_bytes(buf)
            audit['uncommitted_tail_bytes']=len(buf)
        audit.update(rx_bytes=received,finished_ns=time.time_ns(),cpu_faults=faults,cpu_stopped=worker is None or not worker.is_alive())
        store.close()
        try:bg.restoration(p['baseline_radio']);bg.idle();device.preflight();audit['restored']=True
        except BaseException as e:audit['restoration_error']=repr(e)
        c.save(root/'execution.json',audit)
        for sig,handler in previous.items():signal.signal(sig,handler)
    print(json.dumps(audit,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['plan','run']);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--selection',type=Path);parser.add_argument('--dataset',choices=list(native.SPECS))
    args=parser.parse_args()
    if args.command=='plan':prepare(args.root,args.selection,args.dataset)
    else:run(args.root)
