#!/usr/bin/env python3
"""Known-symbol receiver audit of existing synthetic inputs; no model/RF."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
import rml2018a_d10_synthetic_parameters as p
s=p.s;ev=p.ev


def receiver_rrc(sps):
    beta=.35;t=np.arange(-6*sps,6*sps+1,dtype=float)/sps
    h=((1-beta)*np.sinc((1-beta)*t)+4*beta/np.pi*np.cos(np.pi*(1+beta)*t))/(1-(4*beta*t)**2)
    # None of the registered integer sps grids hits t=+-1/(4beta).
    ev.require(np.isfinite(h).all(),'receiver pulse singularity')
    return h/np.linalg.norm(h)


def digital(label,seed,sps):
    rng=np.random.RandomState(seed);n=max(512,4096//sps)
    if label=='BPSK':symbols=2*rng.randint(2,size=n)-1;const=np.array([-1,1])
    elif label=='QPSK':
        const=np.exp(1j*(np.pi/4+np.pi/2*np.arange(4)));symbols=const[rng.randint(4,size=n)]
    else:
        symbols=(2*rng.randint(4,size=n)-3)+1j*(2*rng.randint(4,size=n)-3)
        const=np.array([a+1j*b for a in (-3,-1,1,3) for b in (-3,-1,1,3)])
    phase=2*np.pi*rng.rand();impulse=np.zeros(n*sps,complex);impulse[::sps]=symbols
    tx=np.convolve(impulse,s.rrc(sps=sps),mode='same');start=(len(tx)-1024)//2
    crop=tx[start:start+1024];gain=1/np.sqrt(s.power(crop))
    actual=p.generate(label,seed,sps,False)
    np.testing.assert_allclose(actual,crop*gain*np.exp(1j*phase),rtol=1e-13,atol=1e-13)
    h=receiver_rrc(sps);np.testing.assert_allclose(h,s.rrc(sps=sps),rtol=1e-12,atol=1e-12)
    recovered=np.convolve(actual*np.exp(-1j*phase)/gain,h,mode='same')
    centers=np.arange(0,len(tx),sps);local=centers-start
    valid=(local>=len(h)//2)&(local<1024-len(h)//2)
    observed=recovered[local[valid]];expected=symbols[valid]
    decided=const[np.abs(observed[:,None]-const[None,:]).argmin(1)]
    evm=float(np.sqrt(s.power(observed-expected)/s.power(expected)))
    errors=int((abs(decided-expected)>1e-10).sum())
    return dict(label=label,seed=seed,sps=sps,symbols=len(expected),errors=errors,evm=evm),observed,expected


def analog(label,seed):
    rng=np.random.RandomState(seed);t=np.arange(-128,129)
    h=2*50000/s.RATE*np.sinc(2*50000/s.RATE*t)*np.hamming(len(t));h/=h.sum()
    m=np.convolve(rng.normal(size=4096),h,mode='same');m-=m[512:-512].mean();m/=max(abs(m[512:-512]))
    phase=2*np.pi*rng.rand();carrier=1 if label=='AM-DSB-WC' else 0;depth=.8 if carrier else 1
    z=carrier+depth*m;window=z[1536:2560];gain=1/np.sqrt(s.power(window))
    actual=p.generate(label,seed,8,False)
    demod=actual*np.exp(-1j*phase)/gain
    message=(demod-carrier)/depth
    error=float(max(abs(message-m[1536:2560])))
    spectrum=abs(np.fft.fft(demod.real*np.hanning(1024)))**2
    side_error=float(max(abs(spectrum[1:512]-spectrum[:512:-1]))/max(spectrum))
    return dict(label=label,seed=seed,message_error=error,sideband_symmetry_error=side_error,
        imaginary_residual=float(max(abs(demod.imag))),interior_message_mean=float(m[512:-512].mean()),
        carrier_coefficient=carrier,depth=depth,interior_envelope_min=float(min(z[512:-512])) if carrier else None,
        crop_message_mean=float(m[1536:2560].mean()))


def main(root):
    ev.require(root.resolve()==root and root.parent==Path('/var/tmp/sdrharness-dev'),'canonical evidence root')
    root.mkdir(exist_ok=True);ev.require(not (root/'plan.json').exists(),'fresh physical audit')
    identities=[ev.identity(q) for q in (__file__,p.__file__,s.__file__)]
    # Validate against the same frozen inputs; no new predictions or best-grid choice.
    parent=Path('/var/tmp/sdrharness-dev/rml2018a-d10-synthetic-parameters-20260926')
    audit=json.loads((ev.REPO/'docs/evidence/RML2018A_D10_SYNTHETIC_PARAMETERS_2026-09-26.json').read_text())
    for r in audit['files']:ev.identity(r['path'],r['sha256'])
    ev.atomic(root/'plan.json',dict(identities=identities,parent=str(parent),digital_windows=768,analog_windows=128,
        gates=dict(symbol_errors=0,max_evm=.03,am_message_error=1e-12,am_sideband_symmetry=1e-12),
        semantics='Known timing/phase/gain receiver, exclude matched-filter half-length at each crop edge. Not blind synchronization, training-distribution match or RF evidence.',no_model=True,no_rf=True))
    rows=[];points={}
    for label,cls in s.LABELS.items():
        if label.startswith('AM'):continue
        for sps in (2,4,8,16):
            for rep in range(64):
                record,got,want=digital(label,202609260+cls*1000+rep,sps);rows.append(record)
                if rep==0 and sps==8:points[label]=dict(received_real=got.real.tolist(),received_imag=got.imag.tolist(),expected_real=want.real.tolist(),expected_imag=want.imag.tolist())
    analogs=[analog(label,202609260+cls*1000+rep) for label,cls in s.LABELS.items() if label.startswith('AM') for rep in range(64)]
    result=dict(digital_windows=len(rows),symbols=sum(r['symbols'] for r in rows),symbol_errors=sum(r['errors'] for r in rows),max_evm=max(r['evm'] for r in rows),
        analog_windows=len(analogs),max_message_error=max(r['message_error'] for r in analogs),max_sideband_symmetry_error=max(r['sideband_symmetry_error'] for r in analogs),
        minimum_wc_envelope=min(r['interior_envelope_min'] for r in analogs if r['interior_envelope_min'] is not None),
        maximum_sc_crop_message_mean=max(abs(r['crop_message_mean']) for r in analogs if r['label']=='AM-DSB-SC'))
    result['passed']=bool(result['symbol_errors']==0 and result['max_evm']<.03 and result['max_message_error']<1e-12 and result['max_sideband_symmetry_error']<1e-12 and result['minimum_wc_envelope']>=.2-1e-12)
    ev.atomic(root/'rows.json',dict(digital=rows,analog=analogs));ev.atomic(root/'constellations.json',points);ev.atomic(root/'results.json',result)
    ev.require(result['passed'],'physical audit gate failed');print(json.dumps(result))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);main(ap.parse_args().out)
