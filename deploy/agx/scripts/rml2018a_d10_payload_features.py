#!/usr/bin/env python3
"""Fixed D10 diagnostic members: payload features, no inference or RF."""
import csv
import json
import signal
import time
import resource
import shutil
from pathlib import Path
import numpy as np
import h5py
import rml2018a_model_collection_eval as ev
from rml2018a_low_snr_association import stratified_comparison

ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-d10-payload-20260922-a2')
D10=Path('/var/tmp/sdrharness-dev/rml2018a-d10-replay-20260922')
BASE=Path('/var/tmp/sdrharness-dev/rml2018a-offline-baseline-20260916')
FS=2100000
F=np.fft.fftshift(np.fft.fftfreq(4096,1/FS))
LO=(F>=240000)&(F<=260000)
CENTER=abs(F)<=10000
TAIL=(abs(F)>=400000)&(abs(F)<=700000)
W=np.hanning(1024)
METRICS=['envelope_error_delta','spectrum_distance_delta','outside_lo_distance_delta','coherence_delta','center_physical_relative_change','removed_lo_fraction','rms_gain','residual_tail_fraction_delta']


def spectrum(x):
    p=abs(np.fft.fftshift(np.fft.fft(x*W,4096)))**2
    return p/p.sum()


def envcv(x):
    a=abs(x);return float(a.std()/a.mean())


def coherence(a,b):
    return float(abs(np.vdot(a,b))**2/(np.vdot(a,a).real*np.vdot(b,b).real))


def features(s,r,g,rr,gr):
    # Undo the distinct window RMS to compare actual subtraction in common ADC units.
    r=r*rr;g=g*gr;d=r-g
    ps,pr,pg,pd=map(spectrum,(s,r,g,d))
    cs,cr,cg=map(envcv,(s,r,g))
    def tv(a,b):return float(abs(a-b).sum()/2)
    def rest(p):return p[~LO]/p[~LO].sum()
    sr=np.vdot(s,r)/np.vdot(s,s);sg=np.vdot(s,g)/np.vdot(s,s)
    er=r-sr*s;eg=g-sg*s
    # Source includes synthetic noise: these are source-fit residuals, not pure noise.
    tailr=spectrum(er)[TAIL].sum();tailg=spectrum(eg)[TAIL].sum()
    crp=abs(np.fft.fftshift(np.fft.fft(r*W,4096)))**2
    cgp=abs(np.fft.fftshift(np.fft.fft(g*W,4096)))**2
    return dict(source_env_cv=cs,raw_env_cv=cr,guard_env_cv=cg,
        envelope_error_delta=abs(cg-cs)-abs(cr-cs),
        raw_spectrum_distance=tv(pr,ps),guard_spectrum_distance=tv(pg,ps),
        spectrum_distance_delta=tv(pg,ps)-tv(pr,ps),
        outside_lo_distance_delta=tv(rest(pg),rest(ps))-tv(rest(pr),rest(ps)),
        raw_coherence=coherence(s,r),guard_coherence=coherence(s,g),coherence_delta=coherence(s,g)-coherence(s,r),
        source_center_fraction=float(ps[CENTER].sum()),raw_center_fraction=float(pr[CENTER].sum()),guard_center_fraction=float(pg[CENTER].sum()),
        center_physical_relative_change=float(cgp[CENTER].sum()/crp[CENTER].sum()-1),
        removed_lo_fraction=float(pd[LO].sum()),removed_center_fraction=float(pd[CENTER].sum()),
        raw_lo_fraction=float(pr[LO].sum()),guard_lo_fraction=float(pg[LO].sum()),
        rms_gain=float(rr/gr),residual_tail_fraction_delta=float(tailg-tailr))


def main():
    ROOT.mkdir(exist_ok=False)
    start=time.monotonic();signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('600s')));signal.alarm(600)
    audit=json.loads(Path('docs/evidence/RML2018A_D10_REPLAY_2026-09-22.json').read_text())
    for rec in audit['files']:ev.identity(rec['path'],rec['sha256'])
    parent_seal=json.loads((BASE/'retention.json').read_text())
    for name in ('baseline-rows.json','input-identities.json'):
        rec=next(r for r in parent_seal['files'] if Path(r['path']).name==name);ev.identity(rec['path'],rec['sha256'])
    plan=dict(schema='d10-payload-features-v1',parents=[ev.identity(D10/'predictions.npz'),ev.identity(D10/'inputs.json'),ev.identity(BASE/'baseline-rows.json')],script=ev.identity(__file__),
        rows=2496,primary_source_snr=[-10,0],primary_rows=576,metrics=METRICS,
        estimator='Hann1024 FFT4096 fs2100000; center +/-10kHz; LO240..260kHz; tail |f|400..700kHz; no mean removal',
        interpretation='PSD total variation and envelope CV distance to same noisy source; scalar source-fit residual is not pure noise; ADC scaling uses archived pre-RMS; descriptive not causal',
        comparison='four correctness states; regression vs retained-correct within class/Z, equal cell weight; no threshold search',
        budget=dict(seconds=600,host_bytes=1024**3,output_bytes=32*1024**2,free_bytes=shutil.disk_usage(ROOT).free),new_inference=False,rf=False)
    ev.atomic(ROOT/'plan.json',plan)
    with np.load(D10/'predictions.npz') as f:p={k:f[k] for k in f.files}
    ids=p['source_row'];y=p['truth'];z=p['source_snr_db'];old=sorted(json.loads((BASE/'baseline-rows.json').read_text()),key=lambda r:r['index'])
    ev.require([r['index'] for r in old]==list(range(2496)) and np.array_equal(ids,[r['source_row'] for r in old]),'lineage ids')
    inputs=json.loads((D10/'inputs.json').read_text());data={}
    for plane in ('source','raw','guard'):
        rec=inputs[plane]['parent_identity'];ev.unchanged(rec)
        with h5py.File(rec['path'],'r') as f:
            if plane=='source':x=f['X'][ids].transpose(0,2,1)
            else:
                allids=f['source_row'][:];order=np.argsort(allids);rows=order[np.searchsorted(allids[order],ids)]
                ev.require(np.array_equal(allids[rows],ids),'row mapping')
                ix=np.argsort(rows);x=f['iq'][rows[ix]][np.argsort(ix)]
        x=np.ascontiguousarray(x,dtype=np.float32)
        import hashlib
        ev.require(hashlib.sha256(x.tobytes()).hexdigest()==inputs[plane]['selected_iq_sha256'],'D10 input bytes')
        data[plane]=x[:,0].astype(float)+1j*x[:,1].astype(float);ev.unchanged(rec)
    rows=[]
    for i in range(len(ids)):
        rc=p['raw_logits'][i].argmax()==y[i];gc=p['guard_logits'][i].argmax()==y[i]
        state='retained_correct' if rc and gc else 'regressed' if rc else 'corrected' if gc else 'both_wrong'
        line=old[i]; rr=line['planes']['raw']['received_rms'];gr=line['planes']['guard']['received_rms']
        row=dict(source_row=int(ids[i]),validation_rank=int(p['validation_rank'][i]),truth=int(y[i]),source_snr_db=int(z[i]),state=state,
            raw_prediction=int(p['raw_logits'][i].argmax()),guard_prediction=int(p['guard_logits'][i].argmax()),source_prediction=int(p['source_logits'][i].argmax()),
            raw_path=line['raw_path'],frame=line['frame'],window_in_frame=line['window_in_frame'],
            **features(data['source'][i],data['raw'][i],data['guard'][i],rr,gr))
        rows.append(row)
    with (ROOT/'rows.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    low=[r for r in rows if -10<=r['source_snr_db']<=0];ev.require(len(low)==576,'primary members')
    def stats(rs):
        return dict(n=len(rs),medians={k:float(np.median([r[k] for r in rs])) for k in METRICS},
            closer_spectrum=sum(r['spectrum_distance_delta']<0 for r in rs),closer_envelope=sum(r['envelope_error_delta']<0 for r in rs),higher_coherence=sum(r['coherence_delta']>0 for r in rs),
            center_change_abs_max=max(abs(r['center_physical_relative_change']) for r in rs),removed_lo_min=min(r['removed_lo_fraction'] for r in rs))
    result=dict(primary=stats(low),states={s:stats([r for r in low if r['state']==s]) for s in sorted(set(r['state'] for r in low))},
        matched=[stratified_comparison(low,k) for k in METRICS],
        classes={str(c):stats([r for r in low if r['truth']==c]) for c in range(24)},
        seconds=time.monotonic()-start,rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    ev.require(result['rss_bytes']<=1024**3,'RSS budget')
    ev.atomic(ROOT/'results.json',result);print(json.dumps(result['states'],indent=2))
    signal.alarm(0)

if __name__=='__main__':main()
