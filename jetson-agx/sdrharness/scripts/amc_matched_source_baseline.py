#!/usr/bin/env python3
"""Amplitude-chain audit and matched-preprocessing source baseline; no RF/training."""
import argparse
import gc
import os
from pathlib import Path
import signal
import shutil
import sys
import time
import asyncio
import fcntl
import h5py
import numpy as np
import amc_validation_eval as e
import amc_rrc_transport as transport
from amc_source_rms_control import rms_only
from gpu_lease import GpuLease

def transform(x,dataset):
    return e.normalize(x,dataset) if dataset in ('rml2016a','rml2016b') else rms_only(x)[0]

def software():
    files=[Path(__file__).resolve(),Path(e.__file__),Path(e.backend.__file__),Path(transport.__file__),
           Path(__file__).with_name('amc_source_rms_control.py').resolve(),Path(__file__).with_name('rml2018a_stream_dsp.py').resolve(),
           Path(__file__).with_name('gpu_lease.py').resolve()]
    return {str(p):e.backend.digest(p) for p in files}

def prepare(root,parent,control):
    e.c.require(root.is_absolute() and root.resolve()==root and not root.exists(),'fresh matched baseline root')
    p=e.effective_plan(parent,parent/'resident-source-revision-v1.json')
    e.c.require(e.read(parent/'complete.json')['status']=='complete' and e.read(control/'complete.json')['status']=='complete','complete parents')
    e.c.require(shutil.disk_usage(root.parent).free>8*1024**3,'output reserve')
    root.mkdir(mode=0o700)
    e.atomic(root/'plan.json',dict(schema='amc-matched-source-v1',parent=str(parent),control=str(control),
        parent_complete_sha256=e.backend.digest(parent/'complete.json'),control_complete_sha256=e.backend.digest(control/'complete.json'),
        source_campaign=p['source'],datasets=p['datasets'],models=p['models'],software=software(),
        scope='same 713385 seed42 validation members, eight models; source input view matched to receiver normalization, not a new IQ dataset',
        transforms={'rml2016a':'sum_abs_iq_one','rml2016b':'sum_abs_iq_one','rml2018a':'complex_rms_one','hisarmod2019':'complex_rms_one'},
        maximum_forward_rows=713385*8+32*512,deadline_seconds=48*3600,
        reuse='original-source logits only for byte-identical transformed rows; exact 31768-row RMS-control logits for D10/MCFormer after full input/checkpoint checks',
        no_rf=True,no_training=True,production_admission=False))

def load_dataset(root,plan,d):
    out=root/d['dataset'];out.mkdir(exist_ok=True);capture=Path(plan['source_campaign'])/d['dataset']
    e.c.require(e.backend.digest(capture/'dataset-complete.json')==d['seal_sha256'] and
                e.backend.digest(d['source_path'])==d['source_sha256'],'frozen capture/source')
    n=d['rows'];length=d['window_samples'];required=2*n*2*length*4+12*1024**3
    e.c.require(e.resource_gate()['available_kib']*1024>required,'resident input and model reserve')
    with h5py.File(d['vds']) as f:
        meta={k:f[k][:] for k in ('source_row','class_id','source_snr_db','validation_rank')}
    x=np.empty((n,2,length),dtype=np.float32);matched=np.empty_like(x);peak=np.empty(n);rms=np.empty(n);l1=np.empty(n)
    for start in range(0,n,2048):
        stop=min(start+2048,n);s=slice(start,stop);x[s]=e.source_values(d,meta['source_row'][s],meta['class_id'][s],meta['source_snr_db'][s])
        matched[s]=transform(x[s],d['dataset']);z=x[s,0].astype(float)+1j*x[s,1].astype(float)
        peak[s]=abs(z).max(1);rms[s]=np.sqrt(np.mean(abs(z)**2,axis=1));l1[s]=abs(z).sum(1)
    same=np.all(x==matched,axis=(1,2));meta['identical_to_original']=same
    # Audit every registered TX row scale against original source peaks.
    seal=e.read(capture/'dataset-complete.json');offset=0;max_error=0.;gains=[]
    for item in seal['batch_receipts']:
        batch=capture/f"batch-{item['batch']:05d}";bp=e.read(batch/'plan.json');rows=bp['source']['contract']['source_rows'];count=len(rows)
        e.c.require(np.array_equal(rows,meta['source_row'][offset:offset+count]),'TX member order')
        scales=np.asarray(bp['transport']['row_scales']);expected=.2*np.sqrt(10)/peak[offset:offset+count]
        error=float(np.max(abs(scales/expected-1)));e.c.require(error<1e-12,'recorded per-row peak scaling')
        max_error=max(max_error,error);gains.append(bp['transport']['global_gain']);offset+=count
    e.c.require(offset==n,'all TX row scales checked')
    # Non-identifiability demonstration: changing each source row's absolute
    # amplitude by positive powers of two leaves the full emitted IQ identical.
    probe=np.linspace(0,n-1,16,dtype=int);z=x[probe,0].astype(float)+1j*x[probe,1].astype(float)
    factors=2.**np.tile(np.arange(-2,2),4);tx,a=transport.transmit(z,'amplitude-audit',frame_payload_samples=2048)
    tx2,b=transport.transmit(z*factors[:,None],'amplitude-audit',frame_payload_samples=2048)
    e.c.require(np.array_equal(tx,tx2),'amplitude rescaling leaves TX byte-identical')
    e.atomic(out/'amplitude-audit.json',dict(dataset=d['dataset'],rows=n,source_rms_quantiles=np.quantile(rms,[0,.05,.5,.95,1]).tolist(),
        source_l1_quantiles=np.quantile(l1,[0,.05,.5,.95,1]).tolist(),matched_input_sha256=e.c.digest(matched.tobytes()),
        original_input_sha256=e.c.digest(x.tobytes()),identical_original_rows=int(same.sum()),tx_scale_max_relative_error=max_error,
        tx_global_gain_range=[min(gains),max(gains)],positive_row_rescaling_probe_rows=meta['source_row'][probe].tolist(),
        tx_same_bytes_after_row_rescaling=True,probe_tx_sha256=a['tx_sha256'],original_scales_not_encoded_in_receiver_payload=True,
        resident_input_bytes=x.nbytes+matched.nbytes,receiver='CFO/phase correction, matched filtering, raw/guard separate unit RMS; 2016 additional sum-abs normalization',
        recoverability='pilot can estimate effective common channel/batch gain under channel assumptions; original row peak/RMS is not identifiable without extra transmitter metadata; stored RX RMS recovers pre-normalized ADC scale only'))
    for array in [x,matched,*meta.values()]:array.flags.writeable=False
    return x,matched,meta

def worker(root,plan,d,spec,scratch,original,matched,meta):
    dataset=d['dataset'];variant=spec['variant'];out=root/dataset/variant;out.mkdir(exist_ok=True)
    for path,sha in spec['files'].items():e.c.require(e.backend.digest(path)==sha,'frozen model/config/source')
    n=d['rows'];classes=len(d['class_names']);logits=np.full((n,classes),np.nan,dtype=np.float32);reuse=np.zeros(n,dtype=np.int8)
    parent=Path(plan['parent'])/dataset/variant;probe=np.unique(np.linspace(0,n-1,128,dtype=int));baseline=np.empty((len(probe),classes),np.float32)
    for start in range(0,n,2048):
        end=min(start+2048,n);path=parent/'source'/f'rows-{start:07d}.npz'
        e.c.require(e.backend.digest(path)==e.read(path.with_suffix('.json'))['sha256'],'frozen original predictions')
        with np.load(path) as f:
            e.c.require(np.array_equal(f['source_row'],meta['source_row'][start:end]),'source prediction members')
            ii=np.flatnonzero(meta['identical_to_original'][start:end]);logits[start+ii]=f['source_logits'][ii];reuse[start+ii]=1
            pi=np.flatnonzero((probe>=start)&(probe<end));baseline[pi]=f['source_logits'][probe[pi]-start]
    if dataset=='rml2018a' and variant in ('amc_mamba_d10','baseline_mcformer'):
        control=Path(plan['control'])/variant;report=e.read(control/'result.json');path=control/'predictions.npz'
        e.c.require(e.backend.digest(path)==report['predictions_sha256'] and report['checkpoint_sha256']==spec['files'][str(Path(spec['package'])/'best.pt')],'control identity')
        with np.load(path) as f:
            ii=f['validation_rank'];e.c.require(np.array_equal(meta['source_row'][ii],f['source_row']) and
                e.c.digest(original[ii].tobytes())==str(f['original_input_sha256']) and e.c.digest(matched[ii].tobytes())==str(f['rms_input_sha256']),'exact reusable control inputs')
            logits[ii]=f['rms_logits'];reuse[ii]=2
    for start in range(0,n,2048):
        end=min(start+2048,n);path=out/f'rows-{start:07d}.npz'
        if path.with_suffix('.json').exists():
            with h5py.File(d['vds']) as source:e.verify_shard(path,source,start,end,classes,('matched',))
            with np.load(path) as f:
                e.c.require(str(f['input_sha256'])==e.c.digest(matched[start:end].tobytes()),'resumed input SHA');logits[start:end]=f['matched_logits'];reuse[start:end]=f['reuse_origin']
    for key in ('TMPDIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR'):
        path=scratch/key;path.mkdir(parents=True,exist_ok=True);os.environ[key]=str(path)
    lease=GpuLease(scratch/'gpu-gate','mamba');token=asyncio.run(lease.acquire(time.monotonic()+10,request=dataset+'/'+variant));started=time.monotonic()
    try:
        e.resource_gate();package=Path(spec['package']);model,torch=e.backend.load_frozen_model(package,e.read(package/'config.json'),variant=='amc_mamba_d10',d['class_names'])
        def predict(x):
            with torch.inference_mode():return model(torch.from_numpy(np.array(x,copy=True,order='C')).cuda()).float().cpu().numpy()
        old=predict(original[probe]);e.c.require(np.allclose(old,baseline,atol=2e-4,rtol=2e-4) and np.array_equal(old.argmax(1),baseline.argmax(1)),'original baseline gate')
        numerical=predict(matched[probe]);single_pos=np.linspace(0,len(probe)-1,8,dtype=int);single=np.concatenate([predict(matched[probe[j]:probe[j]+1]) for j in single_pos])
        e.c.require(np.allclose(single,numerical[single_pos],atol=2e-4,rtol=2e-4) and np.array_equal(single.argmax(1),numerical[single_pos].argmax(1)),'matched numerical gate')
        forward_rows=0
        for start in range(0,n,2048):
            e.c.require(not (root/'STOP').exists() and time.monotonic()-started<plan['deadline_seconds'],'STOP/deadline');e.resource_gate()
            e.c.require(shutil.disk_usage(root).free>2*1024**3,'disk reserve')
            end=min(start+2048,n);path=out/f'rows-{start:07d}.npz';missing=np.flatnonzero(~np.isfinite(logits[start:end]).all(1))+start
            for begin in range(0,len(missing),128):
                ii=missing[begin:begin+128];logits[ii]=predict(matched[ii]);forward_rows+=len(ii)
            if not path.with_suffix('.json').exists():
                e.save_shard(path,dict(source_row=meta['source_row'][start:end],validation_rank=meta['validation_rank'][start:end],class_id=meta['class_id'][start:end],
                    matched_logits=logits[start:end],matched_prediction=logits[start:end].argmax(1),input_sha256=np.array(e.c.digest(matched[start:end].tobytes())),reuse_origin=reuse[start:end]))
            e.atomic(out/'progress.json',dict(rows=end,total=n,new_payload_forward_rows=forward_rows))
        e.c.require(np.isfinite(logits).all() and np.allclose(numerical,logits[probe],atol=2e-4,rtol=2e-4) and np.array_equal(numerical.argmax(1),logits[probe].argmax(1)),'probe/output identity')
        matrix=np.zeros((classes,classes),dtype=np.int64);np.add.at(matrix,(meta['class_id'],logits.argmax(1)),1)
        e.atomic(out/'result.json',dict(dataset=dataset,model=variant,rows=n,correct=int(matrix.trace()),accuracy=float(matrix.trace()/n),confusion=matrix.tolist(),
            original=e.read(parent/'result-three-planes.json')['planes'],input_transform=plan['transforms'][dataset],plan_sha256=e.backend.digest(root/'plan.json'),
            checkpoint_sha256=spec['files'][str(package/'best.pt')],new_payload_forward_rows=forward_rows,numerical_forward_rows=len(probe)*2+len(single_pos),
            reused_original_rows=int((reuse==1).sum()),reused_control_rows=int((reuse==2).sum()),baseline_max_error=float(np.max(abs(old-baseline))),
            matched_single_max_error=float(np.max(abs(single-numerical[single_pos]))),precision='FP32 TF32 off',strict_load=True,elapsed_seconds=time.monotonic()-started))
        torch.cuda.synchronize()
    finally:lease.release(token);lease.close()

def run(root,scratch):
    plan=e.read(root/'plan.json');lock=(root/'run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for path,sha in plan['software'].items():e.c.require(e.backend.digest(path)==sha,'frozen software')
    e.capture.pilot().helpers()[0].spark_off();done=[];began=time.monotonic()
    try:
        for d in plan['datasets']:
            e.c.require('torch' not in sys.modules,'parent has no CUDA context');original,matched,meta=load_dataset(root,plan,d)
            for spec in (m for m in plan['models'] if m['dataset']==d['dataset']):
                e.c.require(not (root/'STOP').exists(),'STOP');out=root/d['dataset']/spec['variant']
                if (out/'result.json').exists():
                    result=e.read(out/'result.json');e.c.require(result['plan_sha256']==e.backend.digest(root/'plan.json'),'completed identity')
                    with h5py.File(d['vds']) as f:
                        for start in range(0,d['rows'],2048):e.verify_shard(out/f'rows-{start:07d}.npz',f,start,min(start+2048,d['rows']),len(d['class_names']),('matched',))
                    done.append(result);continue
                e.atomic(root/'progress.json',dict(status='running',dataset=d['dataset'],model=spec['variant'],completed_models=len(done),total_models=32))
                out.mkdir(parents=True,exist_ok=True);sys.stdout.flush();sys.stderr.flush();pid=os.fork()
                if pid==0:
                    try:
                        with (out/'worker.log').open('a') as f:os.dup2(f.fileno(),1);os.dup2(f.fileno(),2)
                        worker(root,plan,d,spec,scratch,original,matched,meta)
                    except BaseException:
                        import traceback
                        traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)
                    sys.stdout.flush();sys.stderr.flush();os._exit(0)
                while True:
                    waited,status=os.waitpid(pid,os.WNOHANG)
                    if waited:break
                    if time.monotonic()-began>plan['deadline_seconds']:
                        os.kill(pid,signal.SIGKILL);os.waitpid(pid,0);raise RuntimeError('deadline')
                    time.sleep(.5)
                e.c.require(os.waitstatus_to_exitcode(status)==0,'model child failed');done.append(e.read(out/'result.json'))
            del original,matched,meta;gc.collect()
        e.atomic(root/'complete.json',dict(status='complete',rows=713385,results=done));e.atomic(root/'progress.json',dict(status='complete',completed_models=32))
    except BaseException as exc:e.atomic(root/'progress.json',dict(status='failed',error=repr(exc),completed_models=len(done)));raise
    finally:lock.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run']);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--parent',type=Path);p.add_argument('--control',type=Path);p.add_argument('--scratch',type=Path);a=p.parse_args()
    if a.command=='prepare':prepare(a.root,a.parent,a.control)
    else:run(a.root,a.scratch)
