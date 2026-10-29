#!/usr/bin/env python3
"""Bounded four-window replay/batch compatibility proof on saved IQ only."""
import argparse
import asyncio
import importlib.util
import os
from pathlib import Path
import shutil
import time
import numpy as np
import rml2018a_snr_infer as m
import rml2018a_four_window as four
import rml2018a_infer_batch as batch


def main(root,campaign):
    m.c.require(root.parent==Path('/var/tmp/sdrharness-dev') and root.resolve()==root and not root.exists(),'new validation root')
    groups=m.corpus(campaign);root.mkdir(mode=0o700);scratch=root/'scratch';scratch.mkdir(mode=0o700)
    os.environ.update(TMPDIR=str(scratch),XDG_CACHE_HOME=str(scratch),CUDA_CACHE_PATH=str(scratch/'cuda'),
                      TRITON_CACHE_DIR=str(scratch/'triton'),PYTHONDONTWRITEBYTECODE='1')
    plan=dict(method=four.METHOD,campaign=str(campaign),acquisition_sha256=m.c.file_hash(campaign/'acquisition-complete.json'),
              samples=864,joint_decisions=216,batch_size=1024,source_snrs=[30,0,-20],classes=list(range(24)),tags=list(m.TAGS),
              selection='First four contiguous payloads of first block of each class/Z; all three input planes',
              deadline_seconds=1800,maximum_model_windows=20000,maximum_rf_samples=0,
              gates=dict(joint_top1_mismatches=0,max_abs_logit=0.0625,max_abs_softmax=0.005,peak_reserved_bytes=40*1024**3),
              software=m.software(),profile_sha256=m.c.file_hash(m.PROFILE))
    m.atomic_json(root/'plan.json',plan);started=time.monotonic();calls=0;backend=None;token=None;lease=None
    def check():m.c.require(time.monotonic()-started<1800 and not (root/'STOP').exists(),'validation deadline/STOP')
    def progress(n):
        nonlocal calls
        calls+=n;m.c.require(calls<=20000,'validation model window bound')
    try:
        m.spark_stopped();arrays=[];lineage=[]
        for z in plan['source_snrs']:
            g=next(g for g in groups if g['snr']==z);index=m.read(Path(g['root'])/'index.json')
            for cid in range(24):
                check();data=m.load_block(g,index,cid*4);inputs,recipe=four.restore(g,cid*4,data)
                for tag in m.TAGS:
                    arrays.append(inputs[tag][:4]);lineage.append(dict(snr=z,class_id=cid,tag=tag,
                        source_rows=data[0][:4].tolist(),input_sha256=m.c.digest(inputs[tag][:4].tobytes()),recipe=recipe))
            print(f'restored source Z {z}: all 24 classes',flush=True)
        x=np.concatenate(arrays);m.c.require(x.shape==(864,2,1024),'validation coverage')
        m.atomic_json(root/'inputs.json',dict(groups=lineage,sha256=m.c.digest(x.tobytes())))
        from gpu_lease import GpuLease
        lease=GpuLease(scratch/'gpu-gate','mamba');token=asyncio.run(lease.acquire(time.monotonic()+10,request='four-window-proof'))
        spec=importlib.util.spec_from_file_location('four_validation_worker',m.SCRIPTS/'amc-mamba-worker.py')
        worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        backend=worker.RfV1Backend(m.PROFILE);torch=worker.torch
        m.c.require(all(v.dtype==torch.float32 for v in backend.model.parameters()) and not backend.model.training,'frozen FP32 eval')
        baseline=[];t=time.monotonic()
        for i,v in enumerate(x):
            check();baseline.append(backend.classify_logits(v)[0]);progress(1)
            if i%216==0:print(f'baseline {i}/864',flush=True)
        baseline=np.asarray(baseline,np.float32);single_seconds=time.monotonic()-t
        torch.cuda.reset_peak_memory_stats();t=time.monotonic()
        # Full CUDA batch and tail both exercised, with group-preserving repetition.
        expanded=np.tile(x,(2,1,1));observed=batch.infer(backend,expanded,1024,check,progress)
        reference=np.tile(baseline,(2,1));seconds=time.monotonic()-t
        def softmax(v):
            e=np.exp(v-v.max(1,keepdims=True));return e/e.sum(1,keepdims=True)
        a=reference.reshape(-1,4,24).mean(1,dtype=np.float64);b=observed.reshape(-1,4,24).mean(1,dtype=np.float64)
        result=dict(complete=True,single_seconds=single_seconds,batch_seconds=seconds,
            joint_top1_mismatches=int((a.argmax(1)!=b.argmax(1)).sum()),
            window_top1_mismatches=int((reference.argmax(1)!=observed.argmax(1)).sum()),
            max_abs_logit=float(abs(observed-reference).max()),max_abs_softmax=float(abs(softmax(a)-softmax(b)).max()),
            peak_reserved_bytes=torch.cuda.max_memory_reserved(),model_windows=calls,
            model_identity=backend.admission_identity,elapsed_seconds=time.monotonic()-started)
        result['passed']=all(result[k]<=v for k,v in plan['gates'].items())
        result['strict_historical_logit_pass']=result['max_abs_logit']<=1e-5
        np.savez(root/'predictions.npz',baseline=baseline,batch=observed,reference_group_logits=a,batch_group_logits=b)
        m.atomic_json(root/'benchmark.json',result);print(result,flush=True)
        m.c.require(result['passed'],'four-window compatibility failed')
    except BaseException as e:
        m.atomic_json(root/'failure.json',dict(error=repr(e),model_windows=calls));raise
    finally:
        if backend is not None:
            del backend;torch.cuda.synchronize();torch.cuda.empty_cache()
        if token is not None:lease.release(token)
        if lease is not None:lease.close()
        removed=[dict(path=str(v),bytes=v.stat().st_size) for v in scratch.rglob('*') if v.is_file()]
        m.c.require(scratch.resolve()==root/'scratch','exact scratch');shutil.rmtree(scratch)
        retained=[dict(path=str(v),bytes=v.stat().st_size,sha256=m.c.file_hash(v)) for v in sorted(root.rglob('*')) if v.is_file()]
        m.atomic_json(root/'retention.json',dict(purpose='Four-window numerical compatibility and replay provenance',
            parent_campaign=str(campaign),model_profile_sha256=plan['profile_sha256'],removed=removed,
            removed_bytes=sum(v['bytes'] for v in removed),retained=retained,retained_bytes=sum(v['bytes'] for v in retained),
            manual_delete_argv=['rm','-rf','--',str(root)],deletion_constraint='Do not delete while a dependent inference run uses this proof.'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--campaign',type=Path,required=True)
    a=p.parse_args();main(a.root,a.campaign)
