#!/usr/bin/env python3
"""Sequential complete seed42 validation RX; durable dataset barrier, no models."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import h5py
import numpy as np
import amc_dataset_contract as native
import amc_rrc_transport as r
import rml2018a_campaign_store as store

c=r.c
SCRIPTS=Path(__file__).resolve().parent
ORDER=('rml2016a','rml2016b','rml2018a','hisarmod2019')
COUNTS=(33000,180000,383385,117000)
CONFIG_SHA='070401363f1624013dd1442aba737c68824ed8561f6dbd26980f7181c3a517a0'

def pilot():
    spec=importlib.util.spec_from_file_location('campaign_pilot',SCRIPTS/'amc-rrc-pilot.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def fingerprint(path):
    path=Path(path).resolve();s=path.stat()
    return dict(path=str(path),device=s.st_dev,inode=s.st_ino,bytes=s.st_size,mtime_ns=s.st_mtime_ns,ctime_ns=s.st_ctime_ns)

def durable(path,value):
    store.atomic_json(path,value)

def software():
    return {str(SCRIPTS/n):c.file_hash(SCRIPTS/n) for n in
      ('amc_validation_campaign.py','amc-rrc-pilot.py','amc_rrc_transport.py','amc_dataset_contract.py','rml2018a_campaign_store.py','rml2018a_stream_dsp.py','rml2018a_stream_frames.py','rml2018a-continuous-pilot.py','validate-p201-termination-background.py')}

def prepare(root,selection):
    c.require(root.is_absolute() and root.resolve()==root and not root.exists() and root.is_relative_to(c.REPO/'local-assets/amc-eval/rf'),'fresh campaign root')
    original=json.loads(selection.read_text())['source_selection'];datasets=[]
    root.mkdir(mode=0o700)
    for name,count in zip(ORDER,COUNTS):
        entry=original[name];path=Path(entry['source_path']);identity=fingerprint(path)
        c.require(c.file_hash(path)==entry['contract']['source_sha256'],'source SHA')
        c.require(fingerprint(path)==identity,'source changed during hash')
        split=entry['splits'][0];c.require(split['seed']==42 and c.file_hash(split['path'])==split['sha256'],'frozen seed42 split')
        with np.load(split['path'],allow_pickle=False) as f:
            val=f['val'];train=f['train'];test=f['test']
            c.require(len(val)==count and len(np.unique(val))==count and not np.intersect1d(val,train).size and not np.intersect1d(val,test).size,'exact isolated validation')
        folder=root/name;folder.mkdir()
        np.save(folder/'validation-rows.npy',val.astype('<i8'),allow_pickle=False)
        with (folder/'validation-rows.npy').open('rb') as f:os.fsync(f.fileno())
        length=native.SPECS[name][1];batch_rows=1048576//length
        batches=(count+batch_rows-1)//batch_rows
        datasets.append(dict(dataset=name,rows=count,window_samples=length,batch_rows=batch_rows,batches=batches,
            split=split,validation_rows_sha256=c.file_hash(folder/'validation-rows.npy'),source_path=str(path),source_fingerprint=identity,
            source_sha256=entry['contract']['source_sha256'],class_names=entry['contract']['class_names']))
    batches=sum(x['batches'] for x in datasets)
    # All batches retain ADC, raw/guard and metadata; at most one TX file needed.
    maximum_retained_bytes=batches*160*1024**2
    free=shutil.disk_usage(root).free;c.require(free>maximum_retained_bytes+10*1024**3,'whole campaign space reserve')
    plan=dict(schema='amc-full-validation-sequential-v1',datasets=datasets,source_selection=str(selection),source_selection_sha256=c.file_hash(selection),
      transport=r.contract(2048),seed=42,total_rows=sum(COUNTS),total_batches=batches,maximum_adc_bytes=batches*14*1048576*4,
      maximum_retained_bytes=maximum_retained_bytes,initial_free_bytes=free,minimum_free_bytes=10*1024**3,
      maximum_batch_tx_samples=512*14336+125,maximum_batch_tx_seconds=(512*14336+125)/2100000,
      deadline_seconds=24*3600,batch_deadline_seconds=300,software=software(),daemon_config_sha256=CONFIG_SHA,
      dataset_order=list(ORDER),next_dataset_gate='all previous rows received, raw/processed sealed, file SHA and fsync verified, dataset-complete.json committed',
      no_model_during_capture=True,stop=str(root/'STOP'),scope='all original seed42 val rows/all source Z; no train/test, no old predictions; each dataset finishes disk commit before next begins')
    durable(root/'campaign.json',plan)
    print(json.dumps({k:plan[k] for k in ('total_rows','total_batches','maximum_adc_bytes','maximum_retained_bytes','initial_free_bytes')}),flush=True)

def read_plan(root):
    p=json.loads((root/'campaign.json').read_text());c.require(p['schema']=='amc-full-validation-sequential-v1' and p['dataset_order']==list(ORDER),'campaign identity')
    for path,sha in p['software'].items():c.require(c.file_hash(path)==sha,'frozen campaign software')
    for d in p['datasets']:
        c.require(fingerprint(d['source_path'])==d['source_fingerprint'],'unchanged source fingerprint')
        c.require(c.file_hash(root/d['dataset']/'validation-rows.npy')==d['validation_rows_sha256'],'validation index SHA')
    return p

def barrier(root,plan,index):
    for d in plan['datasets'][:index]:
        path=root/d['dataset']/'dataset-complete.json'
        c.require(path.exists(),'previous dataset not committed')
        value=json.loads(path.read_text());c.require(value['rows']==d['rows'] and value['validation_rows_sha256']==d['validation_rows_sha256'] and value['status']=='complete','previous dataset seal mismatch')
        c.require(c.file_hash(root/d['dataset']/'raw-guard.h5')==value['virtual_dataset_sha256'],'previous dataset index changed')

def seal_batch(root,expected):
    e=json.loads((root/'execution.json').read_text())
    c.require(e['status']=='completed' and e['restored'] and e['cpu_stopped'] and e['synchronized_rows']==len(expected) and not e['missing_frames'],'complete synchronized restored batch')
    with store.SnrStore(root/'corpus') as s:
        s.verify();c.require(s.index['complete'],'sealed store')
    with h5py.File(root/'corpus/processed.h5') as f:
        rows=np.concatenate([b['source_row'][:] for b in f['blocks'].values()])
        c.require(np.array_equal(rows,expected),'exact validation row order')
        for b in f['blocks'].values():
            c.require(b['valid/raw'][:].all() and b['valid/guard'][:].all(),'no missing row hidden')
    frames=json.loads((root/'frames.json').read_text());offset=np.diff([f['marker_rf_sample'] for f in frames])
    c.require(np.all(abs(offset-14336)<=4),'pilot continuity gate')
    files=[]
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.name not in ('batch-complete.json','tx.fc32','writer.lock'):
            with path.open('rb') as f:os.fsync(f.fileno())
            files.append(dict(path=str(path.relative_to(root)),bytes=path.stat().st_size,sha256=c.file_hash(path)))
    value=dict(status='complete',rows=len(expected),source_rows_sha256=c.digest(np.asarray(expected,dtype='<i8').tobytes()),files=files,
        guard_applied_frames=e['guard_applied_frames'],expected_frames=e['expected_frames'],finished_ns=time.time_ns())
    durable(root/'batch-complete.json',value)
    # Deterministically regenerable TX waveform is temporary, ADC is retained.
    tx=root/'tx.fc32'
    if tx.exists():tx.unlink();store.sync_directory(root)
    return value

def verify_batch(root,expected):
    value=json.loads((root/'batch-complete.json').read_text())
    c.require(value['rows']==len(expected) and value['source_rows_sha256']==c.digest(np.asarray(expected,dtype='<i8').tobytes()),'sealed rows')
    for f in value['files']:
        path=root/f['path'];c.require(path.stat().st_size==f['bytes'] and c.file_hash(path)==f['sha256'],'sealed file changed')
    return value

def seal_dataset(folder,d,rows):
    receipts=[];block_sources=[];offset=0
    for i,start in enumerate(range(0,len(rows),d['batch_rows'])):
        root=folder/f'batch-{i:05d}';expected=rows[start:start+d['batch_rows']]
        receipts.append(verify_batch(root,expected))
        with h5py.File(root/'corpus/processed.h5') as f:
            for key,b in f['blocks'].items():
                count=len(b['source_row']);block_sources.append((root/'corpus/processed.h5',key,offset,count));offset+=count
    c.require(offset==d['rows'],'whole validation count')
    temp=folder/'raw-guard.h5.tmp'
    fields={'source_row':('<i8',()),'class_id':('<i8',()),'source_snr_db':('<f8',()),'raw_sample_start':('<i8',()),'raw_sample_count':('<i8',()),
            'inputs/raw':('<f4',(2,d['window_samples'])),'inputs/guard':('<f4',(2,d['window_samples'])),'valid/raw':('?',()),'valid/guard':('?',())}
    with h5py.File(temp,'w',libver='latest') as f:
        f.create_dataset('validation_rank',data=np.arange(d['rows'],dtype='<i8'))
        for field,(dtype,tail) in fields.items():
            layout=h5py.VirtualLayout(shape=(d['rows'],*tail),dtype=dtype)
            for path,key,start,count in block_sources:
                source=h5py.VirtualSource(str(path.relative_to(folder)),'blocks/'+key+'/'+field,shape=(count,*tail))
                layout[start:start+count]=source
            f.create_virtual_dataset(field,layout)
        f.attrs['seed']=42;f.attrs['dataset']=d['dataset'];f.attrs['raw_iq']='batch-*/corpus/raw.sigmf-data; no duplicate IQ'
    with temp.open('rb') as f:os.fsync(f.fileno())
    temp.replace(folder/'raw-guard.h5');store.sync_directory(folder)
    with h5py.File(folder/'raw-guard.h5') as f:
        c.require(np.array_equal(f['source_row'][:],rows) and f['valid/raw'][:].all() and f['valid/guard'][:].all(),'virtual dataset readback')
    value=dict(status='complete',dataset=d['dataset'],rows=len(rows),validation_rows_sha256=d['validation_rows_sha256'],
       virtual_dataset_sha256=c.file_hash(folder/'raw-guard.h5'),batches=len(receipts),completed_ns=time.time_ns(),
       raw_samples=len(receipts)*12*1048576,total_adc_bytes=len(receipts)*14*1048576*4,
       batch_receipts=[dict(batch=i,sha256=c.file_hash(folder/f'batch-{i:05d}'/'batch-complete.json')) for i in range(len(receipts))])
    durable(folder/'dataset-complete.json',value);return value

def run(root):
    lock=(root/'campaign.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    p=read_plan(root);m=pilot();old,bg,device=m.helpers();old.spark_off();bg.idle();device.preflight()
    c.require(bg.ssh('sha256sum /sd/sdr-agent/current/sdrd.conf').split()[0]==CONFIG_SHA,'validated65536 buffer')
    # Recheck actual source contents once at each campaign start, not per batch.
    for d in p['datasets']:c.require(c.file_hash(d['source_path'])==d['source_sha256'],'campaign source SHA')
    stop=False;active=None;child=None;started=time.monotonic();status=dict(status='running',completed_datasets=[],completed_rows=0)
    def cancel(sig,frame):
        nonlocal stop
        stop=True
        if active is not None:(active/'STOP').touch()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,cancel)
    try:
      for index,d in enumerate(p['datasets']):
        barrier(root,p,index);folder=root/d['dataset'];rows=np.load(folder/'validation-rows.npy',allow_pickle=False)
        if (folder/'dataset-complete.json').exists():
            seal_dataset(folder,d,rows);status['completed_datasets'].append(d['dataset']);status['completed_rows']+=len(rows);continue
        for i,start in enumerate(range(0,len(rows),d['batch_rows'])):
            c.require(not stop and not (root/'STOP').exists(),'campaign stopped')
            c.require(time.monotonic()-started<p['deadline_seconds'],'campaign deadline')
            c.require(shutil.disk_usage(root).free>p['minimum_free_bytes']+160*1024**2,'campaign disk reserve')
            expected=rows[start:start+d['batch_rows']];active=folder/f'batch-{i:05d}'
            status.update(dataset=d['dataset'],batch=i,batches=d['batches'],dataset_committed_rows=start,active=str(active),updated_ns=time.time_ns())
            durable(root/'progress.json',status)
            if (active/'batch-complete.json').exists():verify_batch(active,expected);continue
            c.require(not active.exists(),'unsealed attempt requires explicit recovery; never overwrite')
            x,contract=native.read_selected(d['source_path'],d['dataset'],expected,d['class_names'],d['source_sha256']);del x
            selection=folder/f'selection-{i:05d}.json'
            entry=dict(source_path=d['source_path'],contract=contract,run_id=root.name+'-'+d['dataset']+'-'+str(i),validation_campaign=dict(plan_sha256=c.file_hash(root/'campaign.json'),batch=i,validation_rank_start=start))
            durable(selection,dict(source_selection={d['dataset']:entry}))
            m.prepare(active,selection,d['dataset'],verified_source=d['source_fingerprint'])
            # State checks precede one TX owner; STOP goes through the pilot's exact generation cancel.
            with (folder/f'batch-{i:05d}.log').open('xb') as log:
                child=subprocess.Popen([sys.executable,'-B',str(SCRIPTS/'amc-rrc-pilot.py'),'run','--root',str(active)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                end=time.monotonic()+p['batch_deadline_seconds']
                while child.poll() is None:
                    if stop or (root/'STOP').exists() or time.monotonic()>end:
                        (active/'STOP').touch();stop=True
                    if time.monotonic()>end+90:
                        os.killpg(child.pid,signal.SIGTERM)
                        try:child.wait(timeout=30)
                        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=10)
                        raise RuntimeError('finite child exceeded STOP grace')
                    time.sleep(.2)
                c.require(child.returncode==0,'finite batch failed')
            seal_batch(active,expected)
            status['dataset_committed_rows']=start+len(expected);durable(root/'progress.json',status)
        seal_dataset(folder,d,rows)
        status['completed_datasets'].append(d['dataset']);status['completed_rows']+=len(rows);durable(root/'progress.json',status)
      status.update(status='complete',completed_ns=time.time_ns());durable(root/'complete.json',status)
    except BaseException as e:
        status.update(status='stopped' if stop or (root/'STOP').exists() else 'failed',error=repr(e));raise
    finally:
        if child is not None and child.poll() is None:
            (active/'STOP').touch()
            try:child.wait(timeout=90)
            except subprocess.TimeoutExpired:
                child.terminate();child.wait(timeout=90)
        if active is not None and (active/'plan.json').exists():
            try:
                baseline=json.loads((active/'plan.json').read_text())['baseline_radio']
                bg.restoration(baseline);bg.idle();device.preflight();status['restored']=True
            except BaseException as e:status['restored']=False;status['restoration_error']=repr(e)
        status['updated_ns']=time.time_ns();durable(root/'progress.json',status)
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('command',choices=['plan','run']);a.add_argument('--root',required=True,type=Path);a.add_argument('--selection',type=Path);args=a.parse_args()
    if args.command=='plan':prepare(args.root,args.selection)
    else:run(args.root)
