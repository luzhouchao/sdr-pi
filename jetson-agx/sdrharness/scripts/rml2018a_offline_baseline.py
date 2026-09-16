#!/usr/bin/env python3
"""Bounded validation-only ADC replay and one pilot-amplitude diagnostic; no RF."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import time
import shutil
import collections
import numpy as np
import h5py
import rml2018a_model_collection_eval as ev
import rml2018a_campaign as c
from rml2018a_stream_dsp import Decoder, FRAME_SAMPLES
from rml2018a_campaign_gpu import PayloadBatch
from rml2018a_guard_gpu import GuardBatch
import rml2018a_guard_tone as guard

BASE = Path('/var/tmp/sdrharness-dev')
PRIOR = BASE/'rml2018a-lo-effect-20260915'
EXPORT = BASE/'rml2018a-external-copy-20260914'
DSP_NAMES = ['rml2018a_stream_dsp.py','rml2018a_campaign.py','rml2018a_campaign_gpu.py',
             'rml2018a_guard_gpu.py','rml2018a_guard_tone.py','rml2018a_lo_cancellation.py']


def read_json(p):
    return json.loads(Path(p).read_text())


class NativeView:
    """Read only requested ci16 ranges, retaining original decoder coordinates."""
    def __init__(self, native, base):
        self.native, self.base = native, base

    def __getitem__(self, s):
        q = self.native[s.start+self.base:s.stop+self.base]
        return q[:,0].astype(np.float64)+1j*q[:,1].astype(np.float64)


def array_hash(x):
    return hashlib.sha256(np.ascontiguousarray(x).tobytes()).hexdigest()


def errors(a,b,atol,rtol):
    delta = np.abs(a.astype(np.float64)-b)
    return dict(max_abs=float(delta.max()), rmse=float(np.sqrt(np.mean(delta**2))),
                passed=bool(np.allclose(a,b,atol=atol,rtol=rtol)),
                changed_values=int(np.count_nonzero(delta)))


def main(out):
    started=time.monotonic()
    def check():
        if time.monotonic()-started>1800 or (out/'STOP').exists():
            raise InterruptedError('finite deadline/STOP')
    def stop(*_):
        raise InterruptedError('signal')
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGALRM): signal.signal(sig,stop)
    signal.alarm(1800)
    ev.require(not (out/'plan.json').exists(),'fresh experiment')
    ids=np.load(PRIOR/'normalization-source-rows.npy',allow_pickle=False)
    val,split=ev.load_validation_split(ev.ASSET/'splits/server-seed42-20260914/RML2018a_split_seed42_tr700_val150_te150.npz',ev.SEED42_SPLIT_SHA)
    ev.require(len(ids)==2496 and len(np.unique(ids))==2496 and np.isin(ids,val).all(),'fixed validation IDs')
    parent=read_json(ev.ASSET/'results/mamba-source-raw-val-allquality-20260915/plan.json')
    spec=parent['models'][0]
    ev.require(spec['variant']=='amc_mamba_d8' and spec['seed']==42,'original D8 seed42')
    manifest=read_json(ev.COLLECTION/'manifest.json')
    for rec in manifest['transferred_files']:
        ev.require(ev.digest(ev.COLLECTION/rec['relative'])==rec['sha256'],'imported model identity')
    mapping=read_json(EXPORT/'dataset-map.json')['snr_groups']
    export={r['source']:r for r in read_json(EXPORT/'plan.json')['files']}
    paths={k:ev.CLEAN/f'RadioML2018A_RX_{k}_1024_per_window_RMS_v1.h5' for k in ('raw','guard')}
    paths['source']=ev.ASSET/'datasets/rml2018a/RML2018a.hdf5'
    selection=[];saved={};meta={}
    for plane in ('raw','guard'):
        with h5py.File(paths[plane],'r') as f:
            order=np.argsort(f['source_row'][:]); rows=order[ids]
            # HDF5 fancy reads require storage ordering.
            ix=np.argsort(rows); rev=np.argsort(ix)
            saved[plane]=f['iq'][rows[ix]][rev]
            keys=['quality_flags','usable','strict_quality_pass','guard_applied','source_h5_index','source_block_index','raw_sample_start','class_id','source_snr_db','frame_index']
            meta[plane]={k:f[k][rows[ix]][rev] for k in keys}
            meta[plane]['dataset_row']=rows
            if plane=='raw':
                pths=f['source_h5_paths'].asstr()[:]
                for i,row in enumerate(ids):
                    p=BASE/Path(pths[meta[plane]['source_h5_index'][i]]).relative_to('corpus')
                    entry=next(e for e in mapping if Path(e['original_root'])==p.parent)
                    selection.append(dict(index=i,source_row=int(row),path=str(p),block=int(meta[plane]['source_block_index'][i]),
                        frame=int(meta[plane]['frame_index'][i]),sample_start=int(meta[plane]['raw_sample_start'][i]),
                        raw_path=str(BASE/Path(entry['raw_iq']).relative_to('corpus')),frames=str(BASE/Path(entry['frames_directory']).relative_to('corpus'))))
    with h5py.File(paths['source'],'r') as f:
        source=np.ascontiguousarray(f['X'][ids].transpose(0,2,1)); y=f['Y'][ids].argmax(1); z=f['Z'][ids].reshape(-1)
    for plane in ('raw','guard'):
        ev.require(np.array_equal(meta[plane]['class_id'],y) and np.array_equal(meta[plane]['source_snr_db'],z),'labels/Z')
    raw_paths=sorted({r['raw_path'] for r in selection})
    plan=dict(schema='adc-replay-pilot-amplitude-validation-v1',head=__import__('subprocess').check_output(['git','rev-parse','HEAD'],text=True).strip(),
        script=ev.identity(__file__),split=split,model=spec,source_ids_sha256=array_hash(ids),rows=len(ids),
        selection='existing 4 evenly spaced common-quality validation rows per 24 classes x 26 source SNR; no new filtering',
        sync_scope='re-run unchanged pilot tracking from archived predecessor state; not independent full-stream reacquisition',
        tolerance=dict(iq_atol=2e-6,iq_rtol=2e-6,logits_atol=2e-4,logits_rtol=2e-4,top1_agreement=1.0,discrete_metadata='exact'),
        candidate='same synchronized payload divided by pilot-only channel amplitude: |gain to unscaled marker|/sqrt(10); no source payload or labels',
        budget=dict(deadline_seconds=1800,host_bytes=8*1024**3,gpu_bytes=4*1024**3,new_file_bytes=512*1024**2,free_bytes=shutil.disk_usage(out).free,
                    maximum_context_read_bytes=len(ids)*65535*4,raw_files=len(raw_paths),new_predictions=len(ids)*8),
        no_training=True,no_rf=True,production_changes=False)
    ev.require(plan['budget']['free_bytes']>2*1024**3,'space')
    ev.atomic(out/'plan.json',plan);ev.atomic(out/'selection.json',selection)
    identities=[]
    # Full hashes of ADC/HDF5 used, plus all selected frame/configuration records.
    need=set(raw_paths)|{r['path'] for r in selection}|{str(p) for p in paths.values()}
    for r in selection:
        need.add(str(Path(r['path']).parent/'configuration.json'))
        need.add(str(Path(r['path']).parent/'raw.sigmf-meta'))
        need.add(str(Path(r['frames']).parent/'plan.json'))
        b=r['frame']//64
        need.add(str(Path(r['frames'])/f'{b:03d}.json'))
        if b:need.add(str(Path(r['frames'])/f'{b-1:03d}.json'))
    for p in sorted(need):
        check()
        expected=export.get(p,{}).get('sha256')
        if p==str(paths['source']):expected=ev.ORIGINAL_SHA
        if p in (str(paths['raw']),str(paths['guard'])):expected=read_json(p+'.manifest.json')['sha256']
        identities.append(ev.identity(p,expected))
    ev.atomic(out/'input-identities.json',identities)
    print(json.dumps(dict(stage='identities',files=len(identities),seconds=time.monotonic()-started)),flush=True)
    software=[]
    for frames in sorted({r['frames'] for r in selection}):
        old=read_json(Path(frames).parent/'plan.json')
        for name in DSP_NAMES:
            path=Path(__file__).with_name(name);expected=old['software'][str(path)]
            ev.require(ev.digest(path)==expected,'historical DSP differs: '+str(path))
            software.append(dict(plan=str(Path(frames).parent/'plan.json'),path=str(path),sha256=expected))
    ev.atomic(out/'software-identities.json',software)
    torch=ev.setup(out); gpu=PayloadBatch(); batch=GuardBatch(torch)
    replay={k:np.empty_like(source) for k in ('raw','guard')}
    candidate={k:np.empty_like(source) for k in ('raw','guard')}
    records=[];frames_cache={};frame_results={}
    groups=collections.defaultdict(list)
    for r in selection:groups[r['raw_path']].append(r)
    for raw_path,rs in groups.items():
        native=np.memmap(raw_path,dtype='<i2',mode='r').reshape(-1,2)
        for r in rs:
            check(); i=r['index']; frame=r['frame']; block=frame//64
            frames_path=Path(r['frames'])/f'{block:03d}.json'
            if str(frames_path) not in frames_cache:frames_cache[str(frames_path)]=read_json(frames_path)
            archive=frames_cache[str(frames_path)]; archived=archive[frame%64]
            if block:
                pp=Path(r['frames'])/f'{block-1:03d}.json'
                if str(pp) not in frames_cache:frames_cache[str(pp)]=read_json(pp)
                prevblock=frames_cache[str(pp)]
                base=prevblock[-1]['marker_offset']+FRAME_SAMPLES-384
            else:base=0
            key=(raw_path,frame)
            if key not in frame_results:
                cp=read_json(Path(r['frames']).parent/'plan.json')
                d=Decoder(cp['run_id'],None,gpu,'cpu',source_loader=lambda _:None,total_blocks=192)
                d.frame=frame;d.samples=NativeView(native,base)
                if frame:
                    prev=archive[frame%64-1] if frame%64 else prevblock[-1]
                    d.hz=prev['cfo_hz'];predicted=prev['marker_offset']+FRAME_SAMPLES-base
                else:
                    # Independently recover the first coarse marker/CFO from first 1M ADC samples.
                    d.samples=NativeView(native,0)[slice(0,1048576)]
                    d.find_first();predicted=d.marker;d.samples=NativeView(native,0)
                at,hz,phase,score=d.track(predicted)
                global_at=at+base;global_phase=phase+2*np.pi*hz*base/c.RATE
                ev.require(global_at==archived['marker_offset'],'marker sample mismatch')
                ev.require(abs(hz-archived['cfo_hz'])<1e-8 and abs(global_phase-archived['phase_rotation_rad'])<1e-7,'sync numeric mismatch')
                raw=NativeView(native,0)[slice(global_at-256,global_at-256+65535)]
                sync=dict(marker_offset=256,payload_marker_offset=256,estimated_cfo_hz=hz)
                fit=batch.fit([raw],[sync],16)[0]
                corrected,info=guard.cancel(raw,sync,16,pilot_only=True,frequency_fit=fit)
                ev.require((info['status'],info['reason'])==(archived['guard']['status'],archived['guard']['reason']),'guard decision mismatch')
                positions=np.arange(at+1024,at+1024+16384)
                rx=raw[1280:1280+16384]*np.exp(-2j*np.pi*hz*positions/c.RATE+1j*phase)
                gpositions=positions+base
                gx=corrected[1280:1280+16384]*np.exp(-2j*np.pi*hz*gpositions/c.RATE+1j*global_phase)
                # Exactly the same filtered pilot and CFO as tracking; magnitude removes coordinate phase.
                lo=max(0,predicted-128);hi=predicted+1024+128
                local=np.convolve(d.samples[slice(max(0,lo-64),hi+64)],d.fir,mode='same')
                trim=lo-max(0,lo-64);local=local[trim:trim+hi-lo]*np.exp(-2j*np.pi*hz*np.arange(lo,hi)/c.RATE)
                ref=np.convolve(c.marker(cp['run_id'],frame),d.fir,mode='same')
                gain=abs(np.vdot(ref,local[at-lo:at-lo+1024])/np.vdot(ref,ref))/np.sqrt(10.)
                ev.require(np.isfinite(gain) and gain>0,'identifiable pilot gain')
                frame_results[key]=(rx.reshape(16,1024),gx.reshape(16,1024),gain,info,dict(
                    context_sha256=array_hash(native[global_at-256:global_at-256+65535]),marker_error_samples=global_at-archived['marker_offset'],
                    cfo_error_hz=hz-archived['cfo_hz'],phase_error_rad=global_phase-archived['phase_rotation_rad'],marker_score=score))
            rx,gx,gain,info,syn=frame_results[key]
            wi=(r['sample_start']-(archived['marker_offset']+1024))//1024
            ev.require(0<=wi<16 and r['sample_start']==archived['marker_offset']+1024+wi*1024,'window offset')
            with h5py.File(r['path'],'r') as old:
                g=old[f"blocks/{r['block']:03d}"];j=int(np.searchsorted(g['source_row'][:],r['source_row']))
                ev.require(int(g['source_row'][j])==r['source_row'] and int(g['class_id'][j])==int(y[i]) and float(g['source_snr_db'][j])==z[i],'archived label/row')
                q=read_json_bytes(g['quality_json'][j]); row=dict(r,window_in_frame=wi,pilot_gain=gain,sync=syn,guard_status=info['status'],guard_reason=info['reason'],planes={})
                for plane,values in [('raw',rx),('guard',gx)]:
                    value=values[wi:wi+1];a=gpu.normalize(value)[0];replay[plane][i]=a
                    b=g['inputs/'+plane][j]
                    err=errors(a,b,2e-6,2e-6);ev.require(err['passed'],'ADC IQ tolerance exceeded')
                    ev.require(np.array_equal(b,saved[plane][i]),'clean IQ differs')
                    qq=gpu.quality(source[i:i+1,0].astype(np.float64)+1j*source[i:i+1,1],value,np.array([z[i]]))[0]
                    ev.require((qq['rx_sinr_status'],qq['rx_sinr_reason'])==(q[plane]['rx_sinr_status'],q[plane]['rx_sinr_reason']),'quality mismatch')
                    flags=(int(g['valid/'+plane][j])*1+2+4*int(info['status']=='applied')+8*int(qq['rx_sinr_status']=='estimated')+16*int(qq['rx_sinr_db'] is not None and np.isfinite(qq['rx_sinr_db']))+32)
                    ev.require(flags==int(meta[plane]['quality_flags'][i]),'quality flags mismatch')
                    calibrated=value[0]/gain
                    candidate[plane][i]=np.stack((calibrated.real,calibrated.imag)).astype(np.float32)
                    row['planes'][plane]=dict(error=err,quality_flags=flags,usable=bool(meta[plane]['usable'][i]),strict_quality_pass=bool(meta[plane]['strict_quality_pass'][i]),
                        received_rms=float(np.sqrt(np.mean(abs(value)**2))),sinr_status=qq['rx_sinr_status'],sinr_reason=qq['rx_sinr_reason'],conditional_effective_sinr_db=qq['rx_sinr_db'],
                        conditional_sinr_error_db=None if qq['rx_sinr_db'] is None else qq['rx_sinr_db']-q[plane]['rx_sinr_db'])
            records.append(row)
        print(json.dumps(dict(stage='adc_replay',rows=len(records),seconds=time.monotonic()-started)),flush=True)
        # Do not retain full frame waveforms after each raw file.
        frame_results.clear();del native
    ev.atomic(out/'baseline-rows.json',records)
    baseline=dict(rows=len(ids),planes={p:dict(max_abs=max(r['planes'][p]['error']['max_abs'] for r in records),
        max_rmse=max(r['planes'][p]['error']['rmse'] for r in records)) for p in replay},discrete_metadata_exact=True,sync_conditioned_on_archived_predecessor=True)
    ev.atomic(out/'baseline-inputs.json',baseline)
    model=ev.load_model(spec,torch)
    rms=np.sqrt(np.mean(np.sum(source.astype(np.float64)**2,axis=1),axis=1))
    variants=dict(source=source,source_rms=np.asarray(source/rms[:,None,None],dtype=np.float32),
        raw=replay['raw'],guard=replay['guard'],raw_pilot=candidate['raw'],guard_pilot=candidate['guard'],
        archived_raw=saved['raw'],archived_guard=saved['guard'])
    logits={};stats={}
    for name,x in variants.items():
        check();logits[name]=np.concatenate([ev.predict(model,x[a:a+1024],torch,'fp32') for a in range(0,len(x),1024)])
        power=np.sum(x.astype(np.float64)**2,axis=1)
        stats[name]=dict(rms=np.sqrt(power.mean(1)),papr_db=10*np.log10(power.max(1)/power.mean(1)))
    baseline['model']={p:dict(**errors(logits[p],logits['archived_'+p],2e-4,2e-4),top1_agreement=float(np.mean(logits[p].argmax(1)==logits['archived_'+p].argmax(1)))) for p in ('raw','guard')}
    for b in baseline['model'].values():ev.require(b['passed'] and b['top1_agreement']==1.,'baseline model mismatch')
    # Independently compare with persisted same-model validation predictions.
    prior_checks={}
    for plane in ('source','raw','guard'):
        root=ev.ASSET/'results'/('mamba-guard-val-allquality-20260915' if plane=='guard' else 'mamba-source-raw-val-allquality-20260915')
        dsrows=ids if plane=='source' else meta[plane]['dataset_row']; oldlog=np.empty_like(logits[plane])
        for block in np.unique(dsrows//16384):
            p=root/'amc_mamba_d8-seed42'/plane/f'{block*16384:07d}.npz'
            with np.load(p,allow_pickle=False) as f:
                take=np.flatnonzero(dsrows//16384==block);at=np.searchsorted(f['dataset_row'],dsrows[take])
                ev.require(np.array_equal(f['dataset_row'][at],dsrows[take]),'saved prediction membership');oldlog[take]=f['logits'][at]
        b=dict(**errors(logits[plane],oldlog,2e-4,2e-4),top1_agreement=float(np.mean(logits[plane].argmax(1)==oldlog.argmax(1))))
        prior_checks[plane]=b
    baseline['prior_predictions']=prior_checks
    ev.atomic(out/'baseline.json',baseline)
    ev.require(all(b['passed'] and b['top1_agreement']==1. for b in prior_checks.values()),'persisted logits mismatch')
    pairs=[('source','source_rms'),('raw','guard'),('raw','raw_pilot'),('guard','guard_pilot'),('raw_pilot','guard_pilot')]
    def summarize(mask):
        result=dict(rows=int(mask.sum()),correct={k:int(((v.argmax(1)==y)&mask).sum()) for k,v in logits.items()},pairs=[])
        for a,b in pairs:
            ac=logits[a].argmax(1)==y;bc=logits[b].argmax(1)==y
            result['pairs'].append(dict(before=a,after=b,corrected=int((~ac&bc&mask).sum()),regressed=int((ac&~bc&mask).sum()),
                changed_top1=int(((logits[a].argmax(1)!=logits[b].argmax(1))&mask).sum())))
        result['input_distribution']={k:{q:np.percentile(v[mask],[0,5,50,95,100]).tolist() for q,v in vs.items()} for k,vs in stats.items()}
        return result
    result=dict(overall=summarize(np.ones(len(ids),bool)),per_class=[dict(label=parent['classes'][cc],**summarize(y==cc)) for cc in range(24)],
        per_source_snr=[dict(source_snr_db=int(zz),**summarize(z==zz)) for zz in sorted(set(z))],
        per_class_source_snr=[dict(class_id=cc,source_snr_db=int(zz),**summarize((y==cc)&(z==zz))) for cc in range(24) for zz in sorted(set(z))],
        guard_reasons=dict(collections.Counter(str(r['guard_reason']) for r in records)),quality_failures_retained={p:int((~meta[p]['strict_quality_pass']).sum()) for p in ('raw','guard')},
        elapsed_seconds=time.monotonic()-started,peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(),validation_only=True)
    ev.require(result['peak_cuda_allocated_bytes']<=4*1024**3,'GPU budget')
    np.savez(out/'predictions.npz',source_row=ids,validation_rank=np.searchsorted(val,ids),truth=y,source_snr_db=z,
             **{k+'_logits':v for k,v in logits.items()},**{k+'_'+q:v for k,vs in stats.items() for q,v in vs.items()})
    ev.atomic(out/'results.json',result)
    for record in identities:ev.unchanged(record)
    print(json.dumps(dict(stage='complete',baseline=baseline,overall=result['overall']['correct'],seconds=result['elapsed_seconds'])),flush=True)
    signal.alarm(0)


def read_json_bytes(value):
    return json.loads(value)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    try:main(args.output)
    finally:
        cache=ev.cache_root(args.output)
        if cache.exists():
            files=[p for p in cache.rglob('*') if p.is_file()]
            ev.atomic(args.output/'cache-cleanup.json',dict(path=str(cache.resolve()),files=len(files),bytes=sum(p.stat().st_size for p in files)))
            shutil.rmtree(cache)
            ev.require(not cache.exists(),'cache cleanup')
