#!/usr/bin/env python3
"""Streaming, restartable FP32 inference on sealed four-dataset RF validation."""
import argparse
import asyncio
from contextlib import nullcontext
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import gc
import h5py
import numpy as np
import amc_validation_campaign as capture
import amc_rrc_pilot_eval as backend
from gpu_lease import GpuLease

c=capture.c
atomic=capture.durable
VARIANTS=('amc_mamba_d10','baseline_cnn2_stable','baseline_resnet','baseline_gru',
          'baseline_cldnn','baseline_mcldnn','baseline_mcformer','baseline_mamc')
MODELS=Path('/home/jetson/models/amc')
CHUNK=2048
BATCH=128

def read(path):
    return json.loads(Path(path).read_text())

def model_identity(dataset,variant,classes):
    package=MODELS/dataset/variant;cfg=read(package/'config.json')
    c.require(cfg['selected_model_variant']==variant and cfg['resolved_config']['data']['seed']==42 and
              cfg['resolved_config']['data']['num_classes']==len(classes),'seed42 class contract')
    if variant=='amc_mamba_d10':
        identity=read(package/'deployment_manifest.json')
        c.require(identity['seed']==42 and identity['class_names']==classes,'D10 labels')
    else:
        identity=next(v for v in read(MODELS/'verification.json') if v['dataset']==dataset and v['variant']==variant)
    c.require(backend.digest(package/'best.pt')==identity['sha256'],'checkpoint identity')
    source=package/('source_03fa833' if variant=='amc_mamba_d10' else 'source')
    files=[package/'best.pt',package/'config.json',*sorted(source.rglob('*.py'))]
    c.require(len(files)>2,'model source required')
    return dict(dataset=dataset,variant=variant,package=str(package),class_names=classes,
                files={str(p):backend.digest(p) for p in files},backend=cfg['model_backend'])

def software():
    return {str(p):backend.digest(p) for p in (Path(__file__).resolve(),Path(backend.__file__).resolve(),
            Path(capture.__file__).resolve(),Path(__file__).with_name('gpu_lease.py').resolve(),
            Path(__file__).with_name('rml2018a_campaign_store.py').resolve())}

def prepare(root,source):
    c.require(root.is_absolute() and root.resolve()==root and not root.exists() and
              root.parent==c.REPO/'local-assets/amc-eval/results','fresh application result root')
    complete=read(source/'complete.json');status=read(source/'progress.json')
    c.require(complete['status']=='complete' and status['restored'] and
              complete['completed_rows']==sum(capture.COUNTS),'all RF finished/restored')
    campaign=read(source/'campaign.json');datasets=[];models=[]
    for d in campaign['datasets']:
        folder=source/d['dataset'];seal=read(folder/'dataset-complete.json')
        c.require(seal['status']=='complete' and seal['rows']==d['rows'],'complete dataset')
        members=np.load(folder/'validation-rows.npy',allow_pickle=False)
        capture.verify_dataset(folder,d,members)
        # Pin all HDF5 VDS targets, including offline-recovered batches.
        targets={}
        for entry in seal['batch_receipts']:
            b=folder/f"batch-{entry['batch']:05d}"
            p=capture.batch_artifacts(b)[0]/'processed.h5';targets[str(p)]=backend.digest(p)
        datasets.append(dict(dataset=d['dataset'],rows=d['rows'],window_samples=d['window_samples'],
            class_names=d['class_names'],vds=str(folder/'raw-guard.h5'),vds_sha256=seal['virtual_dataset_sha256'],
            seal_sha256=backend.digest(folder/'dataset-complete.json'),processed=targets))
        models.extend(model_identity(d['dataset'],v,d['class_names']) for v in VARIANTS)
    c.require(shutil.disk_usage(root.parent).free>8*1024**3,'8GiB result reserve')
    root.mkdir(mode=0o700)
    atomic(root/'plan.json',dict(schema='amc-full-validation-inference-v1',source=str(source),
        capture_complete_sha256=backend.digest(source/'complete.json'),datasets=datasets,models=models,
        software=software(),seed=42,planes=['raw','guard'],chunk_rows=CHUNK,batch_size=BATCH,
        total_predictions=complete['completed_rows']*16,deadline_seconds=48*3600,
        normalization={'rml2016a':'sum_abs_iq_one','rml2016b':'sum_abs_iq_one',
                       'rml2018a':'complex_rms_one','hisarmod2019':'complex_rms_one'},
        scope='all seed42 validation members, including raw fallback; no source predictions, training or RF'))

def normalize(x,dataset):
    x=np.ascontiguousarray(x,dtype=np.float32)
    c.require(np.isfinite(x).all(),'finite input; never drop members')
    if dataset in ('rml2016a','rml2016b'):
        denominator=np.sqrt(np.sum(x.astype(np.float64)**2,axis=1)).sum(axis=1)
        c.require(np.all(denominator>0),'nonzero native input')
        x=np.ascontiguousarray(x/denominator[:,None,None],dtype=np.float32)
    return x

def resource_gate():
    memory={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
    temperatures={};missing=[]
    for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
        name=(zone/'type').read_text().strip()
        try:temperatures[name]=int((zone/'temp').read_text())/1000
        except (OSError,ValueError,TypeError):missing.append(name)
    required={'cpu-thermal','tj-thermal','soc0-thermal','soc1-thermal','soc2-thermal'}
    c.require(memory['MemAvailable']>=4*1024**2 and required<=temperatures.keys() and
              max(temperatures.values())<80,'resource gate')
    return dict(available_kib=memory['MemAvailable'],temperatures=temperatures,unmeasured=missing)

def effective_plan(root,revision=None):
    plan=read(root/'plan.json')
    if revision is not None:
        revision=Path(revision)
        c.require(revision.is_absolute() and revision.parent==root,'local execution revision')
        value=read(revision)
        c.require(value['schema']=='amc-resident-inference-revision-v1' and
                  value['parent_plan_sha256']==backend.digest(root/'plan.json') and
                  set(value['software'])==set(plan['software']) and
                  value['planes']==['source','raw','guard'],'authorized source addition')
        plan=dict(plan,software=value['software'],execution_revision_sha256=backend.digest(revision),
                  planes=value['planes'],total_predictions=sum(d['rows'] for d in plan['datasets'])*24)
        campaign=read(Path(plan['source'])/'campaign.json')
        for d in plan['datasets']:
            original=next(x for x in campaign['datasets'] if x['dataset']==d['dataset'])
            first=read(Path(plan['source'])/d['dataset']/'batch-00000/plan.json')
            d.update(source_path=original['source_path'],source_sha256=original['source_sha256'],
                     raw_label_values=first['source']['contract']['raw_label_values'])
    for path,sha in plan['software'].items():c.require(backend.digest(path)==sha,'inference software')
    return plan

def resident_budget(d,available_bytes):
    # Both processed planes, their masks, and shared labels/row metadata.
    payload=d['rows']*(3*2*d['window_samples']*4+8*4+2)
    # Reserve 12GiB for one model/CUDA and 25% of input size for load transients.
    required=(payload*5+3)//4+12*1024**3
    return dict(input_bytes=payload,required_available_bytes=required,
                available_bytes=available_bytes,allowed=available_bytes>=required)

def load_resident(d,root):
    for path,sha in {**d['processed'],d['vds']:d['vds_sha256']}.items():
        c.require(backend.digest(path)==sha,'sealed inference dataset')
    if 'source_path' in d:c.require(backend.digest(d['source_path'])==d['source_sha256'],'original source SHA')
    budget=resident_budget(d,resource_gate()['available_kib']*1024)
    if not budget['allowed']:
        atomic(root/d['dataset']/'memory.json',dict(mode='streaming',budget=budget))
        return None
    values={};began=time.monotonic()
    with h5py.File(d['vds'],'r') as f:
        for name in ('source_row','class_id','source_snr_db','validation_rank','valid/raw','valid/guard'):
            values[name]=f[name][:]
        c.require(values['valid/raw'].all() and values['valid/guard'].all(),'all received members')
        for tag in ('raw','guard'):
            x=f['inputs/'+tag][:]
            c.require(x.shape==(d['rows'],2,d['window_samples']),'native input shape')
            for start in range(0,len(x),CHUNK):x[start:start+CHUNK]=normalize(x[start:start+CHUNK],d['dataset'])
            values['inputs/'+tag]=x
    if 'source_path' in d:
        x=np.empty((d['rows'],2,d['window_samples']),dtype=np.float32)
        for start in range(0,d['rows'],CHUNK):
            end=min(start+CHUNK,d['rows'])
            x[start:end]=source_values(d,values['source_row'][start:end],values['class_id'][start:end],values['source_snr_db'][start:end])
        values['inputs/source']=x
    for x in values.values():x.flags.writeable=False
    atomic(root/d['dataset']/'memory.json',dict(mode='resident_fork_readonly',budget=budget,
        resident_bytes=sum(x.nbytes for x in values.values()),load_seconds=time.monotonic()-began,
        sharing='one parent allocation inherited read-only by sequential fresh model children; no parent CUDA context'))
    return values

def source_values(d,rows,labels,snrs):
    """Exact original validation values: layout/FP32 only, bounded source reads."""
    rows=np.asarray(rows);x=np.empty((len(rows),2,d['window_samples']),dtype=np.float32)
    with h5py.File(d['source_path'],'r') as f:
        if d['dataset']!='rml2018a':
            names=[v.decode() if isinstance(v,bytes) else str(v) for v in f['classes'][:]]
            c.require(names==d['class_names'],'source class order')
        for block in np.unique(rows//8192):
            ids=np.flatnonzero(rows//8192==block);lo=int(block)*8192;hi=min(lo+8192,len(f['X']))
            positions=rows[ids]-lo
            values=f['X'][lo:hi][positions];y=f['Y'][lo:hi][positions];z=f['Z'][lo:hi][positions].reshape(-1)
            if d['dataset']=='rml2018a':
                c.require(np.array_equal(y,np.eye(len(d['class_names']))[y.argmax(1)]),'source onehot')
                values=values.transpose(0,2,1);y=y.argmax(1)
            else:y=np.searchsorted(np.asarray(d['raw_label_values']),y.reshape(-1))
            c.require(np.array_equal(y,np.asarray(labels)[ids]) and np.array_equal(z,np.asarray(snrs)[ids]),'source/RF row labels and Z')
            c.require(values.shape==(len(ids),2,d['window_samples']) and np.isfinite(values).all(),'finite native source')
            x[ids]=values
    return x


def save_shard(path,values):
    temp=path.with_suffix('.tmp')
    with temp.open('wb') as f:
        np.savez_compressed(f,**values);f.flush();os.fsync(f.fileno())
    temp.replace(path);capture.store.sync_directory(path.parent)
    atomic(path.with_suffix('.json'),dict(sha256=backend.digest(path),rows=len(values['source_row'])))

def verify_shard(path,source,start,stop,classes,tags=('raw','guard')):
    receipt=read(path.with_suffix('.json'))
    c.require(backend.digest(path)==receipt['sha256'] and receipt['rows']==stop-start,'prediction shard hash')
    with np.load(path,allow_pickle=False) as p:
        c.require(np.array_equal(p['source_row'],source['source_row'][start:stop]) and
                  np.array_equal(p['validation_rank'],np.arange(start,stop)) and
                  np.array_equal(p['class_id'],source['class_id'][start:stop]),'prediction membership')
        result={}
        for tag in tags:
            logits=p[tag+'_logits'];pred=p[tag+'_prediction']
            c.require(logits.shape==(stop-start,classes) and np.isfinite(logits).all() and
                      np.array_equal(logits.argmax(1),pred),'finite logits and exact argmax')
            matrix=np.zeros((classes,classes),dtype=np.int64);np.add.at(matrix,(p['class_id'],pred),1)
            result[tag]=matrix
        return result

def worker(root,dataset,variant,scratch,resident=None,plan=None):
    plan=plan or effective_plan(root);d=next(d for d in plan['datasets'] if d['dataset']==dataset)
    spec=next(m for m in plan['models'] if m['dataset']==dataset and m['variant']==variant)
    inputs={**d['processed'],d['vds']:d['vds_sha256']} if resident is None else {}
    for path,sha in {**plan['software'],**spec['files'],**inputs}.items():
        c.require(backend.digest(path)==sha,'frozen inference input/software')
    package=Path(spec['package']);out=root/dataset/variant;out.mkdir(parents=True,exist_ok=True)
    for name in ('TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR','TMPDIR'):
        p=scratch/name;p.mkdir(parents=True,exist_ok=True);os.environ[name]=str(p)
    lease=GpuLease(scratch/'gpu-gate','mamba');token=asyncio.run(lease.acquire(time.monotonic()+10,request=dataset+'/'+variant))
    stop=False
    def cancel(*_):
        nonlocal stop
        stop=True
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,cancel)
    try:
        resource_gate()
        model,torch=backend.load_frozen_model(package,read(package/'config.json'),variant=='amc_mamba_d10',spec['class_names'])
        def predict(x):
            with torch.inference_mode():
                return np.concatenate([model(torch.from_numpy(x[i:i+BATCH]).cuda()).float().cpu().numpy()
                                       for i in range(0,len(x),BATCH)])
        matrices={tag:np.zeros((len(spec['class_names']),)*2,dtype=np.int64) for tag in plan['planes']}
        gates={};started=time.monotonic()
        with (h5py.File(d['vds'],'r') if resident is None else nullcontext(resident)) as f:
            def input_rows(tag,selection):
                if tag=='source' and resident is None:
                    return source_values(d,f['source_row'][selection],f['class_id'][selection],f['source_snr_db'][selection])
                x=f['inputs/'+tag][selection]
                return normalize(x,dataset) if resident is None else x
            # Numerical check on real first/middle/last validation members,
            # including full configured GPU batches, before accepting any shard.
            for tag in plan['planes']:
                ids=np.unique(np.linspace(0,d['rows']-1,BATCH,dtype=int));x=input_rows(tag,ids)
                batched=predict(x);probe=np.linspace(0,len(ids)-1,4,dtype=int)
                single=np.concatenate([predict(x[i:i+1]) for i in probe])
                c.require(np.isfinite(batched).all() and np.allclose(single,batched[probe],atol=2e-4,rtol=2e-4)
                          and np.array_equal(single.argmax(1),batched[probe].argmax(1)),'FP32 batch/single gate')
                gates[tag]=dict(rows=ids.tolist(),probe=probe.tolist(),max_abs_error=float(np.max(abs(single-batched[probe]))))
            atomic(out/'numerical-gate-three-planes.json',gates)
            for start in range(0,d['rows'],CHUNK):
                c.require(not stop and not (root/'STOP').exists(),'inference stopped')
                c.require(time.monotonic()-started<plan['deadline_seconds'],'worker deadline')
                c.require(shutil.disk_usage(root).free>2*1024**3,'result disk reserve')
                resources=resource_gate()
                end=min(start+CHUNK,d['rows'])
                groups=[(('raw','guard'),out)]
                if 'source' in plan['planes']:groups.append((('source',),out/'source'))
                for tags,folder in groups:
                    folder.mkdir(exist_ok=True);path=folder/f'rows-{start:07d}.npz'
                    if not path.with_suffix('.json').exists():
                        # Uncommitted orphan data/temp may be regenerated; old committed RX shards stay intact.
                        values=dict(source_row=f['source_row'][start:end],validation_rank=np.arange(start,end),
                                    class_id=f['class_id'][start:end],source_snr_db=f['source_snr_db'][start:end])
                        for tag in tags:
                            if tag!='source':c.require(f['valid/'+tag][start:end].all(),'all captured members required')
                            x=input_rows(tag,slice(start,end));logits=predict(x)
                            c.require(logits.shape==(end-start,len(spec['class_names'])) and np.isfinite(logits).all(),'output shape/finite')
                            values.update({tag+'_logits':logits,tag+'_prediction':logits.argmax(1),
                                           tag+'_input_sha256':np.array(c.digest(x.tobytes()))})
                        save_shard(path,values)
                    got=verify_shard(path,f,start,end,len(spec['class_names']),tags)
                    for tag in tags:matrices[tag]+=got[tag]
                atomic(out/'progress.json',dict(rows=end,total_rows=d['rows'],elapsed_seconds=time.monotonic()-started,resources=resources))
        report=dict(dataset=dataset,variant=variant,seed=42,rows=d['rows'],strict_load=True,
            backend=spec['backend'],precision='FP32 TF32 disabled',normalization=plan['normalization'][dataset],
            plan_sha256=backend.digest(root/'plan.json'),checkpoint_sha256=spec['files'][str(package/'best.pt')],
            production_admission=False,planes={tag:dict(correct=int(m.trace()),accuracy=float(m.trace()/d['rows']),
            confusion=m.tolist()) for tag,m in matrices.items()})
        report.update(input_mode='resident_fork_readonly' if resident is not None else 'streaming',
                      execution_revision_sha256=plan.get('execution_revision_sha256'))
        report['source_normalization']='original FP32 values; layout only'
        atomic(out/'result-three-planes.json',report);torch.cuda.synchronize();print(json.dumps(report),flush=True)
    finally:
        lease.release(token);lease.close()

def verify_completed(out,d,source,root):
    report=read(out/'result-three-planes.json');classes=len(d['class_names'])
    c.require(report['plan_sha256']==backend.digest(root/'plan.json') and report['rows']==d['rows'],'completed pair identity')
    matrices={tag:np.zeros((classes,classes),dtype=np.int64) for tag in report['planes']}
    for start in range(0,d['rows'],CHUNK):
        got=verify_shard(out/f'rows-{start:07d}.npz',source,start,min(start+CHUNK,d['rows']),classes)
        if 'source' in matrices:got.update(verify_shard(out/'source'/f'rows-{start:07d}.npz',source,start,min(start+CHUNK,d['rows']),classes,('source',)))
        for tag in matrices:matrices[tag]+=got[tag]
    for tag,m in matrices.items():c.require(m.tolist()==report['planes'][tag]['confusion'],'completed confusion readback')
    return report

def run(root,scratch,revision=None):
    lock=(root/'run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    plan=effective_plan(root,revision)
    capture.pilot().helpers()[0].spark_off()
    scratch.mkdir(parents=True,exist_ok=True);done=[];started=time.monotonic()
    try:
        for d in plan['datasets']:
            dataset=d['dataset'];(root/dataset).mkdir(exist_ok=True)
            c.require('torch' not in sys.modules,'parent must not initialize CUDA before fork')
            resident=load_resident(d,root)
            for spec in (m for m in plan['models'] if m['dataset']==dataset):
                c.require(not (root/'STOP').exists() and time.monotonic()-started<plan['deadline_seconds'],'stopped/deadline')
                variant=spec['variant'];out=root/dataset/variant;out.mkdir(parents=True,exist_ok=True)
                atomic(root/'progress.json',dict(status='running',dataset=dataset,variant=variant,completed_pairs=len(done),total_pairs=32))
                if (out/'result-three-planes.json').exists():
                    with (h5py.File(d['vds'],'r') if resident is None else nullcontext(resident)) as source:
                        done.append(verify_completed(out,d,source,root))
                    del source
                    continue
                sys.stdout.flush();sys.stderr.flush()
                pid=os.fork()
                if pid==0:
                    try:
                        with (out/'worker.log').open('a') as log:
                            os.dup2(log.fileno(),1);os.dup2(log.fileno(),2)
                        worker(root,dataset,variant,scratch,resident,plan)
                    except BaseException:
                        import traceback
                        traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)
                    sys.stdout.flush();sys.stderr.flush();os._exit(0)
                while True:
                    waited,status=os.waitpid(pid,os.WNOHANG)
                    if waited:break
                    if time.monotonic()-started>plan['deadline_seconds']:
                        os.kill(pid,signal.SIGKILL);os.waitpid(pid,0);raise RuntimeError('inference deadline')
                    time.sleep(.5)
                c.require(os.waitstatus_to_exitcode(status)==0,'model child failed; committed shards preserved')
                done.append(read(out/'result-three-planes.json'))
            del resident;gc.collect()
        atomic(root/'complete.json',dict(status='complete',predictions=plan['total_predictions'],results=done))
        atomic(root/'progress.json',dict(status='complete',completed_pairs=len(done),total_pairs=32))
    except BaseException as error:
        atomic(root/'progress.json',dict(status='failed',error=repr(error),completed_pairs=len(done),total_pairs=32));raise
    finally:
        lock.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run','worker']);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--source',type=Path);p.add_argument('--scratch',type=Path);p.add_argument('--dataset');p.add_argument('--variant');p.add_argument('--revision',type=Path);args=p.parse_args()
    if args.command=='prepare':prepare(args.root,args.source)
    elif args.command=='run':run(args.root,args.scratch,args.revision)
    else:worker(args.root,args.dataset,args.variant,args.scratch)
