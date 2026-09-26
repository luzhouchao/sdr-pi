#!/usr/bin/env python3
"""Bounded synthetic causal diagnostic; no RF, training or RadioML IQ access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time
import types
import numpy as np
import rml2018a_model_collection_eval as ev

LABELS = {'BPSK':3, 'QPSK':4, '16QAM':12, 'AM-DSB-WC':19, 'AM-DSB-SC':20}
RATE = 2100000
THRESHOLD = .9227873698928544
MODEL = Path('/home/jetson/models/d10/rml2018a/d10_2018a_seed42_nw8')
PLANES = ('raw','oracle_full','guard_full','guard25','rule')


def power(x):
    return np.mean(np.abs(x)**2, axis=-1)


def unit(x):
    p = power(x)
    ev.require(np.isfinite(x).all() and np.all(p > 0), 'finite nonzero waveform')
    return x/np.sqrt(p)[..., None]


def rrc(sps=8, beta=.35, span=12):
    t = np.arange(-span*sps//2, span*sps//2+1)/sps
    h = np.empty_like(t)
    for i, v in enumerate(t):
        if abs(v) < 1e-12:
            h[i] = 1+beta*(4/np.pi-1)
        elif abs(abs(v)-1/(4*beta)) < 1e-12:
            h[i] = beta/np.sqrt(2)*((1+2/np.pi)*np.sin(np.pi/(4*beta))+(1-2/np.pi)*np.cos(np.pi/(4*beta)))
        else:
            h[i] = (np.sin(np.pi*v*(1-beta))+4*beta*v*np.cos(np.pi*v*(1+beta)))/(np.pi*v*(1-(4*beta*v)**2))
    return h/np.linalg.norm(h)


def generate(label, seed):
    rng = np.random.RandomState(seed)
    if label in ('BPSK','QPSK','16QAM'):
        if label == 'BPSK': symbols = 2*rng.randint(2, size=512)-1
        elif label == 'QPSK': symbols = np.exp(1j*(np.pi/4+np.pi/2*rng.randint(4, size=512)))
        else: symbols = (2*rng.randint(4,size=512)-3)+1j*(2*rng.randint(4,size=512)-3)
        impulse = np.zeros(4096, complex); impulse[::8] = symbols
        z = np.convolve(impulse, rrc(), mode='same')
    else:
        ev.require(label in LABELS, 'known synthetic modulation')
        t = np.arange(-128,129)
        h = 2*50000/RATE*np.sinc(2*50000/RATE*t)*np.hamming(len(t)); h /= h.sum()
        message = np.convolve(rng.normal(size=4096), h, mode='same')
        message -= message[512:-512].mean()
        message /= np.max(np.abs(message[512:-512]))
        z = 1+.8*message if label == 'AM-DSB-WC' else message
    # Continuous long realization, central crop, random carrier phase, no wrap.
    return unit(z[1536:2560]*np.exp(2j*np.pi*rng.rand()))


def channel(clean, seed, snr, sir):
    rng = np.random.RandomState(seed)
    noise = unit(rng.normal(size=1024)+1j*rng.normal(size=1024))*10**(-snr/20)
    phase = rng.uniform(-np.pi,np.pi)
    coefficient = 10**(-sir/20)*np.exp(1j*phase)
    t = np.arange(1024)
    basis = np.exp(2j*np.pi*250000*t/RATE)
    tone = coefficient*basis
    # Independent noise in 256 samples before and after the payload. Frequency
    # is known by construction; this is NOT the production guard estimator.
    gt = np.r_[np.arange(-256,0), np.arange(1024,1280)]
    gb = np.exp(2j*np.pi*250000*gt/RATE)
    gn = (rng.normal(size=512)+1j*rng.normal(size=512))/np.sqrt(2)*10**(-snr/20)
    estimate = np.vdot(gb, coefficient*gb+gn)/512
    raw = clean+noise+tone
    full = raw-estimate*basis
    partial = raw-.25*estimate*basis
    ratio = np.sqrt(power(full)/power(raw))
    oracle = raw-tone
    ev.require(np.max(np.abs(oracle-(clean+noise))) < 1e-12, 'oracle preserves signal and noise')
    variants = dict(raw=raw, oracle_full=oracle, guard_full=full, guard25=partial,
                    rule=partial if ratio < THRESHOLD else full)
    realized = float(10*np.log10(power(clean)/power(noise+tone)))
    return variants, dict(snr=snr,sir=sir,raw_sinr=realized,
        ratio=float(ratio),estimate_error=float(abs(estimate-coefficient)),
        action25=bool(ratio < THRESHOLD),
        error_power={k:float(power(v-clean)) for k,v in variants.items()})


def tensor(z):
    z = unit(z)
    return np.ascontiguousarray(np.stack((z.real,z.imag),axis=1),dtype=np.float32)


def run(out):
    ev.require(out.is_absolute() and out.resolve()==out and out.parent==Path('/var/tmp/sdrharness-dev'), 'canonical experiment root')
    out.mkdir(exist_ok=False)
    cache = out/'cache';cache.mkdir()
    for key in ('TMPDIR','TRITON_CACHE_DIR','CUDA_CACHE_PATH','TORCHINDUCTOR_CACHE_DIR','XDG_CACHE_HOME'):
        p=cache/key;p.mkdir();os.environ[key]=str(p)
    signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('1800s budget')))
    signal.alarm(1800); started=time.monotonic()
    src=MODEL/'source_03fa833';manifest=json.loads((src/'SOURCE_MANIFEST.json').read_text())
    identities=[ev.identity(src/n,h) for n,h in manifest['files'].items()]
    identities += [ev.identity(MODEL/'best.pt','5d217592cabab54be4352d8ebddcc47eb9cf9b7ea81d1010027e8dd213546b81'),ev.identity(MODEL/'config.json'),ev.identity(__file__)]
    mapping=ev.REPO/'jetson-agx/sdrharness/config/amc/rml2018a-labels.server-v1.json'
    names=json.loads(mapping.read_text())['classes']
    ev.require(all(names[v]==k for k,v in LABELS.items()),'label mapping')
    identities.append(ev.identity(mapping))
    plan=dict(schema='d10-synthetic-v1',identities=identities,labels=LABELS,realizations_per_class=64,
        snr_db=[-10,0,10,20],sir_db=[-10,0,10],sample_rate=RATE,window=1024,
        generator='4096 continuous samples; central crop1536:2560; digital RRC sps8 beta.35 span12 symbols; AM Gaussian message FIR257 Hamming cutoff50kHz, modulation index.8; random carrier phase',
        seeds='clean=202609260+class_id*1000+rep; channel=202609261+base_index*100+snr_index (shared across SIR)',
        planes=list(PLANES),guard='simplified known-frequency complex least squares on512 independent noisy guard samples; NOT production estimator',
        rule_threshold=THRESHOLD,normalization='independent per-window RMS after each cancellation; no DC removal',
        group_axis='known-component synthetic raw SINR, NOT conditional RF estimate',
        scope='synthetic diagnostic; not RadioML distribution replication, accuracy benchmark, RF result or admission',
        budget=dict(seconds=1800,gpu_bytes=4*1024**3,minimum_disk_free=1024**3,maximum_predictions=20800),
        no_rf=True,no_training=True,production_changes=False)
    ev.require(shutil.disk_usage(out).free>1024**3,'disk space');ev.atomic(out/'plan.json',plan)
    clean=[];truth=[]
    for label,cls in LABELS.items():
        for rep in range(64):clean.append(generate(label,202609260+cls*1000+rep));truth.append(cls)
    clean=np.asarray(clean);truth=np.asarray(truth)
    data={k:[] for k in PLANES};records=[];ids=[];noisy=[]
    for i,z in enumerate(clean):
        for j,snr in enumerate(plan['snr_db']):
            for sir in plan['sir_db']:
                variants,record=channel(z,202609261+i*100+j,snr,sir)
                for k in PLANES:data[k].append(variants[k])
                records.append(record);ids.append(i)
                if sir == -10:noisy.append(variants['oracle_full'])
    # Only reproducible small metadata/logits retained; no IQ copy required.
    ev.atomic(out/'channel.json',records)
    ids=np.asarray(ids);y=truth[ids]
    data={k:tensor(np.asarray(v)) for k,v in data.items()}
    data.update(clean=tensor(clean),noise_only=tensor(np.asarray(noisy)))
    ev.atomic(out/'inputs.json',{k:dict(shape=list(v.shape),sha256=hashlib.sha256(v.tobytes()).hexdigest()) for k,v in data.items()})
    sys.path.insert(0,str(src))
    for name in ('models','utils','datasets'):
        ev.require(name not in sys.modules,'namespace collision')
        mod=types.ModuleType(name);mod.__path__=[str(src/name)];sys.modules[name]=mod
    import torch
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.manual_seed(0)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    ev.require(torch.cuda.is_available(),'real CUDA backend required')
    from models.d10 import AMCMambaD10
    cfg=json.loads((MODEL/'config.json').read_text())
    model=AMCMambaD10(num_classes=24,**{k:cfg['resolved_config']['model'][k] for k in ev.FIELDS})
    ck=torch.load(MODEL/'best.pt',map_location='cpu',weights_only=True)
    ev.require(ck['selected_model_variant']=='amc_mamba_d10','D10 variant')
    model.load_state_dict(ck['model_state'],strict=True)
    ev.require(sum(p.numel() for p in model.parameters())==cfg['model_parameters'] and model.encoder.backend==cfg['model_backend'],'model identity')
    model=model.eval().cuda()
    ev.atomic(out/'load.json',dict(strict=True,parameters=cfg['model_parameters'],backend=model.encoder.backend,torch=torch.__version__))
    logits={};checks={}
    for k,x in data.items():
        probe=np.linspace(0,len(x)-1,10,dtype=int)
        batch=ev.predict(model,x[probe],torch,'fp32')
        single=np.concatenate([ev.predict(model,x[a:a+1],torch,'fp32') for a in probe])
        checks[k]=dict(max_abs=float(abs(batch-single).max()),top1_equal=bool(np.array_equal(batch.argmax(1),single.argmax(1))))
        ev.require(np.allclose(batch,single,atol=2e-4,rtol=2e-4) and checks[k]['top1_equal'],'numerical gate')
        logits[k]=np.concatenate([ev.predict(model,x[a:a+128],torch,'fp32') for a in range(0,len(x),128)])
        ev.require(np.allclose(logits[k][probe],single,atol=2e-4,rtol=2e-4) and np.array_equal(logits[k][probe].argmax(1),single.argmax(1)),'full batch numerical gate')
        ev.require(not (out/'STOP').exists(),'STOP')
        print(k,len(x),flush=True)
    ev.atomic(out/'numerical.json',checks)
    np.savez(out/'predictions.npz',truth=y,base_id=ids,clean_truth=truth,**{k+'_logits':v for k,v in logits.items()})
    rawsinr=np.array([r['raw_sinr'] for r in records])
    def summary(mask):
        good={k:logits[k].argmax(1)==y for k in PLANES}
        return dict(rows=int(mask.sum()),correct={k:int((v&mask).sum()) for k,v in good.items()},
            corrected={k:int((~good['raw']&v&mask).sum()) for k,v in good.items()},
            regressed={k:int((good['raw']&~v&mask).sum()) for k,v in good.items()})
    groups={'overall':summary(np.ones(len(y),bool)),'sinr_below0':summary(rawsinr<0)}
    for label,cls in LABELS.items():groups[label]=summary(y==cls)
    for lo,hi in ((-30,-10),(-10,-5),(-5,0),(0,5),(5,10),(10,30)):
        groups[f'sinr[{lo},{hi})']=summary((rawsinr>=lo)&(rawsinr<hi))
    baseline={label:dict(clean_correct=int(((logits['clean'].argmax(1)==truth)&(truth==cls)).sum()),rows=64,
        predicted_counts=np.bincount(logits['clean'][truth==cls].argmax(1),minlength=24).tolist(),
        noise_only_correct={str(snr):int((logits['noise_only'].argmax(1).reshape(320,4)[truth==cls,j]==cls).sum()) for j,snr in enumerate(plan['snr_db'])}) for label,cls in LABELS.items()}
    error={k:np.array([r['error_power'][k] for r in records]) for k in PLANES}
    physical={k:dict(error_decreased=int((v<error['raw']).sum()),regressed_despite_lower_error=int(((v<error['raw'])&(logits['raw'].argmax(1)==y)&(logits[k].argmax(1)!=y)).sum())) for k,v in error.items()}
    for rec in identities:ev.unchanged(rec)
    ev.require(torch.cuda.max_memory_allocated()<4*1024**3,'GPU memory')
    ev.atomic(out/'results.json',dict(groups=groups,baseline=baseline,physical=physical,seconds=time.monotonic()-started,gpu_bytes=torch.cuda.max_memory_allocated()))
    signal.alarm(0);print(json.dumps(groups['overall']),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    run(p.parse_args().out)
