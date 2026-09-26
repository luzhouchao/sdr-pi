#!/usr/bin/env python3
"""New-seed paired rolloff/timing factorial; synthetic diagnostics only."""
import argparse,hashlib,json,os,signal,sys,types,shutil
from pathlib import Path
import numpy as np
import rml2018a_d10_synthetic as s

ev=s.ev
VARIANTS=('fixed','rolloff','timing','both')


def pulse(sps,beta,fraction):
    t=(np.arange(-6*sps,6*sps+1,dtype=float)-fraction)/sps
    den=1-(4*beta*t)**2
    h=np.empty_like(t);special=np.abs(den)<1e-10
    h[~special]=((1-beta)*np.sinc((1-beta)*t[~special])+4*beta/np.pi*np.cos(np.pi*(1+beta)*t[~special]))/den[~special]
    h[special]=beta/np.sqrt(2)*((1+2/np.pi)*np.sin(np.pi/(4*beta))+(1-2/np.pi)*np.cos(np.pi/(4*beta)))
    return h/np.linalg.norm(h)


def realization(label,rep,sps,variant):
    cls=s.LABELS[label];seed=202709260+cls*10000+sps*100+rep
    rng=np.random.RandomState(seed);n=max(512,4096//sps)
    if label=='BPSK':const=np.array([-1,1]);symbols=const[rng.randint(2,size=n)]
    elif label=='QPSK':const=np.exp(1j*(np.pi/4+np.pi/2*np.arange(4)));symbols=const[rng.randint(4,size=n)]
    else:
        const=np.array([a+1j*b for a in (-3,-1,1,3) for b in (-3,-1,1,3)])
        symbols=(2*rng.randint(4,size=n)-3)+1j*(2*rng.randint(4,size=n)-3)
    # Identical nuisance draws across classes at each (sps,rep), independent of symbols.
    nuisance=np.random.RandomState(202809260+sps*100+rep)
    beta=float(nuisance.uniform(.1,.4));tau=float(nuisance.uniform(0,16));phase=float(nuisance.uniform(0,2*np.pi))
    if variant not in ('rolloff','both'):beta=.35
    if variant not in ('timing','both'):tau=0.
    h=pulse(sps,beta,tau%1);impulse=np.zeros(n*sps,complex);impulse[::sps]=symbols
    full=np.convolve(impulse,h,mode='same');start=(len(full)-1024)//2+int(tau)
    crop=full[start:start+1024];rms=np.sqrt(s.power(crop));x=crop/rms*np.exp(1j*phase)
    # Known phase/gain and matched fractional pulse; no inference-based alignment.
    rx=np.convolve(x*np.exp(-1j*phase)*rms,h[::-1],mode='same')
    centers=np.arange(n)*sps-start;mask=(centers>=len(h)//2)&(centers<1024-len(h)//2)
    got=rx[centers[mask]];want=symbols[mask]
    decisions=const[abs(got[:,None]-const[None,:]).argmin(1)]
    info=dict(label=label,truth=cls,rep=rep,sps=sps,variant=variant,seed=seed,beta=beta,tau=tau,phase=phase,
              symbols=len(want),errors=int((abs(decisions-want)>1e-10).sum()),evm=float(np.sqrt(s.power(got-want)/s.power(want))))
    return x,info


def inputs():
    waves=[];records=[]
    for label in ('BPSK','QPSK','16QAM'):
        for sps in (2,4,8,16):
            for variant in VARIANTS:
                for rep in range(64):
                    x,r=realization(label,rep,sps,variant);waves.append(x);records.append(r)
    for label in ('AM-DSB-WC','AM-DSB-SC'):
        for rep in range(64):
            seed=202709260+s.LABELS[label]*10000+rep
            waves.append(s.generate(label,seed));records.append(dict(label=label,truth=s.LABELS[label],rep=rep,sps=None,variant='unchanged_AM',seed=seed))
    return s.tensor(np.asarray(waves)),records


def run(out):
    ev.require(out.resolve()==out and out.parent==Path('/var/tmp/sdrharness-dev'),'canonical root');out.mkdir(exist_ok=False)
    cache=out/'cache';cache.mkdir()
    for key in ('TMPDIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR','XDG_CACHE_HOME'):
        q=cache/key;q.mkdir();os.environ[key]=str(q)
    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('900s deadline')));signal.alarm(900)
    parent=Path('/var/tmp/sdrharness-dev/rml2018a-d10-synthetic-20260926')
    identities=json.loads((parent/'plan.json').read_text())['identities']+[ev.identity(__file__)]
    for r in identities:ev.identity(r['path'],r['sha256'])
    ev.require(shutil.disk_usage(out).free>1024**3,'space')
    ev.atomic(out/'plan.json',dict(schema='synthetic-randomized-factorial-v1',identities=identities,
        variants=list(VARIANTS),sps=[2,4,8,16],per_cell=64,rows=3200,
        seeds='symbols202709260+class*10000+sps*100+rep; nuisance202809260+sps*100+rep; AM202709260+class*10000+rep',
        distributions='beta uniform[.1,.4); tau uniform[0,16) sample units, integer crop shift plus fractional pulse shift; phase uniform[0,2pi)',
        paired='same symbols/phase across four variants; same nuisance draws across digital classes; AM new-seed unchanged control only',
        physics_gate=dict(symbol_errors=0,max_evm=.12),
        scope='Engineering convention for timing units; not claimed exact RadioML reconstruction. No noise/CFO/multipath. Full factorial reported, no best-sps selection.',
        seconds=900,gpu_bytes=4*1024**3,no_training=True,no_rf=True))
    x,records=inputs();digital=[r for r in records if 'errors' in r]
    physical=dict(windows=len(digital),symbols=sum(r['symbols'] for r in digital),errors=sum(r['errors'] for r in digital),max_evm=max(r['evm'] for r in digital))
    ev.atomic(out/'physical.json',physical);ev.atomic(out/'inputs.json',dict(rows=records,sha256=hashlib.sha256(x.tobytes()).hexdigest()))
    ev.require(physical['errors']==0 and physical['max_evm']<.12,'physical gate before model')
    src=s.MODEL/'source_03fa833';sys.path.insert(0,str(src))
    for name in ('models','utils','datasets'):
        ev.require(name not in sys.modules,'namespace');m=types.ModuleType(name);m.__path__=[str(src/name)];sys.modules[name]=m
    import torch
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    from models.d10 import AMCMambaD10
    cfg=json.loads((s.MODEL/'config.json').read_text());model=AMCMambaD10(num_classes=24,**{k:cfg['resolved_config']['model'][k] for k in ev.FIELDS})
    ck=torch.load(s.MODEL/'best.pt',map_location='cpu',weights_only=True)
    ev.require(ck['selected_model_variant']=='amc_mamba_d10','variant');model.load_state_dict(ck['model_state'],strict=True)
    ev.require(sum(p.numel() for p in model.parameters())==126958 and model.encoder.backend==cfg['model_backend'],'model identity');model=model.eval().cuda()
    probe=np.arange(0,len(x),64);bat=ev.predict(model,x[probe],torch,'fp32');single=np.concatenate([ev.predict(model,x[i:i+1],torch,'fp32') for i in probe])
    ev.require(np.allclose(bat,single,atol=2e-4,rtol=2e-4) and np.array_equal(bat.argmax(1),single.argmax(1)),'probe numerical')
    outputs=[]
    for a in range(0,len(x),128):
        ev.require(not (out/'STOP').exists(),'STOP');outputs.append(ev.predict(model,x[a:a+128],torch,'fp32'))
    logits=np.concatenate(outputs)
    ev.require(np.allclose(logits[probe],single,atol=2e-4,rtol=2e-4) and np.array_equal(logits[probe].argmax(1),single.argmax(1)),'batch numerical')
    truth=np.array([r['truth'] for r in records]);np.savez(out/'predictions.npz',logits=logits,truth=truth)
    groups=[]
    for a in range(0,len(x),64):
        r=records[a];pred=logits[a:a+64].argmax(1)
        groups.append(dict(label=r['label'],sps=r['sps'],variant=r['variant'],correct=int((pred==r['truth']).sum()),rows=64,counts=np.bincount(pred,minlength=24).tolist()))
    for r in identities:ev.unchanged(r)
    ev.require(torch.cuda.max_memory_allocated()<4*1024**3,'GPU memory')
    ev.atomic(out/'results.json',dict(groups=groups,numerical_rows=len(probe),max_abs=float(abs(bat-single).max()),strict_load=True,backend=model.encoder.backend,gpu_bytes=torch.cuda.max_memory_allocated()))
    signal.alarm(0)
    print(json.dumps(physical),flush=True)
    for r in groups:print(r['label'],r['sps'],r['variant'],r['correct'],flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);run(ap.parse_args().out)
