#!/usr/bin/env python3
"""D10 partial cancellation with candidate-specific RMS, fixed diagnostic members; no RF or training."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import sys
import time
import types
import numpy as np
import h5py
import rml2018a_model_collection_eval as ev

MODEL = Path('/home/jetson/models/d10/rml2018a/d10_2018a_seed42_nw8')
D10 = Path('/var/tmp/sdrharness-dev/rml2018a-d10-replay-20260922')
PARENT = Path('/var/tmp/sdrharness-dev/rml2018a-offline-baseline-20260916')


def ah(x):
    return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def summarize(truth, logits, mask):
    good={k:v.argmax(1)==truth for k,v in logits.items()}
    return dict(rows=int(mask.sum()),correct={k:int((v&mask).sum()) for k,v in good.items()},
                versus_raw={k:dict(corrected=int((~good['raw']&v&mask).sum()),regressed=int((good['raw']&~v&mask).sum())) for k,v in good.items()})


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('1800s deadline')))
    signal.alarm(1800)
    cache = out/'cache'
    for key in ('TMPDIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR','XDG_CACHE_HOME'):
        p=cache/key; p.mkdir(parents=True); os.environ[key]=str(p)
    src=MODEL/'source_03fa833'
    manifest=json.loads((src/'SOURCE_MANIFEST.json').read_text())
    identities=[ev.identity(src/name,sha) for name,sha in manifest['files'].items()]
    identities += [ev.identity(MODEL/'best.pt','5d217592cabab54be4352d8ebddcc47eb9cf9b7ea81d1010027e8dd213546b81'),ev.identity(MODEL/'config.json'),ev.identity(src/'SOURCE_MANIFEST.json'),ev.identity(__file__),ev.identity(PARENT/'predictions.npz'),ev.identity(PARENT/'input-identities.json')]
    audit=json.loads((ev.REPO/'docs/evidence/RML2018A_D10_REPLAY_2026-09-22.json').read_text())
    for rec in audit['files']: ev.identity(rec['path'],rec['sha256'])
    seal=json.loads((PARENT/'retention.json').read_text())
    rec=next(r for r in seal['files'] if Path(r['path']).name=='baseline-rows.json')
    identities += [ev.identity(D10/'predictions.npz'),ev.identity(D10/'inputs.json'),ev.identity(rec['path'],rec['sha256'])]
    with np.load(D10/'predictions.npz',allow_pickle=False) as f: reference={k:f[k].copy() for k in f.files}
    cfg=json.loads((MODEL/'config.json').read_text())
    with np.load(PARENT/'predictions.npz',allow_pickle=False) as p:
        old={k:p[k].copy() for k in p.files}
    ids=old['source_row']; y=old['truth']; z=old['source_snr_db']
    val,split=ev.load_validation_split(ev.ASSET/'splits/server-seed42-20260914/RML2018a_split_seed42_tr700_val150_te150.npz',ev.SEED42_SPLIT_SHA)
    ev.require(len(ids)==2496 and len(np.unique(ids))==2496 and np.isin(ids,val).all(),'fixed members')
    ev.require(np.array_equal(np.searchsorted(val,ids),old['validation_rank']),'validation rank')
    plan=dict(schema='d10-partial-cancellation-v1',identities=identities,split=split,source_ids_sha256=ah(ids),rows=2496,source_commit=manifest['commit'],
              budget=dict(seconds=1800,host_bytes=8*1024**3,gpu_bytes=4*1024**3,output_bytes=128*1024**2,free_bytes=shutil.disk_usage(out).free),
              numerical_gate=dict(atol=2e-4,rtol=2e-4,top1_agreement=1.0),batch_size=128,precision='fp32',
              planes=['raw','alpha25','alpha50','alpha75','guard'],design='alpha=0,.25,.5,.75,1; reconstruct R and G with archived per-window ADC RMS, mix (1-alpha)*R+alpha*G, normalize each mixed window; fixed raw-reference receive SINR bins; descriptive diagnostic only, no adaptive threshold or training',no_training=True,no_rf=True,production_changes=False)
    ev.require(plan['budget']['free_bytes']>1024**3,'disk budget')
    ev.atomic(out/'plan.json',plan)
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
    records=json.loads((PARENT/'input-identities.json').read_text())
    data={}; input_audit={}
    for plane in ('raw','guard'):
        path=ev.ASSET/'datasets/rml2018a/RML2018a.hdf5' if plane=='source' else ev.CLEAN/f'RadioML2018A_RX_{plane}_1024_per_window_RMS_v1.h5'
        rec=next(r for r in records if r['path']==str(path)); ev.unchanged(rec)
        with h5py.File(path,'r') as f:
            if plane=='source':
                x=f['X'][ids].transpose(0,2,1)
                ev.require(np.array_equal(f['Y'][ids].argmax(1),y) and np.array_equal(f['Z'][ids].reshape(-1),z),'source labels')
            else:
                allids=f['source_row'][:]; order=np.argsort(allids); at=np.searchsorted(allids[order],ids); rows=order[at]
                ix=np.argsort(rows); rev=np.argsort(ix); rows_sorted=rows[ix]
                ev.require(np.array_equal(allids[rows],ids),'source mapping')
                x=f['iq'][rows_sorted][rev]
                for key,target in [('class_id',y),('source_snr_db',z)]:
                    ev.require(np.array_equal(f[key][rows_sorted][rev],target),'RX labels')
                ev.require(f['usable'][rows_sorted].all() and f['strict_quality_pass'][rows_sorted].all(),'quality membership')
            x=np.ascontiguousarray(x,dtype=np.float32)
            ev.require(x.shape==(2496,2,1024) and np.isfinite(x).all(),'input contract')
            rms=np.sqrt(np.mean(np.sum(x.astype(np.float64)**2,axis=1),axis=1))
            ev.require(np.allclose(rms,old[plane+'_rms'],atol=2e-6,rtol=2e-6),'parent RMS')
            data[plane]=x; input_audit[plane]=dict(parent_identity=rec,selected_iq_sha256=ah(x),rms_max_error=float(np.max(np.abs(rms-old[plane+'_rms']))))
        ev.unchanged(rec)
    previous=json.loads((D10/'inputs.json').read_text())
    for plane in data:ev.require(input_audit[plane]['selected_iq_sha256']==previous[plane]['selected_iq_sha256'],'exact original D10 IQ')
    for key in ('source_row','truth','source_snr_db','validation_rank'):ev.require(np.array_equal(old[key],reference[key]),'D10 member identity')
    rows=sorted(json.loads((PARENT/'baseline-rows.json').read_text()),key=lambda r:r['index'])
    ev.require([r['index'] for r in rows]==list(range(2496)) and np.array_equal(ids,[r['source_row'] for r in rows]),'RMS lineage')
    raw_rms=np.array([r['planes']['raw']['received_rms'] for r in rows])
    guard_rms=np.array([r['planes']['guard']['received_rms'] for r in rows])
    gain=raw_rms/guard_rms
    ev.require(np.isfinite(gain).all() and (gain>0).all(),'finite positive fixed gain')
    R=data['raw'].astype(float)*raw_rms[:,None,None]
    G=data['guard'].astype(float)*guard_rms[:,None,None]
    for name,alpha in [('alpha25',.25),('alpha50',.5),('alpha75',.75)]:
        mixed=(1-alpha)*R+alpha*G
        rms=np.sqrt(np.mean(np.sum(mixed**2,axis=1),axis=1))
        ev.require(np.isfinite(rms).all() and (rms>0).all(),'candidate RMS')
        data[name]=np.asarray(mixed/rms[:,None,None],dtype=np.float32)
        ev.require(np.max(abs(np.sqrt(np.mean(np.sum(data[name].astype(float)**2,axis=1),axis=1))-1))<2e-6,'unit RMS')
        input_audit[name]=dict(selected_iq_sha256=ah(data[name]),alpha=alpha,rms_min=float(rms.min()),rms_max=float(rms.max()))
    ev.atomic(out/'inputs.json',input_audit)
    # Same real inputs, singleton vs batch, covering every class and source SNR.
    probe=np.unique(np.r_[np.arange(0,2496,104),np.arange(0,104,4)])
    checks={}; logits={}
    for name in plan['planes']:
        x=data[name]; bat=ev.predict(model,x[probe],torch,'fp32')
        single=np.concatenate([ev.predict(model,x[i:i+1],torch,'fp32') for i in probe])
        ok=np.allclose(bat,single,atol=2e-4,rtol=2e-4) and np.array_equal(bat.argmax(1),single.argmax(1))
        checks[name]=dict(passed=bool(ok),max_abs=float(np.abs(bat-single).max()),rows=len(probe))
        ev.atomic(out/'numerical.json',checks); ev.require(ok,'batch numerical gate')
        logits[name]=np.concatenate([ev.predict(model,x[a:a+128],torch,'fp32') for a in range(0,len(x),128)])
        ev.require(np.allclose(logits[name][probe],single,atol=2e-4,rtol=2e-4) and np.array_equal(logits[name][probe].argmax(1),single.argmax(1)),'production batch gate')
        print(name,int((logits[name].argmax(1)==y).sum()),flush=True)
        ev.require(not (out/'STOP').exists(),'STOP requested')
    ev.atomic(out/'baseline.json',{p:dict(max_abs=float(abs(logits[p]-reference[p+'_logits']).max()),top1_agreement=float(np.mean(logits[p].argmax(1)==reference[p+'_logits'].argmax(1)))) for p in ('raw','guard')})
    for p in ('raw','guard'):ev.require(np.allclose(logits[p],reference[p+'_logits'],atol=2e-4,rtol=2e-4) and np.array_equal(logits[p].argmax(1),reference[p+'_logits'].argmax(1)),'archived D10 baseline')
    np.savez(out/'predictions.npz',gain=gain,raw_rms=raw_rms,guard_rms=guard_rms,source_row=ids,truth=y,source_snr_db=z,validation_rank=old['validation_rank'],**{k+'_logits':v for k,v in logits.items()})
    sinr=np.array([r['planes']['raw']['conditional_effective_sinr_db'] for r in rows])
    edges=np.array([-20,-15,-10,-5,0,5,10,15,20]);labels=['<-20','[-20,-15)','[-15,-10)','[-10,-5)','[-5,0)','[0,5)','[5,10)','[10,15)','[15,20)','>=20','invalid']
    bins=np.where(np.isfinite(sinr),np.searchsorted(edges,sinr,side='right'),10)
    masks={'overall':np.ones(len(ids),bool),'raw_sinr_below0':np.isfinite(sinr)&(sinr<0)}
    masks.update({label:bins==i for i,label in enumerate(labels)})
    result={k:summarize(y,logits,m) for k,m in masks.items()}
    ev.atomic(out/'sinr.json',dict(source_row=ids.tolist(),raw_conditional_sinr_db=sinr.tolist(),labels=labels))
    result['seconds']=time.monotonic()-start; result['rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024; result['cuda_bytes']=torch.cuda.max_memory_allocated()
    ev.require(result['rss_bytes']<=8*1024**3 and result['cuda_bytes']<=4*1024**3,'memory budget')
    for rec in identities: ev.unchanged(rec)
    ev.atomic(out/'results.json',result); print(json.dumps(result['overall']),flush=True)
    signal.alarm(0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--out',type=Path,required=True)
    main(parser.parse_args().out)
