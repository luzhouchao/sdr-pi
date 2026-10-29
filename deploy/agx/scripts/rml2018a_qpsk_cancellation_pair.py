#!/usr/bin/env python3
"""Fixed new-seed QPSK cancellation, two frozen models in isolated processes."""
import argparse,json,hashlib,os,signal,sys,types,shutil
from pathlib import Path
import numpy as np
import rml2018a_d10_synthetic as s
import rml2018a_synthetic_physical as physical

ev=s.ev
PLANES=('clean',)+s.PLANES


def data():
    clean=[s.generate('QPSK',203009260+i) for i in range(64)]
    arrays={k:[] for k in s.PLANES};records=[]
    for i,z in enumerate(clean):
        for j,snr in enumerate((-10,0,10,20)):
            for sir in (-10,0,10):
                variants,rec=s.channel(z,203109260+i*100+j,snr,sir)
                rec.update(base_id=i,seed=203009260+i)
                records.append(rec)
                for key in s.PLANES:arrays[key].append(variants[key])
    arrays={k:s.tensor(np.asarray(v)) for k,v in arrays.items()}
    arrays['clean']=s.tensor(np.asarray(clean))
    return arrays,records


def prepare(root):
    ev.require(root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev'),'canonical root');root.mkdir(exist_ok=False)
    old=Path('/var/tmp/sdrharness-dev/rml2018a-d10-synthetic-20260926/plan.json')
    identities=json.loads(old.read_text())['identities']+[ev.identity(__file__),ev.identity(physical.__file__)]
    manifest=json.loads((ev.COLLECTION/'manifest.json').read_text())
    spec=next(v for v in manifest['models'] if v['variant']=='baseline_cnn2_stable' and v['seed']==42)
    identities.append(ev.identity(ev.COLLECTION/'manifest.json'))
    for rec in manifest['transferred_files']:
        if rec['relative'].startswith(('source/','baseline_cnn2_stable/seed42/')):identities.append(ev.identity(ev.COLLECTION/rec['relative'],rec['sha256']))
    for rec in identities:ev.identity(rec['path'],rec['sha256'])
    ev.require(shutil.disk_usage(root).free>1024**3,'space')
    ev.atomic(root/'plan.json',dict(schema='qpsk-cancellation-pair-v1',identities=identities,cnn2=spec,
        base_windows=64,observations=768,predictions_per_model=3904,total_predictions=7808,
        signal='QPSK sps8 beta.35 span12; random phase; center1024 from4096 samples; unit RMS',
        seed='clean203009260+i; channel203109260+i*100+snr_index; noise shared across SIR',
        snr=[-10,0,10,20],sir=[-10,0,10],tone_hz=250000,rate=2100000,planes=list(PLANES),
        estimator='oracle exact injected tone vs simplified known-frequency512 guard-sample LS; NOT production estimator',
        scope='Single-class synthetic diagnostic, no selection on clean predictions. Repeated conditions share64 base signals. Not RF or locked-test.',
        grouping='paired known-component raw SINR; not source SNR or measured RF estimate',
        rule_threshold=s.THRESHOLD,seconds_per_model=900,gpu_bytes=4*1024**3,no_rf=True,no_training=True))
    checks=[physical.digital('QPSK',203009260+i,8)[0] for i in range(64)]
    ev.require(sum(r['errors'] for r in checks)==0 and max(r['evm'] for r in checks)<.03,'physical gate')
    ev.atomic(root/'physical.json',checks)
    arrays,records=data();ev.atomic(root/'rows.json',records)
    ev.atomic(root/'inputs.json',{k:dict(shape=list(x.shape),sha256=hashlib.sha256(x.tobytes()).hexdigest()) for k,x in arrays.items()})


def infer(root,name):
    dest=root/name;dest.mkdir(exist_ok=False)
    plan=json.loads((root/'plan.json').read_text())
    for rec in plan['identities']:ev.identity(rec['path'],rec['sha256'])
    arrays,records=data();inputs=json.loads((root/'inputs.json').read_text())
    ev.require(records==json.loads((root/'rows.json').read_text()),'rows')
    for k,x in arrays.items():ev.require(hashlib.sha256(x.tobytes()).hexdigest()==inputs[k]['sha256'],'shared inputs')
    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('900s')));signal.alarm(900)
    if name=='cnn2':
        torch=ev.setup(dest);model=ev.load_model(plan['cnn2'],torch)
    else:
        cache=dest/'cache';cache.mkdir()
        for key in ('TMPDIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR','XDG_CACHE_HOME'):
            p=cache/key;p.mkdir();os.environ[key]=str(p)
        src=s.MODEL/'source_03fa833';sys.path.insert(0,str(src))
        for key in ('models','utils','datasets'):
            ev.require(key not in sys.modules,'namespace');m=types.ModuleType(key);m.__path__=[str(src/key)];sys.modules[key]=m
        import torch
        torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(0)
        torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
        from models.d10 import AMCMambaD10
        cfg=json.loads((s.MODEL/'config.json').read_text());model=AMCMambaD10(num_classes=24,**{k:cfg['resolved_config']['model'][k] for k in ev.FIELDS})
        ck=torch.load(s.MODEL/'best.pt',map_location='cpu',weights_only=True)
        ev.require(ck['selected_model_variant']=='amc_mamba_d10','variant');model.load_state_dict(ck['model_state'],strict=True)
        ev.require(sum(p.numel() for p in model.parameters())==126958 and model.encoder.backend==cfg['model_backend'],'D10 identity');model=model.eval().cuda()
    logits={};checks={}
    for key in PLANES:
        x=arrays[key];probe=np.linspace(0,len(x)-1,12,dtype=int)
        batch=ev.predict(model,x[probe],torch,'fp32');single=np.concatenate([ev.predict(model,x[i:i+1],torch,'fp32') for i in probe])
        ev.require(np.allclose(batch,single,atol=2e-4,rtol=2e-4) and np.array_equal(batch.argmax(1),single.argmax(1)),'numerical gate')
        logits[key]=np.concatenate([ev.predict(model,x[i:i+128],torch,'fp32') for i in range(0,len(x),128)])
        ev.require(np.allclose(logits[key][probe],single,atol=2e-4,rtol=2e-4) and np.array_equal(logits[key][probe].argmax(1),single.argmax(1)),'actual batch')
        checks[key]=dict(rows=len(probe),max_abs=float(abs(batch-single).max()))
        ev.require(not (root/'STOP').exists(),'STOP');print(name,key,int((logits[key].argmax(1)==4).sum()),flush=True)
    np.savez(dest/'predictions.npz',**logits)
    ev.require(torch.cuda.max_memory_allocated()<4*1024**3,'GPU bound')
    ev.atomic(dest/'numerical.json',dict(strict_load=True,backend=model.encoder.backend,checks=checks,gpu_bytes=torch.cuda.max_memory_allocated()))
    for rec in plan['identities']:ev.unchanged(rec)
    signal.alarm(0)


def report(root):
    rows=json.loads((root/'rows.json').read_text());sinr=np.array([r['raw_sinr'] for r in rows])
    results={}
    masks={'overall':np.ones(len(rows),bool),'raw_sinr_below0':sinr<0}
    for lo,hi in ((-30,-10),(-10,-5),(-5,0),(0,5),(5,10),(10,30)):masks[f'raw_sinr[{lo},{hi})']=(sinr>=lo)&(sinr<hi)
    for name in ('d10','cnn2'):
        f=np.load(root/name/'predictions.npz',allow_pickle=False);good={k:f[k].argmax(1)==4 for k in s.PLANES}
        groups={}
        for label,mask in masks.items():
            groups[label]=dict(rows=int(mask.sum()),correct={k:int(v[mask].sum()) for k,v in good.items()},
                corrected={k:int((~good['raw'][mask]&v[mask]).sum()) for k,v in good.items()},
                regressed={k:int((good['raw'][mask]&~v[mask]).sum()) for k,v in good.items()})
        results[name]=dict(clean_correct=int((f['clean'].argmax(1)==4).sum()),clean_rows=64,groups=groups,
            regressions_despite_lower_error={k:int(sum(good['raw'][i] and not good[k][i] and r['error_power'][k]<r['error_power']['raw'] for i,r in enumerate(rows))) for k in s.PLANES})
    ev.atomic(root/'results.json',results);print(json.dumps(results,indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('command',choices=['prepare','d10','cnn2','report']);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    if a.command=='prepare':prepare(a.out)
    elif a.command=='report':report(a.out)
    else:infer(a.out,a.command)
