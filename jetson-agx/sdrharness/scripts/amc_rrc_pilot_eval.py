#!/usr/bin/env python3
"""Strict seed42 FP32 engineering inference after completed finite RF captures."""
import argparse
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import types
import h5py
import numpy as np
from gpu_lease import GpuLease

FIELDS=('d_model','dropout','use_real_mamba','mamba_d_state','mamba_d_conv','mamba_expand','mamba_headdim')

def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        while b:=f.read(8388608):h.update(b)
    return h.hexdigest()

def run(root,variant,scratch,normalization="rms"):
    if normalization not in ("rms","native"):raise ValueError("normalization contract")
    plan=json.loads((root/'plan.json').read_text())
    execution=json.loads((root/'execution.json').read_text())
    if execution['status']!='completed' or not execution['restored'] or not execution['cpu_stopped']:
        raise ValueError('capture not completed/restored')
    dataset=plan['dataset']; package=Path('/home/jetson/models/amc')/dataset/variant
    cfg=json.loads((package/'config.json').read_text()); classes=plan['source']['contract']['class_names']
    d10=variant=='amc_mamba_d10'
    if cfg['resolved_config']['data']['seed']!=42 or cfg['resolved_config']['data']['num_classes']!=len(classes):
        raise ValueError('configuration seed/class count')
    if d10:
        identity=json.loads((package/'deployment_manifest.json').read_text())
        if identity['seed']!=42 or identity['class_names']!=classes:raise ValueError('seed/class mapping')
    else:
        identity=next(v for v in json.loads(Path('/home/jetson/models/amc/verification.json').read_text()) if v['dataset']==dataset and v['variant']==variant)
    if digest(package/'best.pt')!=identity['sha256']:raise ValueError('checkpoint changed')
    out=root/('inference-native' if normalization=='native' else 'inference')/variant
    if out.exists():raise ValueError('fresh inference output required')
    out.mkdir(parents=True)
    scratch.mkdir(parents=True,exist_ok=True)
    for name in ('TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR','TMPDIR'):
        p=scratch/name;p.mkdir(exist_ok=True);os.environ[name]=str(p)
    source=package/('source_03fa833' if d10 else 'source')
    for name in ('models','utils'):
        if name in sys.modules:raise ValueError('namespace already loaded')
        m=types.ModuleType(name);m.__path__=[str(source/name)];sys.modules[name]=m
    lease=GpuLease(scratch/'gpu-gate','mamba');token=asyncio.run(lease.acquire(time.monotonic()+10,request=dataset+'/'+variant))
    try:
        import torch
        torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(0)
        torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
        torch.backends.cudnn.benchmark=False
        if not torch.cuda.is_available():raise ValueError('CUDA required')
        cls=getattr(importlib.import_module('models.d10' if d10 else 'models.baselines.'+variant.removeprefix('baseline_')),cfg['selected_model_class'])
        kwargs={k:cfg['resolved_config']['model'][k] for k in FIELDS}
        if not d10:kwargs['model_variant']=variant
        model=cls(num_classes=len(classes),**kwargs)
        state=torch.load(package/'best.pt',map_location='cpu',weights_only=True)
        model.load_state_dict(state['model_state'],strict=True)
        if sum(p.numel() for p in model.parameters())!=cfg['model_parameters'] or model.encoder.backend!=cfg['model_backend']:
            raise ValueError('parameters/backend mismatch')
        model=model.eval().cuda();result={};saved={}
        with h5py.File(root/'corpus/processed.h5','r') as f:
            blocks=list(f['blocks'].values())
            y=np.concatenate([b['class_id'][:] for b in blocks]);ids=np.concatenate([b['source_row'][:] for b in blocks]);saved.update(class_id=y,source_row=ids)
            for tag in ('raw','guard'):
                x=np.concatenate([b['inputs'][tag][:] for b in blocks]);valid=np.concatenate([b['valid'][tag][:] for b in blocks]);indices=np.flatnonzero(valid)
                if not np.isfinite(x[valid]).all():raise ValueError('nonfinite valid input')
                if normalization=='native' and dataset in ('rml2016a','rml2016b'):
                    # Frozen dataset reader preserves sum(abs(IQ))=1. Use RX only.
                    denominator=np.sqrt(np.sum(x[valid].astype(np.float64)**2,axis=1)).sum(axis=1)
                    if not np.all(denominator>0):raise ValueError('zero native denominator')
                    x[valid]=(x[valid]/denominator[:,None,None]).astype(np.float32)
                logits=np.full((len(x),len(classes)),np.nan,dtype=np.float32)
                with torch.inference_mode():
                    for begin in range(0,len(indices),32):
                        ii=indices[begin:begin+32];logits[ii]=model(torch.from_numpy(np.ascontiguousarray(x[ii])).cuda()).float().cpu().numpy()
                    # Actual RF inputs must also satisfy a batch/single numerical gate.
                    probe=indices[np.linspace(0,len(indices)-1,min(4,len(indices)),dtype=int)]
                    single=np.concatenate([model(torch.from_numpy(np.ascontiguousarray(x[i:i+1])).cuda()).float().cpu().numpy() for i in probe])
                if not np.isfinite(logits[valid]).all() or not np.allclose(single,logits[probe],atol=2e-4,rtol=2e-4) or not np.array_equal(single.argmax(1),logits[probe].argmax(1)):
                    raise ValueError('actual RF batch/single gate')
                pred=np.full(len(x),-1);pred[valid]=logits[valid].argmax(1);correct=int(((pred==y)&valid).sum())
                saved.update({tag+'_logits':logits,tag+'_prediction':pred,tag+'_valid':valid})
                result[tag]=dict(total_rows=len(x),valid_rows=int(valid.sum()),correct=correct,accuracy_all_rows=correct/len(x),accuracy_valid_rows=correct/int(valid.sum()),input_sha256=hashlib.sha256(x.tobytes()).hexdigest(),batch_single_gate=True)
        np.savez_compressed(out/'predictions.npz',**saved)
        report=dict(dataset=dataset,variant=variant,seed=42,checkpoint_sha256=identity['sha256'],config_sha256=digest(package/'config.json'),processed_sha256=digest(root/'corpus/processed.h5'),plan_sha256=digest(root/'plan.json'),script_sha256=digest(__file__),class_names=classes,input_normalization=('sum_abs_iq_one' if normalization=='native' and dataset in ('rml2016a','rml2016b') else 'complex_rms_one'),precision='FP32 TF32 disabled',backend=model.encoder.backend,strict_load=True,production_admission=False,planes=result)
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
        torch.cuda.synchronize()
    finally:
        lease.release(token);lease.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--normalization',choices=['rms','native'],default='rms');p.add_argument('--root',type=Path,required=True);p.add_argument('--variant',required=True);p.add_argument('--scratch',type=Path,required=True);a=p.parse_args();run(a.root,a.variant,a.scratch,a.normalization)
