#!/usr/bin/env python3
"""Fixed-grid synthetic clean-input audit; no RF, training or parameter selection."""
import argparse, json, os, signal, sys, time, types, hashlib, shutil
from pathlib import Path
import numpy as np
import rml2018a_d10_synthetic as s

ev=s.ev
PARENT=Path('/var/tmp/sdrharness-dev/rml2018a-d10-synthetic-20260926')


def generate(label,seed,sps,zero_phase):
    if label.startswith('AM'):
        rng=np.random.RandomState(seed);rng.normal(size=4096);phase=2*np.pi*rng.rand()
        x=s.generate(label,seed)
        return x*np.exp(-1j*phase) if zero_phase else x
    rng=np.random.RandomState(seed)
    # Keep previous512-symbol realization exactly at sps8. Slower sampling
    # requires more symbols to retain a central crop free of filter transients.
    n=max(512,4096//sps)
    if label=='BPSK':symbols=2*rng.randint(2,size=n)-1
    elif label=='QPSK':symbols=np.exp(1j*(np.pi/4+np.pi/2*rng.randint(4,size=n)))
    else:symbols=(2*rng.randint(4,size=n)-3)+1j*(2*rng.randint(4,size=n)-3)
    impulse=np.zeros(n*sps,complex);impulse[::sps]=symbols
    z=np.convolve(impulse,s.rrc(sps=sps),mode='same')
    start=(len(z)-1024)//2
    phase=2*np.pi*rng.rand()
    return s.unit(z[start:start+1024]*np.exp(1j*(0 if zero_phase else phase)))


def main(out):
    ev.require(out.resolve()==out and out.parent==Path('/var/tmp/sdrharness-dev'),'canonical output')
    out.mkdir(exist_ok=False);cache=out/'cache';cache.mkdir()
    for k in ('TMPDIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR','XDG_CACHE_HOME'):
        p=cache/k;p.mkdir();os.environ[k]=str(p)
    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('900s deadline')));signal.alarm(900)
    parent=json.loads((PARENT/'plan.json').read_text())
    for r in parent['identities']:ev.identity(r['path'],r['sha256'])
    src=s.MODEL/'source_03fa833'
    audit=json.loads((ev.REPO/'docs/evidence/RML2018A_D10_SYNTHETIC_2026-09-26.json').read_text())
    for r in audit['files']:ev.identity(r['path'],r['sha256'])
    ev.require(shutil.disk_usage(out).free>1024**3,'disk')
    plan=dict(schema='synthetic-clean-parameter-audit-v1',parent=ev.identity(PARENT/'predictions.npz'),
        software=[ev.identity(__file__),ev.identity(s.__file__)],model=parent['identities'],
        grid=dict(digital_sps=[2,4,8,16],phase=['random','zero'],per_class=64),
        fixed='RRC beta.35 span12; unit RMS; no noise/tone; AM message unchanged; seeds same as parent',
        limits='Different sps windows span different symbols; sensitivity comparison, not waveform-identical intervention. Full grid reported, no best-setting selection.',
        predictions=1792,seconds=900,gpu_bytes=4*1024**3,no_rf=True,no_training=True)
    ev.atomic(out/'plan.json',plan)
    waves=[];records=[]
    for label,cls in s.LABELS.items():
        for sps in ([2,4,8,16] if not label.startswith('AM') else [8]):
            for zero in (False,True):
                for rep in range(64):
                    seed=202609260+cls*1000+rep
                    wave=generate(label,seed,sps,zero)
                    if sps==8 and not zero:np.testing.assert_array_equal(wave,s.generate(label,seed))
                    waves.append(wave);records.append(dict(label=label,truth=cls,sps=sps,phase='zero' if zero else 'random',rep=rep,seed=seed))
    x=s.tensor(np.asarray(waves));ev.require(len(x)==1792,'budget')
    ev.atomic(out/'inputs.json',dict(rows=records,sha256=hashlib.sha256(x.tobytes()).hexdigest()))
    sys.path.insert(0,str(src))
    for name in ('models','utils','datasets'):
        ev.require(name not in sys.modules,'namespace collision');m=types.ModuleType(name);m.__path__=[str(src/name)];sys.modules[name]=m
    import torch
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    from models.d10 import AMCMambaD10
    cfg=json.loads((s.MODEL/'config.json').read_text())
    model=AMCMambaD10(num_classes=24,**{k:cfg['resolved_config']['model'][k] for k in ev.FIELDS})
    ck=torch.load(s.MODEL/'best.pt',map_location='cpu',weights_only=True)
    ev.require(ck['selected_model_variant']=='amc_mamba_d10','variant');model.load_state_dict(ck['model_state'],strict=True)
    ev.require(sum(p.numel() for p in model.parameters())==126958 and model.encoder.backend==cfg['model_backend'],'identity')
    model=model.eval().cuda();probe=np.arange(0,len(x),64)
    batch=ev.predict(model,x[probe],torch,'fp32');single=np.concatenate([ev.predict(model,x[i:i+1],torch,'fp32') for i in probe])
    ev.require(np.allclose(batch,single,atol=2e-4,rtol=2e-4) and np.array_equal(batch.argmax(1),single.argmax(1)),'numerical')
    outputs=[]
    for a in range(0,len(x),128):
        ev.require(not (out/'STOP').exists(),'STOP');outputs.append(ev.predict(model,x[a:a+128],torch,'fp32'))
    logits=np.concatenate(outputs)
    ev.require(np.allclose(logits[probe],single,atol=2e-4,rtol=2e-4) and np.array_equal(logits[probe].argmax(1),single.argmax(1)),'actual batch gate')
    base=np.array([i for i,r in enumerate(records) if r['sps']==8 and r['phase']=='random'])
    old=np.load(PARENT/'predictions.npz',allow_pickle=False)['clean_logits']
    ev.require(np.allclose(logits[base],old,atol=2e-4,rtol=2e-4) and np.array_equal(logits[base].argmax(1),old.argmax(1)),'old baseline')
    np.savez(out/'predictions.npz',logits=logits,truth=np.array([r['truth'] for r in records]))
    results=[]
    for a in range(0,len(x),64):
        r=records[a];pred=logits[a:a+64].argmax(1)
        results.append(dict(label=r['label'],sps=r['sps'],phase=r['phase'],correct=int((pred==r['truth']).sum()),rows=64,counts=np.bincount(pred,minlength=24).tolist()))
    ev.require(torch.cuda.max_memory_allocated()<4*1024**3,'GPU budget')
    ev.atomic(out/'results.json',dict(groups=results,strict_load=True,backend=model.encoder.backend,numerical_probe_rows=len(probe),numerical_max_abs=float(abs(batch-single).max()),parent_max_abs=float(abs(logits[base]-old).max()),parent_top1_equal=True,gpu_bytes=torch.cuda.max_memory_allocated()))
    signal.alarm(0)
    for r in results:print(r['label'],r['sps'],r['phase'],r['correct'],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);main(p.parse_args().out)
