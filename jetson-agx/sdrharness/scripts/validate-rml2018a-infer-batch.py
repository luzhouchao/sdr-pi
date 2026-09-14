#!/usr/bin/env python3
"""Finite saved-IQ batch benchmark; never performs RF or changes model assets."""
import argparse
import asyncio
import importlib.util
import os
from pathlib import Path
import time

import numpy as np
import rml2018a_snr_infer as m
import rml2018a_infer_batch as batch


def main(root,campaign):
    m.c.require(root.parent == Path('/var/tmp/sdrharness-dev') and root.resolve() == root and
                not root.exists(), 'new validation root')
    groups = m.corpus(campaign)
    root.mkdir(mode=0o700);scratch=root/'scratch';scratch.mkdir(mode=0o700)
    os.environ.update(TMPDIR=str(scratch),XDG_CACHE_HOME=str(scratch),CUDA_CACHE_PATH=str(scratch/'cuda'),
                      TRITON_CACHE_DIR=str(scratch/'triton'),PYTHONDONTWRITEBYTECODE='1')
    plan=dict(campaign=str(campaign),acquisition_sha256=m.c.file_hash(campaign/'acquisition-complete.json'),
              source_snrs=[30,0,-20],classes=list(range(24)),tags=list(m.TAGS),
              selection='For each Z/class/tag take first 5 valid rows in first class block; evenly select1024 slots from1080.',
              samples=1024,benchmark_rows=8192,batches=[1024,4096,8192],maximum_model_windows=200000,deadline_seconds=1800,
              gates=dict(top1_mismatches=0,max_abs_logit=0.0625,max_abs_softmax=0.005,
                         peak_reserved_bytes=40*1024**3,min_speedup=2),
              strict_historical_logit_atol=1e-5,
              note='Engineering batching bridge; strict historical logit gate separately reported, never rewritten.',
              software=m.software(),profile_sha256=m.c.file_hash(m.PROFILE))
    m.atomic_json(root/'plan.json',plan)
    started=time.monotonic();deadline=started+1800
    def check():m.c.require(time.monotonic()<deadline and not (root/'STOP').exists(),'benchmark deadline/STOP')
    m.spark_stopped()
    from gpu_lease import GpuLease
    lease=GpuLease(scratch/'gpu-gate','mamba');token=None;backend=None
    try:
        token=asyncio.run(lease.acquire(time.monotonic()+10,request='batch-inference-validation'))
        data=[];lineage=[]
        for z in plan['source_snrs']:
            g=next(g for g in groups if g['snr']==z);index=m.read(Path(g['root'])/'index.json')
            for cid in range(24):
                rows,ids,inputs,masks,q=m.load_block(g,index,cid*4)
                for tag in m.TAGS:
                    for i in np.flatnonzero(masks[tag])[:5]:
                        data.append(inputs[tag][i]);lineage.append(dict(snr=z,class_id=cid,tag=tag,
                            row=int(rows[i]),input_sha256=m.c.digest(inputs[tag][i].tobytes())))
        # Evenly sample the 1080 slots, so all classes/Z/tags remain represented.
        selected=np.linspace(0,len(data)-1,1024,dtype=int)
        x=np.stack([data[i] for i in selected]);lineage=[lineage[i] for i in selected]
        m.c.require(len(x)==1024 and len({(v['snr'],v['class_id'],v['tag']) for v in lineage})==216,
                    'all24/all3Z/all3planes validation coverage')
        m.atomic_json(root/'inputs.json',dict(rows=lineage,sha256=m.c.digest(x.tobytes())))
        spec=importlib.util.spec_from_file_location('batch_validation_worker',m.SCRIPTS/'amc-mamba-worker.py')
        worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
        backend=worker.RfV1Backend(m.PROFILE);torch=worker.torch
        t=time.monotonic();baseline=[]
        for i,v in enumerate(x):
            check();baseline.append(backend.classify_logits(v)[0])
            if i%256==0:print(f'single-window baseline {i}/1024',flush=True)
        baseline=np.array(baseline,dtype=np.float32);single_seconds=time.monotonic()-t
        np.save(root/'baseline.npy',baseline,allow_pickle=False)
        def softmax(y):
            y=y.astype(np.float64);e=np.exp(y-y.max(axis=1,keepdims=True));return e/e.sum(axis=1,keepdims=True)
        results=[]
        expanded=np.tile(x,(8,1,1));reference=np.tile(baseline,(8,1))
        for size in plan['batches']:
            check();backend._snr_graphs={};torch.cuda.empty_cache();torch.cuda.reset_peak_memory_stats()
            # One full-size warmup, then two measured passes in alternating data order.
            batch.infer(backend,expanded[:size],size,check)
            timings=[];values=[]
            fallback_before=getattr(backend,'_snr_fallback_windows',0)
            for reverse in (False,True):
                t=time.monotonic();v=batch.infer(backend,expanded[::-1].copy() if reverse else expanded,size,check)
                timings.append(time.monotonic()-t);values.append(v[::-1].copy() if reverse else v)
            result=dict(batch_size=size,seconds=timings,windows_per_second=8192/min(timings),
                        speedup=single_seconds*8/max(timings),peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                        peak_reserved_bytes=torch.cuda.max_memory_reserved(),
                        max_abs_logit=max(float(abs(v-reference).max()) for v in values),
                        max_abs_softmax=max(float(abs(softmax(v)-softmax(reference)).max()) for v in values),
                        top1_mismatches=max(int((v.argmax(1)!=reference.argmax(1)).sum()) for v in values),
                        fallback_windows=getattr(backend,'_snr_fallback_windows',0)-fallback_before,
                        repeat_max_abs_logit=float(abs(values[0]-values[1]).max()))
            result['strict_historical_logit_pass']=result['max_abs_logit']<=1e-5
            gates=plan['gates']
            result['passed']=(result['top1_mismatches']==0 and result['max_abs_logit']<=gates['max_abs_logit'] and
                result['max_abs_softmax']<=gates['max_abs_softmax'] and result['peak_reserved_bytes']<=gates['peak_reserved_bytes'] and
                result['speedup']>=gates['min_speedup'])
            np.save(root/f'batch-{size}.npy',values[0],allow_pickle=False)
            results.append(result);print(result,flush=True)
            m.atomic_json(root/'benchmark.json',dict(complete=False,single_seconds=single_seconds,results=results))
        passed=[v for v in results if v['passed']]
        selected=max(passed,key=lambda v: v['windows_per_second'])['batch_size'] if passed else None
        m.atomic_json(root/'benchmark.json',dict(complete=True,single_seconds=single_seconds,results=results,
            selected_batch_size=selected,model_identity=backend.admission_identity,elapsed_seconds=time.monotonic()-started))
    finally:
        if backend is not None:
            del backend;torch.cuda.synchronize();torch.cuda.empty_cache()
        if token is not None:lease.release(token)
        lease.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--campaign',type=Path,required=True);a=parser.parse_args();main(a.root,a.campaign)
