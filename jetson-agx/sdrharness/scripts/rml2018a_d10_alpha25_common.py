#!/usr/bin/env python3
"""Fixed alpha=.25 on remaining common validation members; prior subset is a numerical control."""
import os, sys, json, time, signal, shutil, resource, types, hashlib
from pathlib import Path
import numpy as np
import h5py
import rml2018a_model_collection_eval as ev
from rml2018a_d10_replay import MODEL, ah
ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-d10-alpha25-common-20260926')
PARENT=Path('/var/tmp/sdrharness-dev/rml2018a-sinr-stratification-20260922')
REPLAY=Path('/var/tmp/sdrharness-dev/rml2018a-d10-partial-20260926')

def main():
    out=ROOT;out.mkdir(exist_ok=False);start=time.monotonic()
    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('4h deadline')));signal.alarm(14400)
    for key in ('TMPDIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR','XDG_CACHE_HOME'):
        p=out/'cache'/key;p.mkdir(parents=True);os.environ[key]=str(p)
    src=MODEL/'source_03fa833';manifest=json.loads((src/'SOURCE_MANIFEST.json').read_text())
    identities=[ev.identity(src/name,sha) for name,sha in manifest['files'].items()]
    identities += [ev.identity(MODEL/'best.pt','5d217592cabab54be4352d8ebddcc47eb9cf9b7ea81d1010027e8dd213546b81'),ev.identity(MODEL/'config.json'),ev.identity(__file__)]
    for audit,name in [('RML2018A_SINR_STRATIFICATION_2026-09-22.json',PARENT/'joined-predictions.npz'),('RML2018A_D10_PARTIAL_2026-09-26.json',REPLAY/'predictions.npz')]:
        seal=json.loads((ev.REPO/'docs/evidence'/audit).read_text());rec=next(r for r in seal['files'] if r['path']==str(name));identities.append(ev.identity(name,rec['sha256']))
    with np.load(PARENT/'joined-predictions.npz') as f:
        member={k:f[k] for k in ('source_row','truth','validation_rank','source_snr_db','raw_sinr_db','guard_sinr_db','subset_indices')}
    with np.load(REPLAY/'predictions.npz') as f:prior={k:f[k] for k in f.files}
    ids=member['source_row'];y=member['truth'];n=len(ids)
    val,split=ev.load_validation_split(ev.ASSET/'splits/server-seed42-20260914/RML2018a_split_seed42_tr700_val150_te150.npz',ev.SEED42_SPLIT_SHA)
    ev.require(n==369497 and len(np.unique(ids))==n and np.isin(ids,val).all(),'common validation members')
    ev.require(np.array_equal(np.searchsorted(val,ids),member['validation_rank']),'validation ranks')
    sub=member['subset_indices'];ev.require(np.array_equal(ids[sub],prior['source_row']),'prior mapping')
    cfg=json.loads((MODEL/'config.json').read_text())
    records=json.loads(Path('/var/tmp/sdrharness-dev/rml2018a-offline-baseline-20260916/input-identities.json').read_text())
    inputs=[r for r in records if '/rx-clean-' in r['path']]
    for rec in inputs:ev.unchanged(rec)
    plan=dict(rows=n,planes=['alpha25'],alpha=.25,primary_rows=367001,control_rows=2496,design='fixed alpha .25 with independently normalized mixed ADC-scale payload; remaining members primary, prior2496 numerical control; no tuning',identities=identities,input_identities=inputs,split=split,source_ids_sha256=ah(ids),batch_size=128,precision='fp32',tf32=False,gate=dict(atol=2e-4,rtol=2e-4,top1_agreement=1.0),budget=dict(seconds=14400,host_bytes=8*1024**3,gpu_bytes=4*1024**3,output_bytes=256*1024**2,free_bytes=shutil.disk_usage(out).free),no_rf=True,no_training=True,production_changes=False)
    ev.require(plan['budget']['free_bytes']>1024**3,'space');ev.atomic(out/'plan.json',plan)
    # Use only the explicitly supplied source namespaces, never the old D8 tree.
    sys.path.insert(0,str(src))
    for name in ('models','utils','datasets'):
        ev.require(name not in sys.modules,'namespace collision')
        mod=types.ModuleType(name); mod.__path__=[str(src/name)]; sys.modules[name]=mod
    from datasets.h5_iq_dataset import build_split_indices
    regenerated=build_split_indices(2555904,.7,.15,.15,42)
    ev.require(np.array_equal(regenerated['val'],val),'D10 split algorithm differs')
    import torch
    torch.set_num_threads(2); torch.set_num_interop_threads(1); torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32=False; torch.backends.cudnn.allow_tf32=False
    ev.require(torch.cuda.is_available(),'CUDA required')
    from models.d10 import AMCMambaD10
    model=AMCMambaD10(num_classes=24,**{k:cfg['resolved_config']['model'][k] for k in ev.FIELDS})
    ck=torch.load(MODEL/'best.pt',map_location='cpu',weights_only=True)
    ev.require(ck['selected_model_variant']=='amc_mamba_d10','variant')
    model.load_state_dict(ck['model_state'],strict=True)
    ev.require(sum(p.numel() for p in model.parameters())==cfg['model_parameters'],'parameter count')
    ev.require(model.encoder.backend==cfg['model_backend'],'real backend')
    model=model.eval().cuda()
    ev.atomic(out/'load.json',dict(strict=True,parameters=cfg['model_parameters'],backend=model.encoder.backend,torch=torch.__version__,cuda=torch.version.cuda,split_exact=True))
    print('strict load and split passed',flush=True)

    # Read selected receive powers only, never original source IQ.
    from contextlib import ExitStack
    with ExitStack() as stack:
        handles={};mapping={};powers={p:np.full(n,np.nan) for p in ('raw','guard')};rms_inputs=[]
        for plane in ('raw','guard'):
            rec=next(r for r in inputs if '_'+plane+'_' in r['path']);f=stack.enter_context(h5py.File(rec['path'],'r'));handles[plane]=f
            allids=f['source_row'][:];order=np.argsort(allids);rows=order[np.searchsorted(allids[order],ids)]
            ev.require(np.array_equal(allids[rows],ids),'source mapping');mapping[plane]=rows
            for key,target in [('class_id',y),('source_snr_db',member['source_snr_db'])]:ev.require(np.array_equal(f[key][:][rows],target),'labels')
            ev.require(f['usable'][:][rows].all() and f['strict_quality_pass'][:][rows].all(),'quality')
        f=handles['raw'];rows=mapping['raw'];file_ids=f['source_h5_index'][:][rows];block_ids=f['source_block_index'][:][rows];paths=f['source_h5_paths'].asstr()[:]
        metadata_sha=hashlib.sha256()
        for file_id in np.unique(file_ids):
            path=Path('/var/tmp/sdrharness-dev')/Path(paths[file_id]).relative_to('corpus')
            rec=next(r for r in records if r['path']==str(path));ev.unchanged(rec);rms_inputs.append(rec)
            with h5py.File(path,'r') as original:
                for block_id in np.unique(block_ids[file_ids==file_id]):
                    take=np.flatnonzero((file_ids==file_id)&(block_ids==block_id));g=original[f'blocks/{block_id:03d}'];allrows=g['source_row'][:];at=np.searchsorted(allrows,ids[take])
                    ev.require(np.array_equal(allrows[at],ids[take]),'power row identity')
                    ev.require(np.array_equal(g['class_id'][at],y[take]),'power labels')
                    for i,qbytes in zip(take,g['quality_json'][at]):
                        metadata_sha.update(ids[i:i+1].tobytes());metadata_sha.update(qbytes)
                        q=json.loads(qbytes)
                        for plane in ('raw','guard'):
                            powers[plane][i]=q[plane]['rx_sinr_diagnostics']['received_power_adc_squared']
                            ev.require(np.isclose(q[plane]['rx_sinr_db'],member[plane+'_sinr_db'][i],atol=2e-4,rtol=2e-4),'power SINR identity')
            ev.unchanged(rec);print('power metadata',int(file_id),int(np.isfinite(powers['raw']).sum()),flush=True)
        rms={p:np.sqrt(v) for p,v in powers.items()}
        for plane,v in rms.items():
            ev.require(np.isfinite(v).all() and (v>0).all(),'power positive complete')
            ev.require(np.allclose(v[sub],prior[plane+'_rms'],atol=2e-6,rtol=2e-6),'archived RMS gate')
        ev.atomic(out/'power-lineage.json',dict(inputs=rms_inputs,selected_metadata_sha256=metadata_sha.hexdigest(),prior_rms_max_error={p:float(abs(rms[p][sub]-prior[p+'_rms']).max()) for p in rms}))
        np.savez(out/'members.npz',**member,raw_rms=rms['raw'],guard_rms=rms['guard'])
        def read(take):
            data={}
            for plane,f in handles.items():
                r=mapping[plane][take];ix=np.argsort(r);v=np.ascontiguousarray(f['iq'][r[ix]][np.argsort(ix)],dtype=np.float32)
                ev.require(v.shape==(len(take),2,1024) and np.isfinite(v).all(),'input contract')
                ev.require(np.max(abs(np.sqrt(np.mean(np.sum(v.astype(float)**2,axis=1),axis=1))-1))<=2e-6,'input RMS')
                data[plane]=v.astype(float)*rms[plane][take,None,None]
            x=.75*data['raw']+.25*data['guard'];scale=np.sqrt(np.mean(np.sum(x*x,axis=1),axis=1))
            return np.ascontiguousarray(x/scale[:,None,None],dtype=np.float32)
        probe=sub[np.linspace(0,len(sub)-1,48,dtype=int)];x=read(probe)
        bat=ev.predict(model,x,torch,'fp32');single=np.concatenate([ev.predict(model,v[None],torch,'fp32') for v in x])
        ev.require(np.allclose(bat,single,atol=2e-4,rtol=2e-4) and np.array_equal(bat.argmax(1),single.argmax(1)),'singleton gate')
        ev.require(np.allclose(bat,prior['alpha25_logits'][np.linspace(0,len(sub)-1,48,dtype=int)],atol=2e-4,rtol=2e-4),'old probe logits')
        logits=np.empty((n,24),np.float32);io_order=np.argsort(mapping['raw']);h=hashlib.sha256();last=time.monotonic()
        for start_row in range(0,n,128):
            take=io_order[start_row:start_row+128];x=read(take);h.update(np.ascontiguousarray(ids[take]).tobytes());h.update(x.tobytes())
            logits[take]=ev.predict(model,x,torch,'fp32');ev.require(not (out/'STOP').exists(),'STOP requested')
            if time.monotonic()-last>30 or start_row+128>=n:
                done=min(start_row+128,n);ev.atomic(out/'progress.json',dict(done=done,total=n,elapsed_seconds=time.monotonic()-start));print('alpha25',done,n,round(time.monotonic()-start,1),flush=True);last=time.monotonic()
        ref=prior['alpha25_logits'];actual=logits[sub]
        ev.require(np.allclose(actual,ref,atol=2e-4,rtol=2e-4) and np.array_equal(actual.argmax(1),ref.argmax(1)),'2496 replay gate')
        ev.require(np.allclose(logits[probe],single,atol=2e-4,rtol=2e-4) and np.array_equal(logits[probe].argmax(1),single.argmax(1)),'production batch gate')
        checks=dict(rows=n,primary_rows=n-len(sub),prior_rows=len(sub),prior_max_abs=float(abs(actual-ref).max()),singleton_max_abs=float(abs(bat-single).max()),selected_input_stream_sha256=h.hexdigest(),correct=int((logits.argmax(1)==y).sum()))
        np.savez(out/'alpha25-predictions.npz',source_row=ids,validation_rank=member['validation_rank'],truth=y,logits=logits,predicted_class=logits.argmax(1))
        ev.atomic(out/'verification.json',checks)
    for rec in inputs+rms_inputs+identities:ev.unchanged(rec)
    stats=dict(seconds=time.monotonic()-start,rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,cuda_bytes=torch.cuda.max_memory_allocated(),checks=checks)
    ev.require(stats['rss_bytes']<8*1024**3 and stats['cuda_bytes']<4*1024**3,'memory')
    ev.require(sum(p.stat().st_size for p in out.rglob('*') if p.is_file())<256*1024**2,'output budget')
    ev.atomic(out/'complete.json',stats);signal.alarm(0);print(json.dumps(stats),flush=True)

if __name__=='__main__':main()
