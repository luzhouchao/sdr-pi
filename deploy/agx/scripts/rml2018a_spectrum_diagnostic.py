#!/usr/bin/env python3
"""Fixed 2496 validation-member spectral geometry; no RF/model or IQ output."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import resource
import signal
import time
import h5py
import numpy as np

PARENT=Path('/var/tmp/sdrharness-dev/rml2018a-offline-baseline-20260916')
ROOT=Path('/var/tmp/sdrharness-dev/rml2018a-spectrum-20260916-a2')
FS=2100000.;N=1024;FFT=4096
F=np.fft.fftshift(np.fft.fftfreq(FFT,1/FS));W=np.hanning(N)
PLAN_METRICS=dict(estimator='1024-point symmetric Hann,4096 FFT, no mean removal',
    occupied_interval='equal-tail 0.5% to99.5%, not shortest interval',
    lo_band_hz=[240000,260000],rf_half_bandwidth_hz=750000,offsets_hz=[250000,750000],
    high_source_snr_db_min=20,mask_meaning='Nominal rectangular geometry only, not measured transfer or loss')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def require(ok,message):
    if not ok:raise ValueError(message)
def array_sha(x):return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def metrics(z):
    z=np.asarray(z,dtype=np.complex128)
    require(z.shape==(N,) and np.isfinite(z).all(),'finite1024 complex samples')
    power=abs(np.fft.fftshift(np.fft.fft(z*W,FFT)))**2
    require(power.sum()>0,'nonzero spectral energy');p=power/power.sum();cdf=np.cumsum(p)
    lo=float(F[min(int(np.searchsorted(cdf,.005)),FFT-1)]);hi=float(F[min(int(np.searchsorted(cdf,.995)),FFT-1)])
    result=dict(f005_hz=lo,f995_hz=hi,obw99_hz=hi-lo,
        lo250_fraction=float(p[(F>=240000)&(F<=260000)].sum()),
        rx_nominal_outside_fraction=float(p[abs(F)>750000].sum()),
        positive_offset_limit_for_99_hz=750000+lo)
    for offset in (250000,750000):
        tx=abs(F-offset)<=750000;rx=abs(F)<=750000
        result[f'tx{offset}_outside_fraction']=float(p[~tx].sum())
        result[f'joint{offset}_outside_fraction']=float(p[~(tx&rx)].sum())
    return result,p


def read_parent():
    retention=json.loads((PARENT/'retention.json').read_text())
    for name in ('plan.json','selection.json','baseline-rows.json','predictions.npz','input-identities.json'):
        entry=next(x for x in retention['files'] if Path(x['path']).name==name)
        require(sha(PARENT/name)==entry['sha256'],'parent seal '+name)
    p=json.loads((PARENT/'plan.json').read_text());records=sorted(json.loads((PARENT/'baseline-rows.json').read_text()),key=lambda r:r['index'])
    require(sha(p['split']['path'])==p['split']['sha256'],'split identity')
    with np.load(p['split']['path']) as f:val=f['val']
    with np.load(PARENT/'predictions.npz') as f:
        keys=['source_row','validation_rank','truth','source_snr_db']+[plane+suffix for plane in ('source','raw','guard') for suffix in ('_rms','_papr_db')]
        arrays={k:f[k] for k in keys} # No logits/predictions loaded.
    ids=arrays['source_row'];require(len(ids)==2496 and len(np.unique(ids))==2496 and np.isin(ids,val).all(),'fixed val membership')
    require(np.array_equal(val[arrays['validation_rank']],ids),'validation rank')
    require([r['index'] for r in records]==list(range(2496)) and np.array_equal(ids,[r['source_row'] for r in records]),'lineage ordering')
    require(array_sha(ids)==p['source_ids_sha256'],'member array SHA')
    return p,records,arrays


def plan():
    require(not (ROOT/'plan.json').exists(),'new plan only');parent,records,arrays=read_parent()
    identities=json.loads((PARENT/'input-identities.json').read_text());paths={r['path'] for r in records}
    source=next(x['path'] for x in identities if x['path'].endswith('/RML2018a.hdf5'));paths.add(source)
    used=[]
    for path in sorted(paths):
        entry=next(x for x in identities if x['path']==path);st=Path(path).stat()
        require(st.st_size==entry['bytes'] and st.st_mtime_ns==entry['mtime_ns'],'parent file metadata '+path)
        used.append(dict(**entry,full_sha_recomputed_this_unit=False))
    p=dict(schema='rml2018a-spectral-geometry-v1',rows=2496,source=source,inputs=used,
        parent=str(PARENT),parent_plan_sha256=sha(PARENT/'plan.json'),selection_sha256=sha(PARENT/'selection.json'),
        script_sha256=sha(__file__),split=parent['split'],source_ids_sha256=parent['source_ids_sha256'],
        model_identity_reference=parent['model']['variant'],model_loaded=False,metrics=PLAN_METRICS,
        budget=dict(cpu_seconds=600,host_bytes=1024**3,new_file_bytes=32*1024**2,new_predictions=0,rf_operations=0),
        identity_scope='Parent manifest SHA plus current size/mtime; fresh selected-row hashes, not full HDF5 rehash',
        tolerances=dict(rms_atol=2e-6,rms_rtol=2e-6,papr_db_atol=2e-5,parseval_rtol=1e-12))
    save(ROOT/'plan.json',p);return p


def summarize(rows,group_keys):
    groups=defaultdict(list)
    for row in rows:groups[tuple(row[k] for k in group_keys)].append(row)
    keys=list(metrics(np.ones(1024))[0]);out=[]
    for group,values in sorted(groups.items()):
        item=dict(zip(group_keys,group));item['n']=len(values)
        for key in keys:
            x=np.array([v[key] for v in values]);item[key+'_mean']=float(x.mean())
            for q in (5,50,95):item[key+f'_p{q}']=float(np.percentile(x,q))
        out.append(item)
    return out


def csv_write(path,rows):
    with Path(path).open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def run():
    p=json.loads((ROOT/'plan.json').read_text());require(p['script_sha256']==sha(__file__) and p['metrics']==PLAN_METRICS,'sealed code/metrics')
    require(not (ROOT/'started.json').exists(),'one execution per root');save(ROOT/'started.json',dict(started_ns=time.time_ns()))
    signal.alarm(600);start=time.monotonic();parent,records,arrays=read_parent();ids=arrays['source_row']
    for entry in p['inputs']:
        st=Path(entry['path']).stat();require(st.st_size==entry['bytes'] and st.st_mtime_ns==entry['mtime_ns'],'input metadata unchanged')
    with h5py.File(p['source'],'r') as f:
        x=f['X'][ids];y=f['Y'][ids].argmax(1);snr=f['Z'][ids].reshape(-1)
    require(np.array_equal(y,arrays['truth']) and np.array_equal(snr,arrays['source_snr_db']),'source labels and source SNR')
    source=np.ascontiguousarray(x.transpose(0,2,1));del x
    groups=defaultdict(list)
    for rec in records:groups[rec['path']].append(rec)
    results=[];lineage=[];spectra=defaultdict(lambda:np.zeros(FFT));counts=defaultdict(int);max_rms=max_papr=0.
    for path,group in sorted(groups.items()):
        with h5py.File(path,'r') as f:
            for rec in group:
                i=rec['index'];g=f[f"blocks/{rec['block']:03d}"];j=int(np.searchsorted(g['source_row'][:],rec['source_row']))
                require(int(g['source_row'][j])==ids[i] and int(g['class_id'][j])==y[i] and float(g['source_snr_db'][j])==snr[i],'processed row labels')
                require(int(g['raw_sample_start'][j])==rec['sample_start'],'ADC coordinate')
                source_rms=np.sqrt(np.mean(np.sum(source[i].astype(float)**2,axis=0)))
                normalized_source=(source[i].astype(float)/source_rms).astype(np.float32)
                require(np.array_equal(g['inputs/source'][j],normalized_source),'archived normalized source exact')
                quality=json.loads(g['quality_json'][j]);hashes={}
                for plane in ('source','raw','guard'):
                    iq=source[i] if plane=='source' else g['inputs/'+plane][j]
                    require(iq.shape==(2,1024),'IQ layout');z=iq[0].astype(float)+1j*iq[1].astype(float)
                    rms=float(np.sqrt(np.mean(abs(z)**2)));papr=float(10*np.log10(np.max(abs(z)**2)/np.mean(abs(z)**2)))
                    require(np.isclose(rms,arrays[plane+'_rms'][i],rtol=2e-6,atol=2e-6),'parent RMS identity')
                    require(abs(papr-arrays[plane+'_papr_db'][i])<=2e-5,'parent PAPR identity')
                    max_rms=max(max_rms,abs(rms-arrays[plane+'_rms'][i]));max_papr=max(max_papr,abs(papr-arrays[plane+'_papr_db'][i]))
                    m,psd=metrics(z);high=bool(snr[i]>=20);hashes[plane]=array_sha(iq)
                    row=dict(index=i,source_row=int(ids[i]),validation_rank=int(arrays['validation_rank'][i]),plane=plane,class_id=int(y[i]),source_snr_db=int(snr[i]),**m)
                    results.append(row)
                    for scope in ('all','high' if high else 'low'):
                        spectra[plane+'_'+scope]+=psd;counts[plane+'_'+scope]+=1
                    if plane!='source':
                        require(bool(g['valid/'+plane][j])==rec['planes'][plane]['usable'],'valid flag')
                        require(quality[plane]['rx_sinr_status']==rec['planes'][plane]['sinr_status'],'quality lineage')
                lineage.append(dict(**rec,selected_iq_sha256=hashes,source_snr_db=int(snr[i]),class_id=int(y[i])))
        print(json.dumps(dict(processed_h5=path,rows=len(lineage))),flush=True)
    require(len(lineage)==2496 and len(results)==7488,'all fixed members retained')
    results.sort(key=lambda r:(r['index'],r['plane']));lineage.sort(key=lambda r:r['index'])
    for plane in ('source','raw','guard'):
        for cls in range(24):
            for z in range(-20,31,2):require(sum(r['plane']==plane and r['class_id']==cls and r['source_snr_db']==z for r in results)==4,'four per class/source SNR')
    csv_write(ROOT/'per_row.csv',results);save(ROOT/'lineage.json',lineage)
    per_snr=summarize(results,['plane','source_snr_db']);csv_write(ROOT/'per_source_snr.csv',per_snr)
    high=[r for r in results if r['source_snr_db']>=20];per_class=summarize(high,['plane','class_id']);csv_write(ROOT/'per_class_high_snr.csv',per_class)
    groupsummary=summarize([dict(r,scope='high' if r['source_snr_db']>=20 else 'low') for r in results],['plane','scope'])
    for key in spectra:spectra[key]/=counts[key]
    np.savez_compressed(ROOT/'mean_spectra.npz',frequency_hz=F,**spectra)
    report=dict(rows=2496,dropped=0,source_snr_high_members=576,groups=groupsummary,
        max_parent_rms_error=max_rms,max_parent_papr_error_db=max_papr,elapsed_seconds=time.monotonic()-start,
        max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        limitations=['Configured analog BW is not a measured brick-wall response','Source PSD contains source noise; high source SNR is separate, not noise-subtracted','Raw/guard already synchronized and normalized; no new ADC replay','Diagnostic val only; no model or accuracy optimization'])
    require(report['max_rss_bytes']<1024**3,'host budget');save(ROOT/'summary.json',report);signal.alarm(0);return report


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('command',choices=['plan','run']);args=a.parse_args()
    def stop(sig,frame):raise RuntimeError(f'spectral diagnostic stop {sig}')
    for sig in (signal.SIGALRM,signal.SIGINT,signal.SIGTERM):signal.signal(sig,stop)
    result={'plan':plan,'run':run}[args.command]();print(json.dumps(result,ensure_ascii=False))
