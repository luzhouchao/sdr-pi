#!/usr/bin/env python3
"""Fixed-member source-only RMS intervention, no RF or training."""
import argparse
import asyncio
import os
from pathlib import Path
import time
import h5py
import numpy as np
import amc_validation_eval as e
from gpu_lease import GpuLease

CLASSES=(1,18)
MODELS=('amc_mamba_d10','baseline_mcformer')

def rms_only(x):
    x=np.asarray(x,dtype=np.float32)
    e.c.require(x.ndim==3 and x.shape[1]==2 and np.isfinite(x).all(),'finite IQ layout')
    rms=np.sqrt(np.mean(np.sum(x.astype(np.float64)**2,axis=1),axis=1))
    e.c.require(np.all(rms>0),'positive RMS')
    return np.ascontiguousarray(x/rms[:,None,None],dtype=np.float32),rms

def prepare(root,infer,sinr):
    e.c.require(root.is_absolute() and root.resolve()==root and not root.exists(),'fresh intervention root')
    p=e.effective_plan(infer,infer/'resident-source-revision-v1.json');d=next(x for x in p['datasets'] if x['dataset']=='rml2018a')
    e.c.require(e.read(infer/'complete.json')['status']=='complete' and e.read(sinr/'complete.json')['status']=='complete','completed parents')
    with np.load(sinr/'rml2018a/sinr.npz') as f:
        rank=np.flatnonzero(np.isin(f['class_id'],CLASSES));ids=f['source_row'][rank]
        e.c.require(len(rank)==31768,'all original validation members of two fixed classes')
        root.mkdir(mode=0o700)
        with (root/'members.npz').open('wb') as out:
            np.savez_compressed(out,validation_rank=rank,source_row=ids,class_id=f['class_id'][rank],
                                source_snr_db=f['source_snr_db'][rank],reference_bin=f['reference_bin'][rank]);out.flush();os.fsync(out.fileno())
    models=[m for m in p['models'] if m['dataset']=='rml2018a' and m['variant'] in MODELS]
    e.atomic(root/'plan.json',dict(schema='source-rms-fixed-member-intervention-v1',inference_root=str(infer),sinr_root=str(sinr),dataset=d,models=models,
        inference_complete_sha256=e.backend.digest(infer/'complete.json'),sinr_sha256=e.backend.digest(sinr/'rml2018a/sinr.npz'),
        members_sha256=e.backend.digest(root/'members.npz'),script_sha256=e.backend.digest(__file__),
        shared_loader_sha256=e.backend.digest(e.backend.__file__),shared_reader_sha256=e.backend.digest(e.__file__),
        rows=31768,classes=list(CLASSES),models_order=list(MODELS),batch_size=128,deadline_seconds=1800,
        maximum_forward_rows=65000,intervention='original source divided by its own complex RMS, FP32; no DC removal, phase/filter/noise/RF changes',
        comparison='frozen original-source and guard predictions for exactly same members; raw conditional SINR bins unchanged',
        production_admission=False))

def run(root,variant,scratch):
    plan=e.read(root/'plan.json');e.c.require(variant in MODELS,'registered model')
    for path,sha in [(Path(__file__),plan['script_sha256']),(Path(e.backend.__file__),plan['shared_loader_sha256']),
                     (Path(e.__file__),plan['shared_reader_sha256']),(root/'members.npz',plan['members_sha256'])]:
        e.c.require(e.backend.digest(path)==sha,'frozen intervention identity')
    out=root/variant;e.c.require(not out.exists(),'fresh model result');out.mkdir()
    spec=next(m for m in plan['models'] if m['variant']==variant);d=plan['dataset'];infer=Path(plan['inference_root'])
    for path,sha in {**spec['files'],d['source_path']:d['source_sha256']}.items():e.c.require(e.backend.digest(path)==sha,'frozen model/source')
    with np.load(root/'members.npz') as f:members={k:f[k] for k in f.files}
    n=plan['rows'];original=np.empty((n,2,1024),dtype=np.float32)
    for begin in range(0,n,2048):
        s=slice(begin,min(begin+2048,n));original[s]=e.source_values(d,members['source_row'][s],members['class_id'][s],members['source_snr_db'][s])
    normalized,rms=rms_only(original)
    # Only original labels/predictions/logits are read for the registered comparison.
    previous={tag:np.empty(n,dtype=np.int64) for tag in ('source','guard')};source_logits=np.empty((n,24),dtype=np.float32)
    for chunk in np.unique(members['validation_rank']//2048):
        ii=np.flatnonzero(members['validation_rank']//2048==chunk);start=int(chunk)*2048;pos=members['validation_rank'][ii]-start
        for tag,folder in [('source',infer/'rml2018a'/variant/'source'),('guard',infer/'rml2018a'/variant)]:
            path=folder/f'rows-{start:07d}.npz';e.c.require(e.backend.digest(path)==e.read(path.with_suffix('.json'))['sha256'],'parent prediction SHA')
            with np.load(path) as f:
                e.c.require(np.array_equal(f['source_row'][pos],members['source_row'][ii]),'same members')
                previous[tag][ii]=f[tag+'_prediction'][pos]
                if tag=='source':source_logits[ii]=f['source_logits'][pos]
    for key in ('TMPDIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR'):
        p=scratch/key;p.mkdir(parents=True,exist_ok=True);os.environ[key]=str(p)
    e.capture.pilot().helpers()[0].spark_off();e.resource_gate()
    lease=GpuLease(scratch/'gpu-gate','mamba');token=asyncio.run(lease.acquire(time.monotonic()+10,request='source-rms/'+variant))
    started=time.monotonic()
    try:
        package=Path(spec['package']);model,torch=e.backend.load_frozen_model(package,e.read(package/'config.json'),variant=='amc_mamba_d10',d['class_names'])
        def predict(x):
            with torch.inference_mode():return model(torch.from_numpy(np.ascontiguousarray(x)).cuda()).float().cpu().numpy()
        probe=np.unique(np.linspace(0,n-1,128,dtype=int));old=predict(original[probe])
        e.c.require(np.allclose(old,source_logits[probe],atol=2e-4,rtol=2e-4) and np.array_equal(old.argmax(1),previous['source'][probe]),'original-source baseline replay')
        logits=np.empty((n,24),dtype=np.float32)
        for start in range(0,n,128):
            e.c.require(time.monotonic()-started<plan['deadline_seconds'] and not (root/'STOP').exists(),'finite intervention deadline/STOP')
            if start%2048==0:e.resource_gate()
            end=min(start+128,n);logits[start:end]=predict(normalized[start:end])
            e.c.require(np.isfinite(logits[start:end]).all(),'finite logits')
        single_ids=np.linspace(0,n-1,8,dtype=int);single=np.concatenate([predict(normalized[i:i+1]) for i in single_ids])
        e.c.require(np.allclose(single,logits[single_ids],atol=2e-4,rtol=2e-4) and np.array_equal(single.argmax(1),logits[single_ids].argmax(1)),'normalized batch/single gate')
        y=members['class_id'];pred=logits.argmax(1);groups=[]
        for cls in CLASSES:
            for bin_id in [-1,*range(9)]:
                m=(y==cls)&((members['reference_bin']==bin_id) if bin_id>=0 else True);total=int(m.sum())
                groups.append(dict(class_id=cls,reference_bin=bin_id,rows=total,
                    original_correct=int(((previous['source']==y)&m).sum()),rms_correct=int(((pred==y)&m).sum()),
                    guard_correct=int(((previous['guard']==y)&m).sum()),source_correct_to_rms_wrong=int(((previous['source']==y)&(pred!=y)&m).sum()),
                    rms_guard_top1_agreement=int(((pred==previous['guard'])&m).sum())))
        e.save_shard(out/'predictions.npz',dict(**members,source_rms=rms,original_prediction=previous['source'],guard_prediction=previous['guard'],
            rms_prediction=pred,rms_logits=logits,original_input_sha256=np.array(e.c.digest(original.tobytes())),rms_input_sha256=np.array(e.c.digest(normalized.tobytes()))))
        torch.cuda.synchronize()
        report=dict(model=variant,plan_sha256=e.backend.digest(root/'plan.json'),checkpoint_sha256=spec['files'][str(package/'best.pt')],rows=n,
            baseline_probe_rows=len(probe),baseline_max_abs_logit_error=float(np.max(abs(old-source_logits[probe]))),normalized_single_probe_rows=len(single_ids),
            normalized_max_abs_logit_error=float(np.max(abs(single-logits[single_ids]))),new_forward_rows=n+len(probe)+len(single_ids),groups=groups,
            predictions_sha256=e.backend.digest(out/'predictions.npz'),elapsed_seconds=time.monotonic()-started,precision='FP32 TF32 off',strict_load=True,
            scope='source-only scalar normalization; no new received-input inference/RF/training')
        e.atomic(out/'result.json',report);print(str(out/'result.json'),flush=True)
    finally:lease.release(token);lease.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run']);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--inference',type=Path);p.add_argument('--sinr',type=Path);p.add_argument('--variant');p.add_argument('--scratch',type=Path);a=p.parse_args()
    if a.command=='prepare':prepare(a.root,a.inference,a.sinr)
    else:run(a.root,a.variant,a.scratch)
