#!/usr/bin/env python3
"""Offline conditional SINR and RF evidence; never changes inference inputs."""
import argparse
import json
from pathlib import Path
import hashlib
import h5py
import numpy as np
import amc_dataset_contract as native
import amc_rrc_transport as r

METHOD='rrc4-native-reference-crossfit-sourceZ-v1'

def quality(x,y,z):
    q=r.c.receive_quality('synchronized',x,y,float(z),window_samples=len(x))
    q.update(rx_sinr_method=METHOD,rx_sinr_reference_plane='matched_decimated_before_rms',
             rx_payload_filter=r.contract(2048)['method'],rx_sample_rate_hz=r.c.RATE/4,
             rx_sinr_measurement_bandwidth_hz=r.c.RATE/4,
             assumptions=['nominal source Z partitions whole transmitted source power',
                          'RRC Nyquist reconstruction approximately preserves source samples',
                          'cross-fitted scalar channel; distortion counted in denominator',
                          'conditional engineering estimate, not independent calibrated truth'])
    return q

def controls():
    rng=np.random.default_rng(9126);results=[]
    def unit(n):
        a=rng.normal(size=n)+1j*rng.normal(size=n)
        return a/np.sqrt(np.mean(abs(a)**2))
    h=r.taps()
    for length in (128,1024):
      for snr in (-10.,0.,18.):
       for noise_power in (.01,.2):
        errors=[];invalid=0
        for row in range(64):
            a=unit(length);b=unit(length)*10**(-snr/20)
            def chain(x):return np.convolve(r.interpolate(x),h)[128:128+4*length:4]
            clean=chain(a);srcnoise=chain(b)
            adc=unit(4*length+128)*np.sqrt(noise_power)
            added=np.convolve(adc,h,mode='valid')[::4]
            n=np.arange(len(adc));tone=.15*np.exp(2j*np.pi*250000*n/r.c.RATE+.1j)
            added+=np.convolve(tone,h,mode='valid')[::4]
            got=quality(a+b,clean+srcnoise+added,snr)
            truth=10*np.log10(np.mean(abs(clean)**2)/np.mean(abs(srcnoise+added)**2))
            if got['rx_sinr_status']=='estimated':errors.append(got['rx_sinr_db']-truth)
            else:invalid+=1
        median=float(np.median(errors)) if errors else None
        results.append(dict(length=length,source_snr_db=snr,adc_noise_power=noise_power,rows=64,valid=len(errors),invalid=invalid,median_bias_db=median,passed=len(errors)>=48 and abs(median)<1.))
    return dict(method=METHOD,seed=9126,results=results,passed=all(v['passed'] for v in results),scope='known synthetic power only; does not verify real dataset Z semantics')

def report(root):
    p=json.loads((root/'plan.json').read_text());e=p['source'];co=e['contract']
    x,_=native.read_selected(e['source_path'],p['dataset'],np.array(co['source_rows']),co['class_names'],co['source_sha256'])
    out=dict(dataset=p['dataset'],method=METHOD,plan_sha256=r.c.file_hash(root/'plan.json'),processed_sha256=r.c.file_hash(root/'corpus/processed.h5'),script_sha256=r.c.file_hash(__file__),planes={})
    records={}
    with h5py.File(root/'corpus/processed.h5') as f:
        blocks=list(f['blocks'].values());qs=[json.loads(q) for b in blocks for q in b['quality_json'][:]]
        for tag in ('raw','guard'):
            v=np.concatenate([b['inputs'][tag][:] for b in blocks]);valid=np.concatenate([b['valid'][tag][:] for b in blocks]);z=v[:,0]+1j*v[:,1]
            normalized=x/np.sqrt(np.mean(abs(x)**2,axis=1))[:,None]
            error=np.sqrt(np.mean(abs(z-normalized)**2,axis=1));coherence=abs(np.mean(z*normalized.conj(),axis=1))
            values=[]
            for i in range(len(x)):
                values.append(quality(x[i],z[i]*qs[i][tag]['normalization_rms'],co['source_snr_db'][i]) if valid[i] else dict(rx_sinr_db=None,rx_sinr_status='invalid',rx_sinr_reason='unsynchronized'))
            records[tag]=values
            estimates=[q['rx_sinr_db'] for q in values if q['rx_sinr_status']=='estimated']
            out['planes'][tag]=dict(valid_rows=int(valid.sum()),sinr_valid=len(estimates),sinr_invalid=len(x)-len(estimates),sinr_quantiles_db=np.quantile(estimates,[0,.5,.9,1]).tolist() if estimates else None,relative_rms_error_quantiles=np.quantile(error[valid],[0,.5,.9,1]).tolist(),coherence_quantiles=np.quantile(coherence[valid],[0,.5,.9,1]).tolist())
    frames=json.loads((root/'frames.json').read_text());markers=[f['marker_rf_sample'] for f in frames if f['status']=='synchronized'];diff=np.diff(markers)
    out['marker_spacing_samples']={str(int(k)):int(v) for k,v in zip(*np.unique(diff,return_counts=True))}
    out['source_rows']=co['source_rows'];out['quality']=records
    out['models']={}
    bins=[-float('inf'),-10,-5,0,5,10,15,20,float('inf')]
    ref=np.array([q['rx_sinr_db'] if q['rx_sinr_status']=='estimated' else np.nan for q in records['raw']])
    model_results={q.parent.name:q for q in (root/'inference').glob('*/result.json')}
    model_results.update({q.parent.name:q for q in (root/'inference-native').glob('*/result.json')})
    for result in sorted(model_results.values()):
        rr=json.loads(result.read_text());model=rr['variant'];out['models'][model]=dict(overall=rr['planes'],paired_raw_reference_sinr=[])
        with np.load(result.parent/'predictions.npz') as data:
            for j in range(len(bins)-1):
                mask=np.isfinite(ref)&(ref>=bins[j])&(ref<bins[j+1]);n=int(mask.sum())
                out['models'][model]['paired_raw_reference_sinr'].append(dict(bin=str(bins[j])+':'+str(bins[j+1]),rows=n,**{t+'_correct':int(((data[t+'_prediction']==data['class_id'])&mask&data[t+'_valid']).sum()) for t in ('raw','guard')}))
            mask=~np.isfinite(ref);out['models'][model]['sinr_invalid_rows']=int(mask.sum())
    r.c.save(root/'conditional-report.json',out)
    print(json.dumps({k:v for k,v in out.items() if k not in ('quality','source_rows','models')}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path);p.add_argument('--controls',type=Path);a=p.parse_args()
    if a.controls:
        v=controls();r.c.save(a.controls,v);print(json.dumps(v));raise SystemExit(0 if v['passed'] else 1)
    report(a.root)
