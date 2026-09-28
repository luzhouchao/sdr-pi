#!/usr/bin/env python3
"""Predeclared bounded checks of LO-only and near-zero-interior model responses."""
import argparse,asyncio,gc,os,time
from pathlib import Path
import h5py,numpy as np
import amc_hisar_8psk_diagnostic as a
from gpu_lease import GpuLease

def run(root,scratch):
    assert not (root/'followup-plan.json').exists()
    first=a.read(root/'complete.json');assert first['status']=='complete'
    parent=a.read(a.PARENT/'plan.json');d=next(x for x in parent['datasets'] if x['dataset']=='hisarmod2019');spec=next(x for x in parent['models'] if x['dataset']==d['dataset'] and x['variant']=='amc_mamba_d10')
    with np.load(a.SINR) as f:meta={k:f[k] for k in f.files}
    targets=np.flatnonzero((meta['class_id']==2)&(meta['reference_bin']==8));cross=[]
    for cl in range(26):
        if cl==2:continue
        candidates=np.flatnonzero((meta['class_id']==cl)&(meta['source_snr_db']==18));assert len(candidates)>=2
        cross.extend(candidates[[len(candidates)//3,2*len(candidates)//3]])
    cross=np.sort(cross);selected=np.sort(np.r_[targets,cross])
    plan=dict(parent_complete_sha256=a.digest(root/'complete.json'),posthoc=True,reason='Initial interventions isolate quiet-middle sensitivity; check whether LO alone yields 8PSK and whether edge-only inputs cause label bias across other classes',target_ranks=targets.tolist(),cross_class_ranks=cross.tolist(),cross_class_selection='two fixed rank quantiles per other class at source Z18; no prediction selection; Z is provenance only',views=['removed_lo_only','source_plus_fixed_1pct_complex_awgn','cross_class_matched','cross_class_middle_zero'],noise_seed=20260928,noise_complex_rms=.01,maximum_new_forward_rows=1000,total_budget_including_parent=8000,no_rf=True,no_training=True,not_deployable=True,script_sha256=a.digest(__file__))
    a.save(root/'followup-plan.json',plan)
    x=a.e.source_values(d,meta['source_row'][selected],meta['class_id'][selected],meta['source_snr_db'][selected]);z=a.unit(a.complex_values(x));target=np.isin(selected,targets);other=~target
    source=z[target];rng=np.random.default_rng(plan['noise_seed']);noise=(rng.normal(size=source.shape)+1j*rng.normal(size=source.shape))/np.sqrt(2)*.01
    with h5py.File(d['vds']) as f:raw=a.complex_values(f['inputs/raw'][targets]);guard=a.complex_values(f['inputs/guard'][targets])
    removed=raw*meta['raw_normalization_rms'][targets,None]-guard*meta['guard_normalization_rms'][targets,None]
    crosszero=z[other].copy();crosszero[:,a.MID]=0
    views={'removed_lo_only':a.unit(removed),'source_plus_fixed_1pct_complex_awgn':a.unit(source+noise),'cross_class_matched':z[other],'cross_class_middle_zero':a.unit(crosszero)}
    metrics=dict(target_papr_db=a.quant(10*np.log10((abs(x[target,0]+1j*x[target,1])**2).max(1)/np.mean(abs(x[target,0]+1j*x[target,1])**2,axis=1))),removed_lo_fraction_of_raw=a.quant(np.mean(abs(removed)**2,axis=1)/meta['raw_normalization_rms'][targets]**2))
    # Compare PAPR using all normal 8PSK source members, without model inference.
    normal=np.flatnonzero((meta['class_id']==2)&(meta['reference_bin']!=8));q=a.e.source_values(d,meta['source_row'][normal],meta['class_id'][normal],meta['source_snr_db'][normal]);q=a.complex_values(q);metrics['normal_8psk_papr_db']=a.quant(10*np.log10((abs(q)**2).max(1)/np.mean(abs(q)**2,axis=1)));del q;gc.collect()
    for path,sha in spec['files'].items():assert a.digest(path)==sha
    for key in ('TMPDIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR'):
        path=scratch/key;path.mkdir(parents=True,exist_ok=True);os.environ[key]=str(path)
    lease=GpuLease(scratch/'gpu-gate','mamba');token=asyncio.run(lease.acquire(time.monotonic()+10,request='hisar-followup'));predictions={};results={};forward=0
    try:
        a.e.resource_gate();package=Path(spec['package']);model,torch=a.e.backend.load_frozen_model(package,a.read(package/'config.json'),True,d['class_names'])
        for tag,v in views.items():
            parts=[]
            for start in range(0,len(v),128):
                with torch.inference_mode():out=model(torch.from_numpy(a.iq(v[start:start+128])).cuda()).float().cpu().numpy()
                assert np.isfinite(out).all();parts.append(out);forward+=len(out)
            logits=np.concatenate(parts);y=logits.argmax(1);rank=targets if tag in list(views)[:2] else cross;truth=meta['class_id'][rank]
            predictions[tag+'_logits']=logits;predictions[tag+'_ranks']=rank
            results[tag]=dict(rows=len(y),correct=int((y==truth).sum()),predicted_8psk=int((y==2).sum()),counts={d['class_names'][int(k)]:int(v) for k,v in zip(*np.unique(y,return_counts=True))})
        # Independently replay eight target source inputs against the sealed first stage.
        with torch.inference_mode():probe=model(torch.from_numpy(a.iq(source[:8])).cuda()).float().cpu().numpy()
        with np.load(root/'interventions.npz') as f:old=f['matched_logits'][f['is_target']][:8]
        assert np.allclose(probe,old,atol=2e-4,rtol=2e-4) and np.array_equal(probe.argmax(1),old.argmax(1));forward+=8
        assert forward<=1000 and forward+first['forward_rows']<=8000
    finally:lease.release(token);lease.close()
    with (root/'followup-predictions.npz').open('wb') as f:np.savez_compressed(f,**predictions)
    a.save(root/'followup-complete.json',dict(status='complete',results=results,metrics=metrics,forward_rows=forward,total_forward_rows=forward+first['forward_rows'],baseline_max_error=float(np.max(abs(probe-old))),plan_sha256=a.digest(root/'followup-plan.json')))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--scratch',type=Path,required=True);q=p.parse_args();run(q.root,q.scratch)
